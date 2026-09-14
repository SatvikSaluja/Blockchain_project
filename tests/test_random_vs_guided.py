"""Pipeline-mechanics test with a tiny budget — confirms the driver wires
together, writes a valid CSV, and summarizes correctly. NOT a claim that
guided beats random at this budget (too small for that to be meaningful);
see experiments/random_vs_guided_results.csv for the real Phase 5 evidence
and tests/test_discovery.py for the real per-strategy discovery check.
"""

import csv
from pathlib import Path

import pytest

from experiments.random_vs_guided import run_head_to_head, summarize, write_csv

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"


@pytest.mark.discovery  # spins up a live Anvil; keep out of the fast default suite
def test_head_to_head_produces_a_row_per_strategy_per_seed(tmp_path):
    results = run_head_to_head(SCENARIO_PATH, n_seeds=2, budget=20, base_seed=0)

    assert len(results) == 4  # 2 seeds x 2 strategies
    strategies = {r.strategy for r in results}
    assert strategies == {"random", "guided"}
    seeds_per_strategy = {r.seed for r in results if r.strategy == "random"}
    assert seeds_per_strategy == {0, 1}

    out_csv = tmp_path / "results.csv"
    write_csv(results, out_csv)
    with out_csv.open() as f:
        rows = list(csv.DictReader(f))
    assert len(rows) == 4
    assert set(rows[0].keys()) == {
        "strategy",
        "seed",
        "candidates_to_first_exploit",
        "discovered",
        "wall_clock_s",
        "exploit_count",
    }

    summary = summarize(results)
    assert "random" in summary
    assert "guided" in summary
    assert "discovery_rate" in summary
