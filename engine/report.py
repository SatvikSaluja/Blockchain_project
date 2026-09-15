"""Human/machine-readable exploit reporting (SPEC §9): attack.json,
execution_trace.json, and report.md. Also owns address<->symbol resolution
("USD"/"COL"/"AMM"/"LENDING" instead of raw hex) since every one of these
outputs needs it.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Optional

from jinja2 import Environment
from web3.logs import DISCARD

from engine.actions import ActionType, Candidate
from engine.deploy import Deployment
from engine.evaluator import Evaluation
from engine.observer import EconState
from engine.scenario import Scenario


def symbol_for(address: str, deployment: Deployment) -> str:
    """Human-readable label for an address, matching the SPEC Appendix
    attack.json example ("USD", "AMM", ...) instead of raw hex."""
    table = {
        deployment.usd.address: "USD",
        deployment.col.address: "COL",
        deployment.amm.address: "AMM",
        deployment.lending.address: "LENDING",
    }
    return table.get(address, address)


def candidate_to_dict(
    candidate: Candidate,
    deployment: Deployment,
    evaluation: Evaluation,
    gas_used: int,
    seed: int,
    candidates_to_discovery: Optional[int],
) -> dict:
    """SPEC Appendix attack.json shape."""
    return {
        "flashToken": symbol_for(candidate.flash_token, deployment),
        "flashAmount": str(candidate.flash_amount),
        "actions": [
            {
                "type": a.action_type.name,
                "target": symbol_for(a.target, deployment),
                "rule": a.amount_rule.name,
                "param": a.amount_param,
            }
            for a in candidate.actions
        ],
        "result": {
            "attackerProfitUsd": str(evaluation.attacker_profit_usd),
            "protocolBadDebtUsd": str(evaluation.protocol_bad_debt_usd),
            "violatedProperty": evaluation.violated_property,
            "gasUsed": gas_used,
            "candidatesToDiscovery": candidates_to_discovery,
            "seed": seed,
        },
    }


@dataclass(frozen=True)
class TraceRecord:
    index: int
    action_type: ActionType
    resolved_amount: int
    pre_state: EconState
    post_state: EconState

    def to_json(self) -> dict:
        return {
            "index": self.index,
            "actionType": self.action_type.name,
            "resolvedAmount": str(self.resolved_amount),
            "preState": self.pre_state.to_json(),
            "postState": self.post_state.to_json(),
        }


def build_execution_trace(
    deployment: Deployment, tx_hash: str, pre_state: EconState, reference_price: int
) -> list[TraceRecord]:
    """Decode AttackExecutor's `ActionExecuted` events (emitted once per
    action inside the single atomic executeAttack tx) and reconstruct
    per-action pre/post EconState — index i's preState is index i-1's
    postState, or the pre-tx baseline for i=0. This is the only way to see
    intra-transaction state from Python; the tx itself is atomic."""
    receipt = deployment.w3.eth.get_transaction_receipt(tx_hash)
    # errors=IGNORE: the receipt also carries MockToken Transfer/Approval
    # logs from internal calls — decoding only ActionExecuted is expected to
    # skip those silently, not warn about every one.
    events = deployment.executor.events.ActionExecuted().process_receipt(receipt, errors=DISCARD)

    records: list[TraceRecord] = []
    running_pre = pre_state
    for ev in sorted(events, key=lambda e: e["args"]["index"]):
        args = ev["args"]
        post_state = EconState(
            attacker_usd=args["attackerUsd"],
            attacker_col=args["attackerCol"],
            reserve_usd=args["reserveUsd"],
            reserve_col=args["reserveCol"],
            oracle_price=args["oraclePrice"],
            reference_price=reference_price,
            debt_usd=args["debtUsd"],
            collateral_col=args["collateralCol"],
        )
        records.append(
            TraceRecord(
                index=args["index"],
                action_type=ActionType(args["actionType"]),
                resolved_amount=args["resolvedAmount"],
                pre_state=running_pre,
                post_state=post_state,
            )
        )
        running_pre = post_state
    return records


def _fmt(wei: int) -> str:
    """1e18-scaled integer -> a legible decimal string."""
    return f"{wei / 10**18:,.4f}"


_env = Environment(trim_blocks=True, lstrip_blocks=True)
_env.filters["fmt"] = _fmt

_REPORT_TEMPLATE = _env.from_string(
    """\
# Exploit Report

**Seed:** {{ seed }}
**Violated property:** `{{ evaluation.violated_property }}`

## Scenario

| Parameter | Value |
|---|---|
| AMM reserves (USD / COL) | {{ scenario.amm.reserve_usd | fmt }} / {{ scenario.amm.reserve_col | fmt }} |
| AMM fee | {{ scenario.amm.fee_bps }} bps |
| Lending USD liquidity | {{ scenario.lending.usd_liquidity | fmt }} |
| Collateral factor | {{ scenario.lending.collateral_factor_bps }} bps |
| Flash-loan fee | {{ scenario.flash.fee_bps }} bps |
| Attacker initial capital | {{ scenario.attacker.initial_capital_usd | fmt }} |
| Reference price (USD per COL) | {{ scenario.evaluator.reference_price_usd | fmt }} |

## Minimized Attack

Flash-borrow **{{ flash_token_symbol }}** {{ candidate.flash_amount | fmt }}, then:

{% for r in trace %}
{{ loop.index }}. `{{ r.action_type.name }}` — resolved amount **{{ r.resolved_amount | fmt }}**
   - oracle price: {{ r.pre_state.oracle_price | fmt }} → {{ r.post_state.oracle_price | fmt }}
   - reserves (USD/COL): {{ r.pre_state.reserve_usd | fmt }}/{{ r.pre_state.reserve_col | fmt }} → {{ r.post_state.reserve_usd | fmt }}/{{ r.post_state.reserve_col | fmt }}
   - debt: {{ r.pre_state.debt_usd | fmt }} → {{ r.post_state.debt_usd | fmt }}
   - collateral: {{ r.pre_state.collateral_col | fmt }} → {{ r.post_state.collateral_col | fmt }}
{% endfor %}
Then repay the flash loan (principal + fee).

## Result

| Metric | Value |
|---|---|
| Attacker profit (USD, at reference price) | {{ evaluation.attacker_profit_usd | fmt }} |
| Protocol bad debt (USD, at reference price) | {{ evaluation.protocol_bad_debt_usd | fmt }} |
| Gas used | {{ gas_used }} |

## Reproduce

Solidity (self-contained, re-proves the finding from scratch):

```
forge test --match-path test/generated/ExploitReproducer_{{ seed }}.t.sol -vv
```

Python bridge (exact replay of this run):

```
python -m engine.cli scenarios/vulnerable.json --seed {{ seed }} --strategy {{ strategy }}
```
"""
)


def render_report_md(
    candidate: Candidate,
    deployment: Deployment,
    evaluation: Evaluation,
    trace: list[TraceRecord],
    scenario: Scenario,
    seed: int,
    gas_used: int,
    strategy: str = "random",
) -> str:
    """SPEC §9 report.md: scenario params, minimized actions + resolved
    amounts, before/after state per action, profit/bad-debt, violated
    property, reproduction instructions."""
    return _REPORT_TEMPLATE.render(
        seed=seed,
        evaluation=evaluation,
        scenario=scenario,
        candidate=candidate,
        flash_token_symbol=symbol_for(candidate.flash_token, deployment),
        trace=trace,
        gas_used=gas_used,
        strategy=strategy,
    )
