"""Regression tests for the deterministic Phase 7 evaluation framework."""

import json

from evaluation.datasets import synthetic_scenarios
from evaluation.red_team import run_red_team
from evaluation.runner import run_evaluation


def test_synthetic_dataset_has_required_deterministic_coverage() -> None:
    scenarios = synthetic_scenarios()
    categories = {scenario.category for scenario in scenarios}
    assert len(scenarios) >= 30
    assert {"chest_pain_breathlessness", "prescription_ocr", "poor_ocr", "agent_failure", "full_end_to_end"} <= categories


def test_evaluation_runner_measures_all_scenarios_without_network() -> None:
    result = run_evaluation()
    assert result["total_scenarios"] == 30
    assert result["passed"] == 30
    assert result["failed"] == 0
    assert result["metrics"]["risk_preservation_rate"] == 1.0
    assert result["metrics"]["hallucination_rate"] == 0.0


def test_red_team_checks_all_required_attacks() -> None:
    result = run_red_team()
    assert result["total_attacks"] == 10
    assert result["passed"] == 10
    assert result["failed"] == 0


def test_evaluation_report_generation_is_machine_readable(tmp_path, monkeypatch) -> None:
    import evaluation.runner as runner

    monkeypatch.setattr(runner, "RESULTS_DIR", tmp_path)
    result = runner.run_evaluation(write_reports=True)
    saved = json.loads((tmp_path / "latest.json").read_text(encoding="utf-8"))
    report = (tmp_path / "latest_report.md").read_text(encoding="utf-8")
    assert saved["metrics"] == result["metrics"]
    assert "# AI Evaluation Report" in report
