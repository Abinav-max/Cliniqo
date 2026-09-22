"""Physician Summary Agent tests with synthetic data and mocked LLMs only."""

from __future__ import annotations

from typing import Any, Optional

import pytest
from pydantic import BaseModel

from agents.document_agent import DocumentAgent
from agents.interview_agent import FieldUpdate, InformationStatus, InterviewAgent, InterviewLLMResponse
from agents.risk_agent import RiskAgent
from agents.structuring_agent import StructuringAgent
from agents.summary_agent import SummaryAgent, SummarySelection
from core.exceptions import StructuredOutputError
from core.schemas import (
    AttentionLevel,
    ClinicalHistory,
    DocumentExtraction,
    HistoryOfPresentIllness,
    PhysicianSummary,
    RiskAssessment,
    RiskFlag,
    RiskSeverity,
    SummaryInput,
    SummarySourceType,
)


class ScriptedLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, Any]] = []

    def generate_json(self, prompt: str, *, schema: type[BaseModel] | None = None,
                      system_instruction: Optional[str] = None,
                      temperature: Optional[float] = None) -> Any:
        self.calls.append({"prompt": prompt, "schema": schema})
        if not self.responses:
            raise AssertionError("No fake response remains.")
        return self.responses.pop(0)


def summary(history: ClinicalHistory | None = None, risk: RiskAssessment | None = None,
            documents: list[DocumentExtraction] | None = None, response: Any | None = None) -> PhysicianSummary:
    if response is None:
        response = {"overview": "Reported information."}
    return SummaryAgent(ScriptedLLM([response])).summarize(history, risk, documents or [])


def chest_history() -> ClinicalHistory:
    return ClinicalHistory(
        session_id="s-1",
        chief_complaint="chest pain",
        associated_symptoms=["breathlessness"],
        history_of_present_illness=HistoryOfPresentIllness(duration="2 days", location="center of chest", severity=7),
        source_evidence={"chief_complaint": "I have chest pain."},
    )


