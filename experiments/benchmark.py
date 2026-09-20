"""Full SPEC §12 benchmark methodology: guided vs random search under
IDENTICAL budgets/action-space/execution-path, over N>=20 seeds, across a
parameter sweep (AMM liquidity depth, collateral factor, flash fee, initial
capital) plus a patched control. Reports mean±std candidates-to-first-
exploit (primary metric), discovery rate, wall-clock, and mean minimized
length — per config, per strategy — as markdown + CSV in experiments/.

The patched control uses a conservative collateral factor (TWAPOracle, the
other option SPEC §12 names, is Task 32/stretch and not built). Confirms the
engine is finding a *real* vulnerability class, not an artifact: exploit
rate should drop sharply once collateral is conservative enough that even a
~2x price manipulation can't produce bad debt.

--fast mode (default here, opt out with --no-fast) drastically reduces N and
budget so the pipeline is verifiable within a single session — this machine
is shared/memory-constrained (see tasks/plan.md's Phase 5 status) and the
full run can genuinely take hours, which SPEC §12 wants (rigor over speed).
The full N>=20, scenario-default-budget run is a documented manual step:

    python -m experiments.benchmark --no-fast
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Optional

import typer

from engine.scenario import Scenario
from experiments.random_vs_guided import TrialResult, run_head_to_head_scenario, write_csv

REPO_ROOT = Path(__file__).resolve().parent.parent
DEFAULT_SCENARIO = REPO_ROOT / "scenarios" / "vulnerable.json"

app = typer.Typer(help="Full guided-vs-random benchmark, SPEC §12.")


def _low_liquidity(base: Scenario) -> Scenario:
    v = base.model_copy(deep=True)
    v.amm.reserve_usd //= 2
    v.amm.reserve_col //= 2
    return v


def _high_flash_fee(base: Scenario) -> Scenario:
    v = base.model_copy(deep=True)
    v.flash.fee_bps = 50
    return v


def _low_capital(base: Scenario) -> Scenario:
    v = base.model_copy(deep=True)
    v.attacker.initial_capital_usd //= 10
    return v


def _patched_conservative_collateral_factor(base: Scenario) -> Scenario:
    """SPEC §12 patched control."""
    v = base.model_copy(deep=True)
    v.lending.collateral_factor_bps = 3000
    return v


# Name -> transform applied to the baseline scenario. "baseline" is the
# identity transform (deep copy, no change) so it always appears first.
CONFIGS: dict[str, Callable[[Scenario], Scenario]] = {
    "baseline": lambda base: base.model_copy(deep=True),
    "low_liquidity": _low_liquidity,
    "high_flash_fee": _high_flash_fee,
    "low_capital": _low_capital,
    "patched_low_collateral_factor": _patched_conservative_collateral_factor,
}


@dataclass
class ConfigSummary:
    config: str
    strategy: str
    n: int
    discovery_rate: float
    mean_candidates: float
    std_candidates: float
    mean_wall_clock_s: float
    mean_minimized_length: Optional[float]


def _summarize_config(config: str, strategy: str, results: list[TrialResult]) -> ConfigSummary:
    trials = [r for r in results if r.strategy == strategy]
    discovered = [r for r in trials if r.discovered]
    rate = len(discovered) / len(trials) if trials else 0.0

    if discovered:
        vals = [r.candidates_to_first_exploit for r in discovered]
        mean_c = sum(vals) / len(vals)
        std_c = (sum((v - mean_c) ** 2 for v in vals) / len(vals)) ** 0.5
        mean_wc = sum(r.wall_clock_s for r in discovered) / len(discovered)
        lengths = [r.minimized_length for r in discovered if r.minimized_length is not None]
        mean_len = sum(lengths) / len(lengths) if lengths else None
    else:
        mean_c = std_c = mean_wc = float("nan")
        mean_len = None

    return ConfigSummary(config, strategy, len(trials), rate, mean_c, std_c, mean_wc, mean_len)


def run_benchmark(
    scenario_path: Path,
    n_seeds: int,
    budget: int,
    base_seed: int = 0,
    minimize_after: bool = True,
    out_dir: Optional[Path] = None,
) -> tuple[list[TrialResult], list[ConfigSummary]]:
    base = Scenario.load(scenario_path)
    all_results: list[TrialResult] = []
    summaries: list[ConfigSummary] = []

    failed_configs: list[str] = []
    for config_name, transform in CONFIGS.items():
        t0 = time.monotonic()
        scenario = transform(base)

        # One retry (fresh Anvil + redeploy, since run_head_to_head_scenario
        # opens its own) before giving up on a config: a multi-hour sweep
        # hit a real node hang after ~10 hours of sustained snapshot/revert
        # load (bridge.py's wait_for_transaction_receipt timeout) with
        # nothing checkpointed since — an uncaught exception here loses
        # every config after it too, not just the one that hit trouble.
        results = None
        for attempt in (1, 2):
            try:
                results = run_head_to_head_scenario(
                    scenario, n_seeds, budget, base_seed, minimize_after=minimize_after
                )
                break
            except Exception as exc:
                typer.echo(f"[{config_name}] attempt {attempt} failed: {exc!r}")

        if results is None:
            typer.echo(f"[{config_name}] failed twice, skipping — see above for the exception")
            failed_configs.append(config_name)
            continue

        all_results.extend(results)
        for strategy in ("random", "guided"):
            summaries.append(_summarize_config(config_name, strategy, results))

        typer.echo(
            f"[{config_name}] done in {(time.monotonic() - t0) / 60:.1f} min, "
            f"{sum(r.discovered for r in results)}/{len(results)} trials discovered"
        )
        # Checkpoint after every config: this machine has a documented OOM
        # history (tasks/plan.md, Phase 5 status) — a killed run loses at
        # most the in-progress config's trials, never the whole sweep.
        if out_dir is not None:
            _write_outputs(all_results, summaries, out_dir)

    if failed_configs:
        typer.echo(f"WARNING: these configs failed twice and are missing from the table: {failed_configs}")

    return all_results, summaries


def _write_outputs(all_results: list[TrialResult], summaries: list[ConfigSummary], out_dir: Path) -> None:
    table = render_markdown_table(summaries)
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "benchmark_results.md").write_text("# Benchmark Results (SPEC §12)\n\n" + table + "\n")
    write_csv(all_results, out_dir / "benchmark_raw.csv")
    write_summary_csv(summaries, out_dir / "benchmark_summary.csv")


def render_markdown_table(summaries: list[ConfigSummary]) -> str:
    lines = [
        "| Config | Strategy | N | Discovery rate | Candidates-to-first-exploit (mean±std) | "
        "Wall-clock s (mean) | Minimized length (mean) |",
        "|---|---|---|---|---|---|---|",
    ]
    for s in summaries:
        length = f"{s.mean_minimized_length:.1f}" if s.mean_minimized_length is not None else "—"
        lines.append(
            f"| {s.config} | {s.strategy} | {s.n} | {s.discovery_rate:.2f} | "
            f"{s.mean_candidates:.1f}±{s.std_candidates:.1f} | {s.mean_wall_clock_s:.1f} | {length} |"
        )
    return "\n".join(lines)


def write_summary_csv(summaries: list[ConfigSummary], out_path: Path) -> None:
    import csv

    out_path.parent.mkdir(parents=True, exist_ok=True)
    with out_path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(
            [
                "config",
                "strategy",
                "n",
                "discovery_rate",
                "mean_candidates_to_first_exploit",
                "std_candidates_to_first_exploit",
                "mean_wall_clock_s",
                "mean_minimized_length",
            ]
        )
        for s in summaries:
            writer.writerow(
                [
                    s.config,
                    s.strategy,
                    s.n,
                    f"{s.discovery_rate:.4f}",
                    f"{s.mean_candidates:.2f}",
                    f"{s.std_candidates:.2f}",
                    f"{s.mean_wall_clock_s:.2f}",
                    f"{s.mean_minimized_length:.2f}" if s.mean_minimized_length is not None else "",
                ]
            )


@app.command()
def main(
    scenario_path: Path = typer.Option(DEFAULT_SCENARIO, help="Base scenario to sweep from"),
    fast: bool = typer.Option(True, help="Reduced N/budget, verifiable in one session (see module docstring)"),
    n_seeds: Optional[int] = typer.Option(None, help="Override the seed count per config/strategy"),
    budget: Optional[int] = typer.Option(None, help="Override the candidate budget per trial"),
    base_seed: int = typer.Option(0, help="First seed; seeds base_seed..base_seed+n_seeds-1"),
    minimize: bool = typer.Option(True, help="Minimize each found exploit for the length metric (slower)"),
    out_dir: Path = typer.Option(REPO_ROOT / "experiments"),
) -> None:
    if n_seeds is None:
        n_seeds = 3 if fast else 20
    if budget is None:
        budget = 300 if fast else Scenario.load(scenario_path).search.budget_candidates

    typer.echo(f"Benchmarking {len(CONFIGS)} configs x 2 strategies x {n_seeds} seeds, budget={budget}...")
    all_results, summaries = run_benchmark(
        scenario_path, n_seeds, budget, base_seed, minimize_after=minimize, out_dir=out_dir
    )

    typer.echo(render_markdown_table(summaries))
    typer.echo(f"wrote {out_dir / 'benchmark_results.md'}, benchmark_raw.csv, benchmark_summary.csv")


if __name__ == "__main__":
    app()
