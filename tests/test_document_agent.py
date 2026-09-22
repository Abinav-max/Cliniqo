"""Document Intelligence Agent tests using synthetic OCR and mocked LLM output."""

from __future__ import annotations

from typing import Any, Optional

import pytest
from pydantic import BaseModel

from agents.document_agent import DocumentAgent
from core.exceptions import StructuredOutputError
from core.schemas import ClinicalHistory, DocumentExtraction, DocumentInput


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


def extract(ocr: str, response: Any, **metadata: Any) -> DocumentExtraction:
    return DocumentAgent(ScriptedLLM([response])).extract({"ocr_text": ocr, **metadata})


def test_prescription_extracts_medication_details() -> None:
    result = extract(
        "Metformin 500 mg once daily by mouth for 30 days",
        {"medications": [{
            "name_as_reported": "Metformin",
            "dose_as_reported": "500 mg",
            "frequency_as_reported": "once daily",
            "route_as_reported": "by mouth",
            "duration_as_reported": "for 30 days",
            "source_text": "Metformin 500 mg once daily by mouth for 30 days",
        }]},
        document_id="rx-1",
        document_type="prescription",
    )
    medication = result.medications[0]
    assert medication.name_as_reported == "Metformin"
    assert medication.dose_as_reported == "500 mg"
    assert medication.frequency_as_reported == "once daily"
    assert result.document_type == "prescription"


def test_laboratory_report_extracts_value_and_unit() -> None:
    result = extract(
        "HbA1c 8.2 %",
        {"lab_results": [{
            "test_name": "HbA1c",
            "value_as_reported": "8.2",
            "unit_as_reported": "%",
            "source_text": "HbA1c 8.2 %",
        }]},
    )
    lab = result.lab_results[0]
    assert (lab.test_name, lab.value_as_reported, lab.unit_as_reported) == ("HbA1c", "8.2", "%")
    assert lab.source_text == "HbA1c 8.2 %"


