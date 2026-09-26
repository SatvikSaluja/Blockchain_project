"""Phase 5 head-to-head driver (SPEC §6.3 / §11 Phase 5 done-when): guided
vs random search under IDENTICAL budgets, action space, and execution path,
across N seeds — "guided beats random on discovery rate / candidates-to-
first-exploit with variance reported."

The full N>=20-seed methodology (parameter sweep, patched controls,
minimized length) is Phase 6's experiments/benchmark.py (Task 31); this is
the narrower guided-vs-random check Phase 5 itself asks for.
"""

from __future__ import annotations

import csv
import random
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import typer
from web3 import Web3

from engine.bridge import ExecutionBridge
from engine.deploy import AnvilProcess, deploy_scenario
from engine.evaluator import Evaluator
from engine.minimizer import minimize
from engine.observer import Observer
from engine.scenario import Scenario
from engine.search.fitness import WeightedFitness
from engine.search.guided_search import run_guided_search
from engine.search.mutations import ActionSpace
from engine.search.novelty import NoveltyTracker
from engine.search.random_search import run_random_search

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIO = REPO_ROOT / "scenarios" / "vulnerable.json"

app = typer.Typer(help="Guided vs random search head-to-head (SPEC §6.3 / §12 preview).")


@dataclass
class TrialResult:
    strategy: str
    seed: int
    candidates_to_first_exploit: Optional[int]
    discovered: bool
    wall_clock_s: float
    exploit_count: int
    minimized_length: Optional[int] = None  # SPEC §12 secondary metric; only set if minimize_after=True


def _run_trial(
    strategy: str,
    seed: int,
    bridge: ExecutionBridge,
    observer: Observer,
    space: ActionSpace,
    scenario: Scenario,
    budget: int,
    minimize_after: bool = False,
) -> TrialResult:
    rng = random.Random(seed)
    start = time.monotonic()

    # stop_on_first=True: the head-to-head metric is candidates-to-first-
    # exploit (SPEC §12 primary metric), so a trial can stop the moment it
    # has one — no need to keep searching for more within one trial here.
    if strategy == "random":
        evaluator = Evaluator(scenario)
        result = run_random_search(bridge, evaluator, observer, space, rng, budget, stop_on_first=True)
    elif strategy == "guided":
        # Fresh NoveltyTracker per trial — novelty is a within-run coverage
        # signal, not something that should leak across independent trials.
        fitness_fn = WeightedFitness(scenario, space, NoveltyTracker(observer.read()))
        evaluator = Evaluator(scenario, fitness_fn=fitness_fn)
        result = run_guided_search(bridge, evaluator, observer, space, rng, budget, stop_on_first=True)
    else:
        raise ValueError(f"unknown strategy {strategy!r}")

    elapsed = time.monotonic() - start

    minimized_length = None
    if minimize_after and result.exploits:
        candidate, _ev, _exec_result = result.exploits[0]
        minimized = minimize(bridge, evaluator, observer, candidate)
        minimized_length = len(minimized.actions)

    return TrialResult(
        strategy=strategy,
        seed=seed,
        candidates_to_first_exploit=result.candidates_to_first_exploit,
        discovered=result.candidates_to_first_exploit is not None,
        wall_clock_s=elapsed,
        exploit_count=len(result.exploits),
        minimized_length=minimized_length,
    )


def run_head_to_head_scenario(
    scenario: Scenario,
    n_seeds: int,
    budget: int,
    base_seed: int = 0,
    minimize_after: bool = False,
    port: int = 8545,
) -> list[TrialResult]:
    """One persistent Anvil + one deployment for the whole benchmark (SPEC
    §5) — every trial's ExecutionBridge.restore() call already guarantees a
    clean baseline before the next one, so redeploying per trial would just
    be the same wasted-work mistake §5 warns against, one level up. Takes a
    `Scenario` object directly so experiments/benchmark.py's parameter sweep
    (Task 31) can run variants without round-tripping through a temp file.
    `port` lets the caller run several configs concurrently, each on its own
    Anvil, without colliding (experiments/benchmark.py parallel mode)."""
    results: list[TrialResult] = []

    with AnvilProcess(port=port) as anvil:
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

        for i in range(n_seeds):
            seed = base_seed + i
            for strategy in ("random", "guided"):
                results.append(
                    _run_trial(strategy, seed, bridge, observer, space, scenario, budget, minimize_after)
                )

    return results


def run_head_to_head(scenario_path: Path, n_seeds: int, budget: int, base_seed: int = 0) -> list[TrialResult]:
    """Path-based convenience wrapper around run_head_to_head_scenario."""
    return run_head_to_head_scenario(Scenario.load(scenario_path), n_seeds, budget, base_seed)


def write_csv(results: list[TrialResult], out_path: Path) -> None:
    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "strategy",
                "seed",
                "candidates_to_first_exploit",
                "discovered",
                "wall_clock_s",
                "exploit_count",
                "minimized_length",
            ]
        )
        for r in results:
            writer.writerow(
                [
                    r.strategy,
                    r.seed,
                    r.candidates_to_first_exploit,
                    r.discovered,
                    f"{r.wall_clock_s:.3f}",
                    r.exploit_count,
                    r.minimized_length,
                ]
            )


def summarize(results: list[TrialResult]) -> str:
    lines = []
    for strategy in ("random", "guided"):
        trials = [r for r in results if r.strategy == strategy]
        discovered = [r for r in trials if r.discovered]
        rate = len(discovered) / len(trials) if trials else 0.0
        if discovered:
            vals = [r.candidates_to_first_exploit for r in discovered]
            mean = sum(vals) / len(vals)
            std = (sum((v - mean) ** 2 for v in vals) / len(vals)) ** 0.5
        else:
            mean = std = float("nan")
        lines.append(
            f"{strategy:8s} N={len(trials):3d} discovery_rate={rate:.2f} "
            f"candidates_to_first_exploit mean±std={mean:.1f}±{std:.1f}"
        )
    return "\n".join(lines)


@app.command()
def main(
    scenario_path: Path = typer.Option(DEFAULT_SCENARIO, help="Scenario to benchmark"),
    n_seeds: int = typer.Option(5, help="Number of seeds per strategy"),
    budget: int = typer.Option(500, help="Candidate budget per run"),
    base_seed: int = typer.Option(0, help="First seed; seeds base_seed..base_seed+n_seeds-1"),
    out_csv: Path = typer.Option(REPO_ROOT / "experiments" / "random_vs_guided_results.csv"),
) -> None:
    results = run_head_to_head(scenario_path, n_seeds, budget, base_seed)
    write_csv(results, out_csv)
    typer.echo(summarize(results))
    typer.echo(f"wrote {out_csv}")


if __name__ == "__main__":
    app()
