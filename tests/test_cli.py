from pathlib import Path

from typer.testing import CliRunner

from engine.cli import app

REPO_ROOT = Path(__file__).resolve().parent.parent
SCENARIO_PATH = REPO_ROOT / "scenarios" / "vulnerable.json"

runner = CliRunner()


def test_help_works():
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == 0
    assert "scenario_path" in result.output


def test_smoke_run_against_vulnerable_scenario(tmp_path):
    result = runner.invoke(
        app,
        [str(SCENARIO_PATH), "--budget", "10", "--results-dir", str(tmp_path)],
    )
    assert result.exit_code == 0, result.output
    assert "Evaluated 10 candidates" in result.output


def test_unsupported_strategy_rejected():
    result = runner.invoke(app, [str(SCENARIO_PATH), "--strategy", "guided", "--budget", "1"])
    assert result.exit_code != 0