def test_discharge_summary_extracts_document_mentions_only() -> None:
    ocr = """Discharge Summary
Diagnosis: Type 2 diabetes mellitus.
Metformin 500 mg once daily.
Follow up in 2 weeks."""
    result = extract(ocr, {
        "diagnoses_mentioned": [{"text": "Type 2 diabetes mellitus", "source_text": "Diagnosis: Type 2 diabetes mellitus."}],
        "medications": [{"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "frequency_as_reported": "once daily", "source_text": "Metformin 500 mg once daily."}],
        "follow_up_instructions": [{"text": "Follow up in 2 weeks", "source_text": "Follow up in 2 weeks."}],
    })
    assert result.diagnoses_mentioned[0].text == "Type 2 diabetes mellitus"
    assert result.medications[0].name_as_reported == "Metformin"
    assert result.follow_up_instructions[0].text == "Follow up in 2 weeks"


def test_allergy_is_extracted_from_document() -> None:
    result = extract("Allergy: Penicillin", {
        "allergies": [{"text": "Penicillin", "source_text": "Allergy: Penicillin"}],
    })
    assert result.allergies[0].text == "Penicillin"
    assert result.allergies[0].source_type == "document"


def test_date_is_extracted_with_source_evidence() -> None:
    result = extract("Date: 2026-09-09\nClinical note", {
        "document_date": "2026-09-09",
        "document_date_source_text": "Date: 2026-09-09",
    })
    assert result.document_date == "2026-09-09"
    assert result.document_date_source_text == "Date: 2026-09-09"


def test_missing_information_is_not_invented_for_medication_only_document() -> None:
    result = extract("Metformin 500 mg once daily", {
        "medications": [{"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "frequency_as_reported": "once daily", "source_text": "Metformin 500 mg once daily"}],
    })
    assert result.diagnoses_mentioned == []
    assert result.lab_results == []
    assert result.allergies == []


def test_absent_allergy_statement_is_not_converted_to_no_allergies() -> None:
    result = extract("Metformin 500 mg once daily", {})
    assert result.allergies == []
    assert all(item.text.lower() != "none" for item in result.allergies)


def test_poor_ocr_can_be_preserved_as_uncertain() -> None:
    result = extract("Metfornin 5OO mg", {
        "medications": [{
            "name_as_reported": "Metfornin",
            "dose_as_reported": "5OO mg",
            "source_text": "Metfornin 5OO mg",
            "uncertain": True,
        }],
    })
    assert result.medications[0].uncertain is True
    assert result.medications[0].source_text == "Metfornin 5OO mg"


def test_uncertainty_does_not_allow_an_invented_entity() -> None:
    result = extract("Patient visited clinic today.", {
        "medications": [{
            "name_as_reported": "Metformin",
            "source_text": "Patient visited clinic today.",
            "uncertain": True,
        }],
    })
    assert result.medications == []


def test_duplicate_ocr_lines_are_deduplicated() -> None:
    line = "Metformin 500 mg once daily"
    result = extract(f"{line}\n{line}", {
        "medications": [
            {"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "frequency_as_reported": "once daily", "source_text": line},
            {"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "frequency_as_reported": "once daily", "source_text": line},
        ],
    })
    assert len(result.medications) == 1


def test_explicit_document_diagnosis_is_mention_not_ai_diagnosis() -> None:
    result = extract("Diagnosis: Type 2 diabetes mellitus.", {
        "diagnoses_mentioned": [{"text": "Type 2 diabetes mellitus", "source_text": "Diagnosis: Type 2 diabetes mellitus."}],
    })
    assert result.diagnoses_mentioned[0].text == "Type 2 diabetes mellitus"
    assert not hasattr(result, "diagnosis")


def test_lab_value_does_not_invent_a_diagnosis() -> None:
    result = extract("HbA1c 8.2%", {
        "lab_results": [{"test_name": "HbA1c", "value_as_reported": "8.2", "unit_as_reported": "%", "source_text": "HbA1c 8.2%"}],
    })
    assert result.diagnoses_mentioned == []


def test_document_without_medication_does_not_invent_one() -> None:
    result = extract("HbA1c 8.2%", {
        "medications": [{"name_as_reported": "Metformin", "source_text": "HbA1c 8.2%"}],
    })
    assert result.medications == []


def test_entities_preserve_source_evidence() -> None:
    source = "Allergy: Penicillin"
    result = extract(source, {
        "allergies": [{"text": "Penicillin", "source_text": source}],
    })
    assert result.allergies[0].source_text == source
    assert result.allergies[0].source_type == "document"


def test_malformed_llm_output_fails_safely_after_one_repair() -> None:
    llm = ScriptedLLM(["{invalid json", "still invalid json"])
    with pytest.raises(StructuredOutputError):
        DocumentAgent(llm).extract("Patient visited clinic today.")
    assert len(llm.calls) == 2


def test_hallucination_resistance_for_generic_document() -> None:
    result = extract("Patient visited clinic today.", {})
    assert result.medications == []
    assert result.lab_results == []
    assert result.diagnoses_mentioned == []
    assert result.allergies == []


def test_ai_treatment_advice_field_is_rejected() -> None:
    llm = ScriptedLLM([{"recommendation": "Stop metformin"}])
    with pytest.raises(StructuredOutputError, match="repaired and validated"):
        DocumentAgent(llm).extract("Metformin 500 mg once daily")


def test_empty_ocr_text_is_handled_without_llm_call() -> None:
    llm = ScriptedLLM([])
    result = DocumentAgent(llm).extract({"document_id": "empty-1", "ocr_text": "  "})
    assert result.document_id == "empty-1"
    assert result.medications == []
    assert result.missing_or_illegible_sections == ["OCR text was empty."]
    assert not llm.calls


def test_phase_two_history_and_ocr_document_remain_separate_for_summary_input() -> None:
    patient_history = ClinicalHistory(chief_complaint="headache")
    document = extract("Metformin 500 mg once daily", {
        "medications": [{"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "frequency_as_reported": "once daily", "source_text": "Metformin 500 mg once daily"}],
    }, document_id="ocr-1")
    assert patient_history.chief_complaint == "headache"
    assert document.document_id == "ocr-1"
    assert document.medications[0].source_type == "document"
    assert document.for_clinician_review_only is True


def test_successful_result_passes_document_extraction_schema() -> None:
    result = extract("HbA1c 8.2%", {
        "lab_results": [{"test_name": "HbA1c", "value_as_reported": "8.2", "unit_as_reported": "%", "source_text": "HbA1c 8.2%"}],
    })
    assert DocumentExtraction.model_validate(result.model_dump()) == result
