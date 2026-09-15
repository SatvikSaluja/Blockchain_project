// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "./tokens/IERC20.sol";
import {ConstantProductAMM} from "./amm/ConstantProductAMM.sol";
import {LendingMarket, IOracle} from "./lending/LendingMarket.sol";
import {FlashLender, IFlashLoanReceiver} from "./FlashLender.sol";

/// @notice On-chain interpreter for a candidate attack (SPEC §3.6). Opens a
/// fixed flash-loan wrapper, runs the inner Action[] program inside the
/// callback, then pushes repayment. A revert anywhere means "invalid
/// candidate" to the search engine — it never needs to know why.
contract AttackExecutor is IFlashLoanReceiver {
    enum ActionType {
        SWAP_USD_FOR_COL,
        SWAP_COL_FOR_USD,
        DEPOSIT_COL,
        BORROW_USD,
        REPAY_USD,
        WITHDRAW_COL
    }

    enum AmountRule {
        FIXED,
        PCT_BALANCE,
        FRAC_RESERVES,
        PCT_BORROW_CAPACITY
    }

    struct Action {
        uint8 actionType; // ActionType
        address target; // token or market address (context-dependent)
        uint8 amountRule; // AmountRule
        uint256 amountParam; // absolute amount OR bps, per rule
    }

    /// @notice Per-action trace record (SPEC §9 execution_trace.json). Emitted
    /// after each action so the Python side can reconstruct pre/post state
    /// for every step of a single atomic transaction — `preState` for index
    /// i is just index i-1's post-state (or the pre-tx baseline for i=0).
    event ActionExecuted(
        uint256 index,
        uint8 actionType,
        uint256 resolvedAmount,
        uint256 attackerUsd,
        uint256 attackerCol,
        uint256 reserveUsd,
        uint256 reserveCol,
        uint256 oraclePrice,
        uint256 debtUsd,
        uint256 collateralCol
    );

    uint256 public constant MAX_ACTIONS = 6;

    ConstantProductAMM public immutable amm;
    IOracle public immutable oracle;
    LendingMarket public immutable lending;
    FlashLender public immutable flashLender;
    IERC20 public immutable usd;
    IERC20 public immutable col;
    address public immutable owner;

    constructor(address _amm, address _oracle, address _lending, address _flashLender, address _usd, address _col) {
        amm = ConstantProductAMM(_amm);
        oracle = IOracle(_oracle);
        lending = LendingMarket(_lending);
        flashLender = FlashLender(_flashLender);
        usd = IERC20(_usd);
        col = IERC20(_col);
        owner = msg.sender;

        // Approve the two contracts this executor ever pushes funds through.
        usd.approve(_amm, type(uint256).max);
        col.approve(_amm, type(uint256).max);
        usd.approve(_lending, type(uint256).max);
        col.approve(_lending, type(uint256).max);
    }

    /// @notice Entry point. `flashToken`/`flashAmount` define the fixed
    /// outer wrapper; `actions` run inside `onFlashLoan`. Reverts propagate.
    function executeAttack(address flashToken, uint256 flashAmount, Action[] calldata actions) external {
        require(msg.sender == owner, "AttackExecutor: not owner");
        require(actions.length <= MAX_ACTIONS, "AttackExecutor: too many actions");
        flashLender.flashLoan(flashToken, flashAmount, abi.encode(actions));
    }

    function onFlashLoan(address token, uint256 amount, uint256 fee, bytes calldata data) external {
        require(msg.sender == address(flashLender), "AttackExecutor: not flash lender");
        Action[] memory actions = abi.decode(data, (Action[]));

        for (uint256 i = 0; i < actions.length; i++) {
            uint256 resolvedAmount = _run(actions[i]);
            (uint256 rUsd, uint256 rCol) = amm.getReserves();
            emit ActionExecuted(
                i,
                actions[i].actionType,
                resolvedAmount,
                usd.balanceOf(address(this)),
                col.balanceOf(address(this)),
                rUsd,
                rCol,
                oracle.price(),
                lending.debtOf(address(this)),
                lending.collateralOf(address(this))
            );
        }

        require(IERC20(token).transfer(address(flashLender), amount + fee), "AttackExecutor: repay failed");
    }

    function _run(Action memory a) internal returns (uint256 amt) {
        ActionType t = ActionType(a.actionType);
        AmountRule r = AmountRule(a.amountRule);

        if (t == ActionType.SWAP_USD_FOR_COL) {
            require(a.target == address(amm), "AttackExecutor: bad target");
            (uint256 rUsd,) = amm.getReserves();
            amt = _min(_resolve(r, a.amountParam, usd, rUsd), usd.balanceOf(address(this)));
            if (amt > 0) amm.swapUsdForCol(amt);
        } else if (t == ActionType.SWAP_COL_FOR_USD) {
            require(a.target == address(amm), "AttackExecutor: bad target");
            (, uint256 rCol) = amm.getReserves();
            amt = _min(_resolve(r, a.amountParam, col, rCol), col.balanceOf(address(this)));
            if (amt > 0) amm.swapColForUsd(amt);
        } else if (t == ActionType.DEPOSIT_COL) {
            require(a.target == address(lending), "AttackExecutor: bad target");
            (, uint256 rCol) = amm.getReserves();
            amt = _min(_resolve(r, a.amountParam, col, rCol), col.balanceOf(address(this)));
            if (amt > 0) lending.depositCollateral(amt);
        } else if (t == ActionType.BORROW_USD) {
            require(a.target == address(lending), "AttackExecutor: bad target");
            (uint256 rUsd,) = amm.getReserves();
            amt = _min(_resolve(r, a.amountParam, usd, rUsd), _borrowCapacity());
            if (amt > 0) lending.borrow(amt);
        } else if (t == ActionType.REPAY_USD) {
            require(a.target == address(lending), "AttackExecutor: bad target");
            (uint256 rUsd,) = amm.getReserves();
            amt = _min(_resolve(r, a.amountParam, usd, rUsd), usd.balanceOf(address(this)));
            if (amt > 0) lending.repay(amt);
        } else {
            // WITHDRAW_COL
            require(a.target == address(lending), "AttackExecutor: bad target");
            (, uint256 rCol) = amm.getReserves();
            amt = _min(_resolve(r, a.amountParam, col, rCol), lending.collateralOf(address(this)));
            if (amt > 0) lending.withdrawCollateral(amt);
        }
    }

    /// @dev Amount-rule resolution against live state (SPEC §3.6 table).
    function _resolve(AmountRule r, uint256 param, IERC20 balToken, uint256 relevantReserve)
        internal
        view
        returns (uint256)
    {
        if (r == AmountRule.FIXED) return param;
        if (r == AmountRule.PCT_BALANCE) return (balToken.balanceOf(address(this)) * param) / 1e4;
        if (r == AmountRule.FRAC_RESERVES) return (relevantReserve * param) / 1e4;
        return (_borrowCapacity() * param) / 1e4; // PCT_BORROW_CAPACITY
    }

    function _borrowCapacity() internal view returns (uint256) {
        uint256 colValueUsd = (lending.collateralOf(address(this)) * oracle.price()) / 1e18;
        uint256 maxDebtUsd = (colValueUsd * lending.collateralFactorBps()) / 1e4;
        uint256 debtUsd = lending.debtOf(address(this));
        return maxDebtUsd > debtUsd ? maxDebtUsd - debtUsd : 0;
    }

    function _min(uint256 a, uint256 b) internal pure returns (uint256) {
        return a < b ? a : b;
    }
}
