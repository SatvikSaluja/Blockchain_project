// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {IERC20} from "../tokens/IERC20.sol";

/// @notice Uniswap-v2-style x*y=k pool. Configurable swap fee (SPEC §13.3 —
/// "add a configurable fee later" was v1's own note; default 0 everywhere in
/// this repo keeps the manipulation math exact for the hand-derived Phase-2
/// exploit, and existing scenarios/deployments are unaffected by this field
/// existing). Fee is taken on the input, Uniswap-v2 style: the trader pays
/// the full amount, output is computed on the fee-reduced amount, and the
/// fee itself stays in reserves — so k strictly increases when feeBps > 0
/// instead of merely holding, and is byte-for-byte the old zero-fee formula
/// when feeBps == 0.
contract ConstantProductAMM {
    IERC20 public immutable usd;
    IERC20 public immutable col;
    uint256 public immutable feeBps; // e.g. 30 = 0.30%, matching Uniswap v2's default

    uint256 public reserveUsd;
    uint256 public reserveCol;

    constructor(address _usd, address _col, uint256 _feeBps) {
        usd = IERC20(_usd);
        col = IERC20(_col);
        feeBps = _feeBps;
    }

    function addLiquidity(uint256 usdAmount, uint256 colAmount) external {
        require(usd.transferFrom(msg.sender, address(this), usdAmount), "AMM: usd transfer failed");
        require(col.transferFrom(msg.sender, address(this), colAmount), "AMM: col transfer failed");
        reserveUsd += usdAmount;
        reserveCol += colAmount;
    }

    function getReserves() external view returns (uint256 rUsd, uint256 rCol) {
        return (reserveUsd, reserveCol);
    }

    /// @dev Exact-in swap. `out = (rOut * inWithFee) / (rIn + inWithFee)`,
    /// `inWithFee = in * (1e4 - feeBps) / 1e4`. Reverts on zero-out or a k
    /// decrease.
    function swapUsdForCol(uint256 usdIn) external returns (uint256 colOut) {
        require(usdIn > 0, "AMM: zero in");
        uint256 rUsd = reserveUsd;
        uint256 rCol = reserveCol;
        uint256 usdInWithFee = (usdIn * (1e4 - feeBps)) / 1e4;
        colOut = (rCol * usdInWithFee) / (rUsd + usdInWithFee);
        require(colOut > 0, "AMM: zero out");

        require(usd.transferFrom(msg.sender, address(this), usdIn), "AMM: usd transfer failed");
        uint256 newUsd = rUsd + usdIn;
        uint256 newCol = rCol - colOut;
        require(newUsd * newCol >= rUsd * rCol, "AMM: k violated");
        reserveUsd = newUsd;
        reserveCol = newCol;
        require(col.transfer(msg.sender, colOut), "AMM: col transfer failed");
    }

    function swapColForUsd(uint256 colIn) external returns (uint256 usdOut) {
        require(colIn > 0, "AMM: zero in");
        uint256 rUsd = reserveUsd;
        uint256 rCol = reserveCol;
        uint256 colInWithFee = (colIn * (1e4 - feeBps)) / 1e4;
        usdOut = (rUsd * colInWithFee) / (rCol + colInWithFee);
        require(usdOut > 0, "AMM: zero out");

        require(col.transferFrom(msg.sender, address(this), colIn), "AMM: col transfer failed");
        uint256 newCol = rCol + colIn;
        uint256 newUsd = rUsd - usdOut;
        require(newUsd * newCol >= rUsd * rCol, "AMM: k violated");
        reserveUsd = newUsd;
        reserveCol = newCol;
        require(usd.transfer(msg.sender, usdOut), "AMM: usd transfer failed");
    }

    /// @notice USD per 1 COL, 1e18-scaled. This is the manipulable price the
    /// vulnerable SpotOracle trusts directly (SPEC §3.3).
    function spotPrice() external view returns (uint256) {
        require(reserveCol > 0, "AMM: no col reserve");
        return (reserveUsd * 1e18) / reserveCol;
    }
}
