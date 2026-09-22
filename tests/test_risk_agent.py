"""Safety/Risk Agent tests using faked structured LLM responses only."""

from __future__ import annotations

from typing import Any, Optional

import pytest
from pydantic import BaseModel

from agents.risk_agent import RiskAgent
from agents.structuring_agent import StructuringAgent
from core.exceptions import StructuredOutputError
from core.schemas import AttentionLevel, ClinicalHistory, HistoryOfPresentIllness


class ScriptedLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_json(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        self.calls.append({"prompt": prompt, "schema": schema})
        if not self.responses:
            raise AssertionError("No fake response remains.")
        return self.responses.pop(0)


def history(**values: Any) -> ClinicalHistory:
    return ClinicalHistory(**values)


def test_chest_pain_and_breathlessness_is_urgent_with_evidence() -> None:
    result = RiskAgent(ScriptedLLM([{}])).assess(history(
        chief_complaint="chest pain",
        associated_symptoms=["breathlessness"],
        unknown_information=["duration", "severity", "allergies", "medications"],
    ))
    assert result.overall_attention_level is AttentionLevel.URGENT
    assert result.risk_flags[0].evidence
    assert result.risk_flags[0].requires_clinician_review is True
    assert result.diagnosis is None


def test_mild_headache_has_no_unsupported_emergency_diagnosis() -> None:
    result = RiskAgent(ScriptedLLM([{}])).assess(history(chief_complaint="mild headache"))
    assert result.risk_flags == []
    assert result.overall_attention_level is AttentionLevel.ROUTINE
    assert result.diagnosis is None


def test_severe_breathing_difficulty_is_urgent() -> None:
    result = RiskAgent(ScriptedLLM([{}])).assess(history(
        chief_complaint="severe difficulty breathing",
    ))
    assert result.overall_attention_level is AttentionLevel.URGENT
    assert result.risk_flags[0].evidence
    assert result.diagnosis is None


def test_loss_of_consciousness_is_urgent() -> None:
    result = RiskAgent(ScriptedLLM([{}])).assess(history(
        chief_complaint="I passed out",
    ))
    assert result.overall_attention_level is AttentionLevel.URGENT
    assert result.diagnosis is None


def test_patient_self_diagnosis_remains_uncertainty() -> None:
    concern = "Patient reports believing they may have a heart attack."
    result = RiskAgent(ScriptedLLM([{}])).assess(history(
        patient_reported_concerns=[concern],
    ))
    assert concern in result.uncertainties
    assert result.diagnosis is None
    assert result.risk_flags == []


def test_missing_allergy_information_is_not_a_negative_allergy() -> None:
    result = RiskAgent(ScriptedLLM([{}])).assess(history(
        chief_complaint="chest pain",
        unknown_information=["allergies", "medications", "duration", "severity"],
    ))
    assert "allergies" in result.missing_information
    assert result.diagnosis is None


def test_medication_contradiction_is_preserved() -> None:
    contradiction = "Medication history contains conflicting statements."
    result = RiskAgent(ScriptedLLM([{}])).assess(history(
        chief_complaint="headache",
        contradictions=[contradiction],
    ))
    assert result.contradictions == [contradiction]


def test_no_hallucinated_patient_data() -> None:
    result = RiskAgent(ScriptedLLM([{}])).assess(history(chief_complaint="headache"))
    assert result.risk_flags == []
    assert not hasattr(result, "age")
    assert not hasattr(result, "vital_signs")
    assert not hasattr(result, "laboratory_results")
    assert result.diagnosis is None


def test_empty_structured_history_is_graceful_without_llm_call() -> None:
    llm = ScriptedLLM([])
    result = RiskAgent(llm).assess(history())
    assert result.overall_attention_level is AttentionLevel.ROUTINE
    assert "chief_complaint" in result.missing_information
    assert not llm.calls


def test_malformed_llm_output_fails_safely_after_one_repair() -> None:
    llm = ScriptedLLM(["{not json", "still not json"])
    with pytest.raises(StructuredOutputError):
        RiskAgent(llm).assess(history(chief_complaint="headache"))
    assert len(llm.calls) == 2


def test_flag_without_evidence_is_rejected() -> None:
    llm = ScriptedLLM([{
        "risk_flags": [{"category": "safety_symptom", "description": "Review reported headache."}],
    }])
    with pytest.raises(StructuredOutputError, match="safely validated"):
        RiskAgent(llm).assess(history(chief_complaint="headache"))


def test_forbidden_diagnosis_is_neutralized() -> None:
    result = RiskAgent(ScriptedLLM([{"diagnosis": "heart attack"}])).assess(
        history(chief_complaint="headache")
    )
    assert result.diagnosis is None


def test_forbidden_medication_advice_is_rejected() -> None:
    llm = ScriptedLLM([{
        "risk_flags": [{
            "category": "safety_symptom",
            "description": "Stop taking metformin.",
            "severity": "moderate",
            "evidence": "headache",
        }],
    }])
    with pytest.raises(StructuredOutputError, match="safely validated"):
        RiskAgent(llm).assess(history(chief_complaint="headache", medications=[{"name_as_reported": "metformin"}]))


def test_unsupported_risk_flag_is_rejected() -> None:
    llm = ScriptedLLM([{
        "risk_flags": [{
            "category": "urgent_symptom",
            "description": "Reported fever needs review.",
            "severity": "high",
            "evidence": "fever",
        }],
    }])
    with pytest.raises(StructuredOutputError, match="safely validated"):
        RiskAgent(llm).assess(history(chief_complaint="headache"))


def test_normal_low_risk_synthetic_case_stays_routine() -> None:
    result = RiskAgent(ScriptedLLM([{}])).assess(history(
        chief_complaint="mild headache",
        history_of_present_illness=HistoryOfPresentIllness(duration="one hour", severity=2),
    ))
    assert result.overall_attention_level is AttentionLevel.ROUTINE
    assert not result.risk_flags


def test_deterministic_urgent_rule_overrides_routine_llm_response() -> None:
    result = RiskAgent(ScriptedLLM([{"overall_attention_level": "routine"}])).assess(history(
        chief_complaint="chest pain",
        associated_symptoms=["breathlessness"],
    ))
    assert result.overall_attention_level is AttentionLevel.URGENT
    assert any(flag.category == "urgent_symptom" for flag in result.risk_flags)


def test_phase_two_clinical_history_flows_directly_into_risk_assessment() -> None:
    structured = StructuringAgent(ScriptedLLM([{
        "chief_complaint": "chest pain",
        "associated_symptoms": ["breathlessness"],
        "source_evidence": {
            "chief_complaint": "I have chest pain.",
            "associated_symptoms": "I also have breathlessness.",
        },
    }])).structure(
        "Patient: I have chest pain.\nPatient: I also have breathlessness."
    )
    assessment = RiskAgent(ScriptedLLM([{}])).assess(structured)
    assert assessment.overall_attention_level is AttentionLevel.URGENT
    assert assessment.diagnosis is None
