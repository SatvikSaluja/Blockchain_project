// SPDX-License-Identifier: MIT
pragma solidity ^0.8.24;

import {ConstantProductAMM} from "../amm/ConstantProductAMM.sol";

/// @notice Reads the AMM's live reserves as the price. THIS IS THE
/// VULNERABILITY (SPEC §3.3): an attacker who moves reserves within the same
/// transaction moves this price, and LendingMarket trusts it unconditionally.
/// TWAPOracle (SPEC §13.1) is the fix; not part of the MVP.
contract SpotOracle {
    ConstantProductAMM public immutable amm;

    constructor(address _amm) {
        amm = ConstantProductAMM(_amm);
    }

    function price() external view returns (uint256) {
        return amm.spotPrice();
    }
}
