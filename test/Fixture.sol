// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {Test} from "forge-std/Test.sol";
import {MockToken} from "../contracts/tokens/MockToken.sol";
import {ConstantProductAMM} from "../contracts/amm/ConstantProductAMM.sol";
import {SpotOracle} from "../contracts/oracles/SpotOracle.sol";
import {LendingMarket} from "../contracts/lending/LendingMarket.sol";
import {FlashLender} from "../contracts/FlashLender.sol";
import {AttackExecutor} from "../contracts/AttackExecutor.sol";

/// @notice Shared deploy+seed fixture matching scenarios/vulnerable.json
/// (SPEC Appendix defaults). Deploy order per SPEC §3: USD -> COL -> AMM ->
/// Oracle(AMM) -> LendingMarket -> FlashLender -> AttackExecutor. Values here
/// must stay in sync with scenarios/vulnerable.json (Phase 3) so the Python
/// bridge replay reproduces identical numbers.
abstract contract Fixture is Test {
    uint256 constant AMM_RESERVE_USD = 1_000_000e18;
    uint256 constant AMM_RESERVE_COL = 1_000_000e18;
    uint256 constant LENDING_USD_LIQUIDITY = 500_000e18;
    uint256 constant COLLATERAL_FACTOR_BPS = 7500;
    uint256 constant FLASH_FEE_BPS = 9;
    uint256 constant ATTACKER_INITIAL_CAPITAL_USD = 10_000e18;
    uint256 constant REFERENCE_PRICE_USD = 1e18;

    MockToken usd;
    MockToken col;
    ConstantProductAMM amm;
    SpotOracle oracle;
    LendingMarket lending;
    FlashLender flashLender;
    AttackExecutor executor;

    address attacker = address(0xA77ACC);
    address liquidityProvider = address(0x1101);

    function setUpFixture() internal {
        usd = new MockToken("USD", "USD");
        col = new MockToken("Collateral", "COL");
        amm = new ConstantProductAMM(address(usd), address(col), 0);
        oracle = new SpotOracle(address(amm));
        lending = new LendingMarket(address(oracle), address(usd), address(col), COLLATERAL_FACTOR_BPS);
        flashLender = new FlashLender(address(usd), address(col), FLASH_FEE_BPS);

        vm.prank(attacker);
        executor = new AttackExecutor(
            address(amm), address(0), address(oracle), address(lending), address(flashLender), address(usd), address(col)
        );

        // Seed AMM liquidity.
        usd.mint(liquidityProvider, AMM_RESERVE_USD);
        col.mint(liquidityProvider, AMM_RESERVE_COL);
        vm.startPrank(liquidityProvider);
        usd.approve(address(amm), type(uint256).max);
        col.approve(address(amm), type(uint256).max);
        amm.addLiquidity(AMM_RESERVE_USD, AMM_RESERVE_COL);
        vm.stopPrank();

        // Seed lending-market USD reserves.
        usd.mint(address(this), LENDING_USD_LIQUIDITY);
        usd.approve(address(lending), type(uint256).max);
        lending.seedLiquidity(LENDING_USD_LIQUIDITY);

        // Flash-loan liquidity, generous headroom above AMM reserves so
        // candidates can flash-borrow up to the full pool size.
        usd.mint(address(flashLender), 2 * AMM_RESERVE_USD);
        col.mint(address(flashLender), 2 * AMM_RESERVE_COL);

        // Modeled attacker starting capital (SPEC §1 "Fund the attacker EOA
        // with the modeled initial capital") — an evaluator-side accounting
        // baseline (§7 deducts it from profit); the MVP flash-loan-only
        // exploit never actually needs to move it into AttackExecutor.
        usd.mint(attacker, ATTACKER_INITIAL_CAPITAL_USD);
    }
}
