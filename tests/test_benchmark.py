"""Pipeline-mechanics test with a tiny budget/N — confirms the sweep wires
together and writes valid outputs. NOT the real benchmark; see
experiments/benchmark_results.md for that (produced by a real --fast run,
documented in tasks/plan.md's Phase 6 status)."""

import csv
from pathlib import Path

import pytest

from engine.scenario import Scenario
from experiments.benchmark import CONFIGS, render_markdown_table, run_benchmark, write_summary_csv

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"


def test_configs_produce_distinct_scenarios():
    base = Scenario.load(SCENARIO_PATH)
    baseline = CONFIGS["baseline"](base)
    patched = CONFIGS["patched_low_collateral_factor"](base)

    assert baseline.lending.collateral_factor_bps == base.lending.collateral_factor_bps
    assert patched.lending.collateral_factor_bps == 3000
    assert patched.lending.collateral_factor_bps != base.lending.collateral_factor_bps
    # Deep copy: mutating a variant never touches the original.
    assert base.lending.collateral_factor_bps != 3000


@pytest.mark.discovery  # spins up a live Anvil per config; keep out of the fast default suite
def test_run_benchmark_produces_a_summary_row_per_config_per_strategy(tmp_path):
    all_results, summaries = run_benchmark(
        SCENARIO_PATH, n_seeds=1, budget=15, base_seed=0, minimize_after=False
    )

    assert len(summaries) == len(CONFIGS) * 2  # 2 strategies per config
    configs_seen = {s.config for s in summaries}
    assert configs_seen == set(CONFIGS.keys())

    table = render_markdown_table(summaries)
    assert "baseline" in table
    assert "patched_low_collateral_factor" in table
    assert "Discovery rate" in table

    out_csv = tmp_path / "summary.csv"
    write_summary_csv(summaries, out_csv)
    with out_csv.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == len(CONFIGS) * 2
    assert set(rows[0].keys()) == {
        "config",
        "strategy",
        "n",
        "discovery_rate",
        "mean_candidates_to_first_exploit",
        "std_candidates_to_first_exploit",
        "mean_wall_clock_s",
        "mean_minimized_length",
    }
