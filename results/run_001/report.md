# Exploit Report

**Seed:** 1337
**Violated property:** `debt_exceeds_collateral_at_reference_price`

## Scenario

| Parameter | Value |
|---|---|
| AMM reserves (USD / COL) | 1,000,000.0000 / 1,000,000.0000 |
| AMM fee | 0 bps |
| Lending USD liquidity | 500,000.0000 |
| Collateral factor | 7500 bps |
| Flash-loan fee | 9 bps |
| Attacker initial capital | 10,000.0000 |
| Reference price (USD per COL) | 1.0000 |

## Minimized Attack

Flash-borrow **USD** 287,493.6134, then:

1. `SWAP_USD_FOR_COL` — resolved amount **287,493.6134**
   - oracle price: 1.0000 → 1.6576
   - reserves (USD/COL): 1,000,000.0000/1,000,000.0000 → 1,287,493.6134/776,702.8820
   - debt: 0.0000 → 0.0000
   - collateral: 0.0000 → 0.0000
2. `DEPOSIT_COL` — resolved amount **55,801.9498**
   - oracle price: 1.6576 → 1.6576
   - reserves (USD/COL): 1,287,493.6134/776,702.8820 → 1,287,493.6134/776,702.8820
   - debt: 0.0000 → 0.0000
   - collateral: 0.0000 → 55,801.9498
3. `BORROW_USD` — resolved amount **69,374.6499**
   - oracle price: 1.6576 → 1.6576
   - reserves (USD/COL): 1,287,493.6134/776,702.8820 → 1,287,493.6134/776,702.8820
   - debt: 0.0000 → 69,374.6499
   - collateral: 55,801.9498 → 55,801.9498
4. `SWAP_COL_FOR_USD` — resolved amount **167,495.1682**
   - oracle price: 1.6576 → 1.1217
   - reserves (USD/COL): 1,287,493.6134/776,702.8820 → 1,059,099.8359/944,198.0502
   - debt: 69,374.6499 → 69,374.6499
   - collateral: 55,801.9498 → 55,801.9498
Then repay the flash loan (principal + fee).

## Result

| Metric | Value |
|---|---|
| Attacker profit (USD, at reference price) | 0.0007 |
| Protocol bad debt (USD, at reference price) | 13,572.7001 |
| Gas used | 267817 |

## Reproduce

Solidity (self-contained, re-proves the finding from scratch):

```
forge test --match-path test/generated/ExploitReproducer_1337.t.sol -vv
```

Python bridge (exact replay of this run):

```
python -m engine.cli scenarios/vulnerable.json --seed 1337 --strategy random
```