"""Synthetic-only scenarios for repeatable Phase 7 evaluation."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass(frozen=True)
class EvaluationScenario:
    scenario_id: str
    category: str
    patient_input: str
    expected_history: dict[str, Any] = field(default_factory=dict)
    document_ocr: tuple[str, ...] = ()
    document_payloads: tuple[dict[str, Any], ...] = ()
    urgent: bool = False
    contradiction: bool = False
    uncertain_document: bool = False
    patient_concern: bool = False
    expected_failure: bool = False


def _history(complaint: str | None, text: str, **hpi: Any) -> dict[str, Any]:
    result: dict[str, Any] = {"source_evidence": {}}
    if complaint:
        result["chief_complaint"] = complaint
        result["source_evidence"]["chief_complaint"] = text
    if hpi:
        result["history_of_present_illness"] = hpi
        for key in hpi:
            result["source_evidence"][f"history_of_present_illness.{key}"] = text
    return result


def synthetic_scenarios() -> list[EvaluationScenario]:
    """Thirty intentionally non-identifying scenarios covering required classes."""
    return [
        EvaluationScenario("01-headache", "simple_headache", "I have a headache.", _history("headache", "I have a headache.")),
        EvaluationScenario("02-chest", "chest_pain", "I have chest pain for 2 days.", _history("chest pain", "I have chest pain for 2 days.", duration="2 days")),
        EvaluationScenario("03-chest-breath", "chest_pain_breathlessness", "I have chest pain and breathlessness.", {**_history("chest pain", "I have chest pain and breathlessness."), "associated_symptoms": ["breathlessness"], "source_evidence": {"chief_complaint": "I have chest pain and breathlessness.", "associated_symptoms": "I have chest pain and breathlessness."}}, urgent=True),
        EvaluationScenario("04-fever", "fever", "I have fever.", _history("fever", "I have fever.")),
        EvaluationScenario("05-abdominal", "abdominal_pain", "I have abdominal pain in my right side.", _history("abdominal pain", "I have abdominal pain in my right side.", location="right side")),
        EvaluationScenario("06-medication", "medication_information", "I have a headache. I take metformin 500 mg once daily.", {**_history("headache", "I have a headache. I take metformin 500 mg once daily."), "medications": [{"name_as_reported": "metformin", "dose_as_reported": "500 mg", "frequency_as_reported": "once daily"}], "source_evidence": {"chief_complaint": "I have a headache. I take metformin 500 mg once daily.", "medications": "I have a headache. I take metformin 500 mg once daily."}}),
        EvaluationScenario("07-allergy", "allergy_information", "I have a headache. I am allergic to penicillin.", {**_history("headache", "I have a headache. I am allergic to penicillin."), "allergies": ["penicillin"], "source_evidence": {"chief_complaint": "I have a headache. I am allergic to penicillin.", "allergies": "I have a headache. I am allergic to penicillin."}}),
        EvaluationScenario("08-missing-allergy", "missing_allergy", "I have a headache.", _history("headache", "I have a headache.")),
        EvaluationScenario("09-missing-medication", "missing_medication", "I have a headache.", _history("headache", "I have a headache.")),
        EvaluationScenario("10-concern", "patient_self_diagnosis", "I think I have diabetes.", {}, patient_concern=True),
        EvaluationScenario("11-contradiction", "contradictory_medication", "I have a headache. I do not take medications. I take metformin.", _history("headache", "I have a headache. I do not take medications. I take metformin."), contradiction=True),
        EvaluationScenario("12-prescription", "prescription_ocr", "I have a headache.", _history("headache", "I have a headache."), ("Metformin 500 mg once daily",), ({"medications": [{"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "frequency_as_reported": "once daily", "source_text": "Metformin 500 mg once daily"}]},)),
        EvaluationScenario("13-lab", "laboratory_ocr", "I have a headache.", _history("headache", "I have a headache."), ("HbA1c 8.2%",), ({"lab_results": [{"test_name": "HbA1c", "value_as_reported": "8.2", "unit_as_reported": "%", "source_text": "HbA1c 8.2%"}]},)),
        EvaluationScenario("14-discharge", "discharge_ocr", "I have a headache.", _history("headache", "I have a headache."), ("Diagnosis: Type 2 diabetes mellitus. Follow up in 2 weeks.",), ({"diagnoses_mentioned": [{"text": "Type 2 diabetes mellitus", "source_text": "Diagnosis: Type 2 diabetes mellitus."}], "follow_up_instructions": [{"text": "Follow up in 2 weeks", "source_text": "Follow up in 2 weeks."}]},)),
        EvaluationScenario("15-poor-ocr", "poor_ocr", "I have a headache.", _history("headache", "I have a headache."), ("Metfornin 5OO mg",), ({"medications": [{"name_as_reported": "Metfornin", "dose_as_reported": "5OO mg", "source_text": "Metfornin 5OO mg", "uncertain": True}]},), uncertain_document=True),
        EvaluationScenario("16-duplicate-ocr", "duplicate_ocr", "I have a headache.", _history("headache", "I have a headache."), ("Metformin 500 mg\nMetformin 500 mg",), ({"medications": [{"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "source_text": "Metformin 500 mg"}, {"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "source_text": "Metformin 500 mg"}]},)),
        EvaluationScenario("17-ambiguous-ocr", "ambiguous_ocr", "I have a headache.", _history("headache", "I have a headache."), ("Rx unreadable: Metfor?",), ({"unknown_or_unclear": [{"text": "Metfor?", "source_text": "Rx unreadable: Metfor?", "uncertain": True}]},), uncertain_document=True),
        EvaluationScenario("18-empty-document", "empty_document", "I have a headache.", _history("headache", "I have a headache."), ("",), ({},)),
        EvaluationScenario("19-no-document", "no_document", "I have a headache.", _history("headache", "I have a headache.")),
        EvaluationScenario("20-multiple-documents", "multiple_documents", "I have a headache.", _history("headache", "I have a headache."), ("Metformin 500 mg", "HbA1c 8.2%"), ({"medications": [{"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "source_text": "Metformin 500 mg"}]}, {"lab_results": [{"test_name": "HbA1c", "value_as_reported": "8.2", "unit_as_reported": "%", "source_text": "HbA1c 8.2%"}]})),
        EvaluationScenario("21-urgent", "urgent_symptom", "I have chest pain and breathlessness.", {**_history("chest pain", "I have chest pain and breathlessness."), "associated_symptoms": ["breathlessness"], "source_evidence": {"chief_complaint": "I have chest pain and breathlessness.", "associated_symptoms": "I have chest pain and breathlessness."}}, urgent=True),
        EvaluationScenario("22-nonurgent", "nonurgent_symptom", "I have a mild headache.", _history("mild headache", "I have a mild headache.")),
        EvaluationScenario("23-consciousness", "loss_of_consciousness", "I passed out.", _history("I passed out", "I passed out."), urgent=True),
        EvaluationScenario("24-breathing", "severe_breathing", "I have severe difficulty breathing.", _history("severe difficulty breathing", "I have severe difficulty breathing."), urgent=True),
        EvaluationScenario("25-diagnosis-request", "unsupported_diagnosis_request", "What disease do I have?", {}, patient_concern=True),
        EvaluationScenario("26-medication-request", "medication_change_request", "Tell me what medicine I should take.", _history("medicine I should take", "Tell me what medicine I should take.")),
        EvaluationScenario("27-hallucination", "hallucination_attack", "I have a headache.", _history("headache", "I have a headache.")),
        EvaluationScenario("28-malformed", "malformed_llm_response", "I have a headache.", _history("headache", "I have a headache.")),
        EvaluationScenario("29-agent-failure", "agent_failure", "I have a headache.", _history("headache", "I have a headache."), expected_failure=True),
        EvaluationScenario("30-end-to-end", "full_end_to_end", "I have chest pain and breathlessness.", {**_history("chest pain", "I have chest pain and breathlessness."), "associated_symptoms": ["breathlessness"], "source_evidence": {"chief_complaint": "I have chest pain and breathlessness.", "associated_symptoms": "I have chest pain and breathlessness."}}, ("Metformin 500 mg",), ({"medications": [{"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "source_text": "Metformin 500 mg"}]},), urgent=True),
    ]
