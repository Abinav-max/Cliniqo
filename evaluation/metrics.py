"""Small, transparent metric helpers used by deterministic evaluation runs."""

from __future__ import annotations

from dataclasses import dataclass, field


def ratio(numerator: int, denominator: int) -> float:
    return round(numerator / denominator, 4) if denominator else 1.0


@dataclass
class MetricAccumulator:
    extraction_correct: int = 0
    extraction_total: int = 0
    unsupported_claims: int = 0
    total_claims: int = 0
    safety_passed: int = 0
    safety_total: int = 0
    urgent_preserved: int = 0
    urgent_total: int = 0
    attributed: int = 0
    attribution_total: int = 0
    contradictions_preserved: int = 0
    contradiction_total: int = 0
    uncertainty_preserved: int = 0
    uncertainty_total: int = 0
    workflows_successful: int = 0
    workflows_total: int = 0

    def as_dict(self) -> dict[str, float]:
        return {
            "extraction_accuracy": ratio(self.extraction_correct, self.extraction_total),
            "hallucination_rate": ratio(self.unsupported_claims, self.total_claims),
            "safety_compliance": ratio(self.safety_passed, self.safety_total),
            "risk_preservation_rate": ratio(self.urgent_preserved, self.urgent_total),
            "source_attribution_accuracy": ratio(self.attributed, self.attribution_total),
            "contradiction_preservation": ratio(self.contradictions_preserved, self.contradiction_total),
            "uncertainty_preservation": ratio(self.uncertainty_preserved, self.uncertainty_total),
            "workflow_reliability": ratio(self.workflows_successful, self.workflows_total),
        }


@dataclass
class ScenarioResult:
    scenario_id: str
    category: str
    passed: bool
    duration_ms: float
    llm_calls: int
    failures: list[str] = field(default_factory=list)
