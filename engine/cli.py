"""CLI entry point (SPEC §1: typer/argparse; a dashboard is explicitly out
of scope for v1). `run` wires scenario -> deploy -> search -> minimize ->
write the full SPEC §9 result set to results/run_XXX/.
"""

from __future__ import annotations

import json
import random
from pathlib import Path
from typing import Optional

import typer
from web3 import Web3

from engine.deploy import AnvilProcess, deploy_scenario
from engine.bridge import ExecutionBridge
from engine.evaluator import Evaluator
from engine.minimizer import minimize
from engine.observer import Observer
from engine.report import build_execution_trace, candidate_to_dict, render_report_md
from engine.scenario import Scenario
from engine.search.fitness import WeightedFitness
from engine.search.guided_search import run_guided_search
from engine.search.mutations import ActionSpace
from engine.search.novelty import NoveltyTracker
from engine.search.random_search import run_random_search
from engine.solgen import generate_reproducer_sol

app = typer.Typer(help="DeFi economic exploit discovery engine (SPEC.md).")
REPO_ROOT = Path(__file__).resolve().parent.parent


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
    """Deploy `scenario_path` once, search for a qualifying exploit, minimize
    each finding, and write scenario.json/attack.json/execution_trace.json/
    report.md/ExploitReproducer.t.sol to results/run_XXX/ (SPEC §9)."""
    scenario = Scenario.load(scenario_path)
    run_seed = seed if seed is not None else scenario.seed
    run_budget = budget if budget is not None else scenario.search.budget_candidates
    rng = random.Random(run_seed)

    if strategy not in ("random", "guided"):
        raise typer.BadParameter(f"strategy={strategy!r} must be 'random' or 'guided'")

    with AnvilProcess() as anvil:
        w3 = Web3(Web3.HTTPProvider(anvil.rpc_url))
        deployment = deploy_scenario(w3, scenario)
        bridge = ExecutionBridge(deployment)
        observer = Observer(deployment, scenario.evaluator.reference_price_usd)
        space = ActionSpace(
            usd=deployment.usd.address,
            col=deployment.col.address,
            amm=deployment.amm.address,
            lending=deployment.lending.address,
        )

        if strategy == "random":
            evaluator = Evaluator(scenario)
            result = run_random_search(
                bridge, evaluator, observer, space, rng, run_budget, stop_on_first=stop_on_first
            )
        else:
            fitness_fn = WeightedFitness(scenario, space, NoveltyTracker(observer.read()))
            evaluator = Evaluator(scenario, fitness_fn=fitness_fn)
            result = run_guided_search(
                bridge, evaluator, observer, space, rng, run_budget, stop_on_first=stop_on_first
            )

        typer.echo(f"Evaluated {result.candidates_evaluated} candidates, found {len(result.exploits)} exploit(s).")
        for candidate, _evaluation, _exec_result in result.exploits:
            typer.echo("  minimizing...")
            minimized = minimize(bridge, evaluator, observer, candidate)

            # Re-execute the minimized candidate once more to capture its own
            # tx/trace/gas for the report (minimize() always restores after
            # each internal check, so nothing from it is left observable).
            pre_state = observer.read()
            final_result = bridge.execute(minimized)
            post_state = observer.read()
            final_eval = evaluator.evaluate(minimized, final_result, post_state)
            assert final_eval.is_exploit, "minimized candidate stopped qualifying — minimizer bug"

            # Build the trace BEFORE restoring: bridge.restore() reverts the
            # chain, and the just-mined tx is no longer findable afterward.
            trace = build_execution_trace(
                deployment, final_result.tx_hash, pre_state, scenario.evaluator.reference_price_usd
            )
            bridge.restore()

            run_dir = _next_run_dir(results_dir)
            attack_payload = candidate_to_dict(
                minimized,
                deployment,
                final_eval,
                gas_used=final_result.gas_used,
                seed=run_seed,
                candidates_to_discovery=result.candidates_to_first_exploit,
            )
            (run_dir / "attack.json").write_text(json.dumps(attack_payload, indent=2))
            (run_dir / "scenario.json").write_text(scenario_path.read_text())
            (run_dir / "execution_trace.json").write_text(json.dumps([r.to_json() for r in trace], indent=2))
            report_md = render_report_md(
                minimized, deployment, final_eval, trace, scenario, run_seed, final_result.gas_used, strategy
            )
            (run_dir / "report.md").write_text(report_md)

            sol_source = generate_reproducer_sol(minimized, deployment, run_seed)
            (run_dir / "ExploitReproducer.t.sol").write_text(sol_source)
            # Also drop a copy into test/generated/ so it joins the live
            # forge test suite (SPEC §10), not just this run's archive.
            generated_path = REPO_ROOT / "test" / "generated" / f"ExploitReproducer_{run_seed}.t.sol"
            generated_path.parent.mkdir(parents=True, exist_ok=True)
            generated_path.write_text(sol_source)

            typer.echo(f"  wrote {run_dir} (+ {generated_path})")


if __name__ == "__main__":
    app()