def metformin_document() -> DocumentExtraction:
    return DocumentExtraction.model_validate({
        "document_id": "rx-1",
        "medications": [{"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "frequency_as_reported": "once daily", "source_text": "Metformin 500 mg once daily"}],
    })


def test_basic_physician_summary() -> None:
    result = summary(chest_history(), response={"overview": "Reported chest pain."})
    assert result.overview == "Reported chest pain."
    assert any("Chief complaint: chest pain" in line for line in result.structured_history_highlights)
    assert result.for_clinician_review_only


def test_default_summary_model_contract_is_limited_to_fact_selection() -> None:
    llm = ScriptedLLM([{"overview": "Reported chest pain."}])
    SummaryAgent(llm).summarize(chest_history())
    assert llm.calls[0]["schema"] is SummarySelection


def test_summary_selection_renders_only_validated_fact_ids() -> None:
    result = SummaryAgent(ScriptedLLM([{"fact_ids": ["clinical_history.0"]}])).summarize(chest_history())
    assert result.overview == "Chief complaint: chest pain for 2 days."


def test_summary_selection_rejects_unknown_fact_id_after_one_repair() -> None:
    llm = ScriptedLLM([{"fact_ids": ["invented.fact"]}, {"fact_ids": ["invented.fact"]}])
    with pytest.raises(StructuredOutputError):
        SummaryAgent(llm).summarize(chest_history())
    assert len(llm.calls) == 2


def test_hpi_includes_reported_duration_location_severity_and_symptoms() -> None:
    result = summary(chest_history(), response={"overview": "Reported chest pain for 2 days."})
    text = " ".join(result.structured_history_highlights)
    assert all(value in text for value in ("2 days", "center of chest", "7/10", "breathlessness"))


def test_summary_preserves_reported_severity_descriptor_without_converting_to_score() -> None:
    history = ClinicalHistory(
        chief_complaint="chest pain",
        history_of_present_illness=HistoryOfPresentIllness(duration="2 hours", severity="severe"),
    )
    result = summary(history, response={"overview": "Reported severe chest pain for 2 hours."})
    assert "severity severe" in " ".join(result.structured_history_highlights)
    assert "severe/10" not in " ".join(result.structured_history_highlights)


def test_document_medication_has_document_attribution() -> None:
    result = summary(ClinicalHistory(chief_complaint="headache"), documents=[metformin_document()], response={"overview": "Reported headache."})
    assert any("document" in line.lower() and "Metformin 500 mg once daily" in line for line in result.document_derived_findings)


def test_document_lab_value_is_preserved() -> None:
    document = DocumentExtraction.model_validate({"lab_results": [{"test_name": "HbA1c", "value_as_reported": "8.2", "unit_as_reported": "%", "source_text": "HbA1c 8.2%"}]})
    result = summary(ClinicalHistory(chief_complaint="headache"), documents=[document], response={"overview": "Reported headache."})
    assert any("HbA1c of 8.2 %" in line for line in result.document_derived_findings)


def test_urgent_risk_flag_is_preserved() -> None:
    risk = RiskAssessment(risk_flags=[RiskFlag(category="urgent_symptom", description="Chest pain with breathlessness warrants review.", severity=RiskSeverity.HIGH, evidence="chest pain and breathlessness", requires_clinician_review=True)], overall_attention_level=AttentionLevel.URGENT)
    result = summary(chest_history(), risk, response={"overview": "Reported chest pain and breathlessness.", "overall_attention_level": "urgent"})
    assert result.overall_attention_level is AttentionLevel.URGENT
    assert any("Urgent review" in line for line in result.safety_items_to_review)


def test_risk_downgrade_is_rejected() -> None:
    risk = RiskAssessment(overall_attention_level=AttentionLevel.URGENT)
    llm = ScriptedLLM([{"overview": "Reported chest pain.", "overall_attention_level": "routine"}, {"overview": "Reported chest pain.", "overall_attention_level": "routine"}])
    with pytest.raises(StructuredOutputError):
        SummaryAgent(llm).summarize(chest_history(), risk)
    assert len(llm.calls) == 2


def test_diagnosis_hallucination_is_rejected() -> None:
    llm = ScriptedLLM([{"overview": "Patient has myocardial infarction."}, {"overview": "Patient has myocardial infarction."}])
    with pytest.raises(StructuredOutputError):
        SummaryAgent(llm).summarize(chest_history())


def test_document_diagnosis_is_clearly_document_derived() -> None:
    document = DocumentExtraction.model_validate({"diagnoses_mentioned": [{"text": "Type 2 diabetes mellitus", "source_text": "Diagnosis: Type 2 diabetes mellitus."}]})
    result = summary(ClinicalHistory(chief_complaint="headache"), documents=[document], response={"overview": "Reported headache."})
    assert "Diagnosis mentioned in uploaded document: Type 2 diabetes mellitus." in result.document_derived_findings
    assert "AI diagnosis" not in " ".join(result.document_derived_findings)


def test_medication_hallucination_is_rejected() -> None:
    llm = ScriptedLLM([{"overview": "Reported headache and aspirin."}, {"overview": "Reported headache and aspirin."}])
    with pytest.raises(StructuredOutputError):
        SummaryAgent(llm).summarize(ClinicalHistory(chief_complaint="headache"))


def test_lab_hallucination_is_rejected() -> None:
    document = DocumentExtraction.model_validate({"lab_results": [{"test_name": "HbA1c", "value_as_reported": "8.2", "unit_as_reported": "%", "source_text": "HbA1c 8.2%"}]})
    llm = ScriptedLLM([{"overview": "Uploaded document HbA1c 9.2%."}, {"overview": "Uploaded document HbA1c 9.2%."}])
    with pytest.raises(StructuredOutputError):
        SummaryAgent(llm).summarize(ClinicalHistory(chief_complaint="headache"), document_extractions=[document])


def test_allergy_hallucination_is_rejected() -> None:
    llm = ScriptedLLM([{"overview": "No known allergies."}, {"overview": "No known allergies."}])
    with pytest.raises(StructuredOutputError):
        SummaryAgent(llm).summarize(ClinicalHistory(chief_complaint="headache"))


def test_patient_self_diagnosis_remains_concern() -> None:
    history = ClinicalHistory(chief_complaint="headache", patient_reported_concerns=["Patient reports believing they may have diabetes."])
    result = summary(history, response={"overview": "Reported headache and diabetes concern."})
    assert result.patient_reported_concerns == ["Patient reports believing they may have diabetes."]


def test_meaningful_missing_information_is_preserved() -> None:
    history = ClinicalHistory(chief_complaint="headache", missing_information=["allergies", "duration"])
    result = summary(history, response={"overview": "Reported headache."})
    assert result.information_gaps == ["allergies", "duration"]


def test_cross_source_medication_conflict_is_preserved() -> None:
    history = ClinicalHistory(chief_complaint="headache", contradictions=["Patient reported no medications."])
    result = summary(history, documents=[metformin_document()], response={"overview": "Reported headache."})
    assert result.contradictions == ["Patient reported no medications."]
    assert result.document_derived_findings


def test_document_uncertainty_is_preserved() -> None:
    document = DocumentExtraction.model_validate({"lab_results": [{"test_name": "HbA1c", "value_as_reported": "8.2", "unit_as_reported": "%", "source_text": "HbA1c 8.2%", "uncertain": True}]})
    result = summary(ClinicalHistory(chief_complaint="headache"), documents=[document], response={"overview": "Reported headache."})
    assert any("uncertainty" in line.lower() for line in result.document_derived_findings)


def test_empty_document_allows_history_summary() -> None:
    result = summary(ClinicalHistory(chief_complaint="headache"), documents=[DocumentExtraction()], response={"overview": "Reported headache."})
    assert result.structured_history_highlights


def test_empty_risk_output_is_supported() -> None:
    result = summary(ClinicalHistory(chief_complaint="headache"), RiskAssessment(), response={"overview": "Reported headache."})
    assert result.overall_attention_level is AttentionLevel.ROUTINE
    assert result.safety_items_to_review == []


def test_empty_clinical_history_is_graceful() -> None:
    llm = ScriptedLLM([])
    result = SummaryAgent(llm).summarize()
    assert "No validated" in result.overview
    assert not llm.calls


def test_malformed_llm_output_fails_after_one_repair() -> None:
    llm = ScriptedLLM(["{bad json", "still bad"])
    with pytest.raises(StructuredOutputError):
        SummaryAgent(llm).summarize(ClinicalHistory(chief_complaint="headache"))
    assert len(llm.calls) == 2


def test_invalid_input_is_rejected() -> None:
    with pytest.raises(Exception):
        SummaryAgent(ScriptedLLM([])).summarize({"clinical_history": {"unexpected": "value"}})


def test_source_traceability_covers_history_document_and_risk() -> None:
    risk = RiskAssessment(risk_flags=[RiskFlag(category="safety_symptom", description="Reported chest pain needs clinician review.", evidence="chest pain", requires_clinician_review=True)], overall_attention_level=AttentionLevel.ATTENTION)
    result = summary(chest_history(), risk, [metformin_document()], {"overview": "Reported chest pain.", "overall_attention_level": "attention"})
    sources = set(result.source_evidence.values())
    assert {"clinical_history", "risk_assessment", "document"} <= sources


def test_valid_enumerated_model_provenance_is_accepted() -> None:
    result = summary(
        chest_history(),
        response={
            "overview": "Patient reports chest pain.",
            "source_evidence": {"overview": "clinical_history"},
        },
    )
    assert result.source_evidence["overview"] is SummarySourceType.CLINICAL_HISTORY


@pytest.mark.parametrize("invalid_source", ["patient", "physician", "clinical_assessment", "AI_analysis"])
def test_invalid_model_provenance_is_rejected_without_relabeling(invalid_source: str) -> None:
    llm = ScriptedLLM([
        {"overview": "Reported chest pain.", "source_evidence": {"overview": invalid_source}},
        {"overview": "Reported chest pain.", "source_evidence": {"overview": invalid_source}},
    ])
    with pytest.raises(StructuredOutputError):
        SummaryAgent(llm).summarize(chest_history())
    assert len(llm.calls) == 2


def test_final_provenance_never_copies_raw_patient_excerpt() -> None:
    history = chest_history()
    history.source_evidence = {"chief_complaint": "I have chest pain."}
    result = summary(history, response={"overview": "Patient reports chest pain."})
    assert all(isinstance(source, SummarySourceType) for source in result.source_evidence.values())
    assert "I have chest pain." not in {str(source) for source in result.source_evidence.values()}


@pytest.mark.parametrize("provider_name", ["groq", "ollama"])
def test_provider_parity_uses_the_same_grounded_summary_contract(provider_name: str) -> None:
    class ProviderNamedLLM(ScriptedLLM):
        name = ""

    llm = ProviderNamedLLM([{
        "overview": "Patient reports chest pain for 2 days.",
        "source_evidence": {"overview": "clinical_history"},
    }])
    llm.name = provider_name
    result = SummaryAgent(llm).summarize(chest_history())
    assert result.overview == "Patient reports chest pain for 2 days."
    assert result.source_evidence["overview"] is SummarySourceType.CLINICAL_HISTORY
    assert result.overall_attention_level is AttentionLevel.ROUTINE


def test_end_to_end_phase_one_to_five_flow_uses_native_interfaces() -> None:
    interview = InterviewAgent(ScriptedLLM([InterviewLLMResponse(
        assistant_message="When did it start?", next_question_category="onset",
        field_updates=[FieldUpdate(category="chief_complaint", value="chest pain", status=InformationStatus.EXPLICIT, patient_excerpt="I have chest pain and breathlessness.")],
    )]))
    interview_result = interview.handle_message("I have chest pain and breathlessness.")
    history = StructuringAgent(ScriptedLLM([{
        "chief_complaint": "chest pain", "associated_symptoms": ["breathlessness"],
        "source_evidence": {"chief_complaint": "I have chest pain and breathlessness.", "associated_symptoms": "I have chest pain and breathlessness."},
    }])).structure(interview_result)
    risk = RiskAgent(ScriptedLLM([{}])).assess(history)
    document = DocumentAgent(ScriptedLLM([{"medications": [{"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "source_text": "Metformin 500 mg"}]}])).extract("Metformin 500 mg")
    result = SummaryAgent(ScriptedLLM([{"overview": "Reported chest pain and breathlessness.", "overall_attention_level": "urgent"}])).summarize(history, risk, [document])
    assert result.overall_attention_level is AttentionLevel.URGENT
    assert result.document_derived_findings
    assert result.safety_items_to_review


def test_successful_summary_passes_pydantic_schema() -> None:
    result = summary(ClinicalHistory(chief_complaint="headache"), response={"overview": "Reported headache."})
    assert PhysicianSummary.model_validate(result.model_dump()) == result


def test_summary_input_object_is_accepted() -> None:
    payload = SummaryInput(clinical_history=ClinicalHistory(chief_complaint="headache"))
    result = SummaryAgent(ScriptedLLM([{"overview": "Reported headache."}])).summarize(payload)
    assert result.structured_history_highlights
