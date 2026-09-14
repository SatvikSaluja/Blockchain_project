"""CLI entry point (SPEC §1: typer/argparse; a dashboard is explicitly out
of scope for v1). `run` wires scenario -> deploy -> search -> on-exploit
save. The result writer here is intentionally minimal (attack.json +
scenario.json) — Phase 6 (Tasks 28-30) adds report.md, execution_trace.json,
and the generated ExploitReproducer.t.sol on top of the same shape.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

import typer
from web3 import Web3

from engine.actions import Candidate
from engine.deploy import AnvilProcess, Deployment, deploy_scenario
from engine.bridge import ExecutionBridge
from engine.evaluator import Evaluation, Evaluator
from engine.observer import Observer
from engine.scenario import Scenario
from engine.search.mutations import ActionSpace
from engine.search.random_search import run_random_search

app = typer.Typer(help="DeFi economic exploit discovery engine (SPEC.md).")
REPO_ROOT = Path(__file__).resolve().parent.parent


def _symbol(address: str, deployment: Deployment) -> str:
    """Human-readable label for an address in attack.json, matching the
    SPEC Appendix example ("USD", "AMM", ...) instead of raw hex."""
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
        "flashToken": _symbol(candidate.flash_token, deployment),
        "flashAmount": str(candidate.flash_amount),
        "actions": [
            {
                "type": a.action_type.name,
                "target": _symbol(a.target, deployment),
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


def _next_run_dir(results_dir: Path) -> Path:
    results_dir.mkdir(parents=True, exist_ok=True)
    existing = [p for p in results_dir.glob("run_*") if p.is_dir()]
    run_dir = results_dir / f"run_{len(existing) + 1:03d}"
    run_dir.mkdir()
    return run_dir


@app.command()
def run(
    scenario_path: Path = typer.Argument(..., help="Path to a scenario.json"),
    strategy: str = typer.Option("random", help="'random' (Phase 4) or 'guided' (Phase 5)"),
    seed: Optional[int] = typer.Option(None, help="Override scenario.seed"),
    budget: Optional[int] = typer.Option(None, help="Override scenario.search.budgetCandidates"),
    results_dir: Path = typer.Option(REPO_ROOT / "results", help="Where to write results/run_XXX/"),
    stop_on_first: bool = typer.Option(False, help="Stop searching at the first qualifying exploit"),
) -> None:
    """Deploy `scenario_path` once, search for a qualifying exploit, and
    write each finding to results/run_XXX/."""
    scenario = Scenario.load(scenario_path)
    run_seed = seed if seed is not None else scenario.seed
    run_budget = budget if budget is not None else scenario.search.budget_candidates
    rng = random.Random(run_seed)

    if strategy != "random":
        raise typer.BadParameter(f"strategy={strategy!r} not implemented yet (Phase 5 adds 'guided')")

    with AnvilProcess() as anvil:
        w3 = Web3(Web3.HTTPProvider(anvil.rpc_url))
        deployment = deploy_scenario(w3, scenario)
        bridge = ExecutionBridge(deployment)
        observer = Observer(deployment, scenario.evaluator.reference_price_usd)
        evaluator = Evaluator(scenario)
        space = ActionSpace(
            usd=deployment.usd.address,
            col=deployment.col.address,
            amm=deployment.amm.address,
            lending=deployment.lending.address,
        )

        result = run_random_search(bridge, evaluator, observer, space, rng, run_budget, stop_on_first=stop_on_first)

        typer.echo(f"Evaluated {result.candidates_evaluated} candidates, found {len(result.exploits)} exploit(s).")
        for candidate, evaluation, exec_result in result.exploits:
            run_dir = _next_run_dir(results_dir)
            payload = candidate_to_dict(
                candidate,
                deployment,
                evaluation,
                gas_used=exec_result.gas_used,
                seed=run_seed,
                candidates_to_discovery=result.candidates_to_first_exploit,
            )
            (run_dir / "attack.json").write_text(json.dumps(payload, indent=2))
            (run_dir / "scenario.json").write_text(scenario_path.read_text())
            typer.echo(f"  wrote {run_dir}")


if __name__ == "__main__":
    app()
