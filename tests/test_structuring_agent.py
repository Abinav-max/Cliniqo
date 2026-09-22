"""Clinical Structuring Agent tests. All LLM responses are local fakes."""

from __future__ import annotations

from typing import Any, Optional

import pytest
from pydantic import BaseModel

from agents.interview_agent import FieldUpdate, InformationStatus, InterviewAgent, InterviewLLMResponse
from agents.structuring_agent import StructuringAgent
from core.exceptions import StructuredOutputError
from core.schemas import ClinicalHistory


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


def payload(**values: Any) -> dict[str, Any]:
    """Payload helper; omitted fields intentionally exercise schema defaults."""
    return values


def test_complete_history_extracts_reported_facts() -> None:
    llm = ScriptedLLM([
        payload(
            chief_complaint="chest pain",
            history_of_present_illness={"duration": "2 days", "location": "center of my chest", "severity": 7},
            associated_symptoms=["nausea"],
            medications=[{"name_as_reported": "metformin", "dose_as_reported": "500 mg", "frequency_as_reported": "once a day"}],
            allergies=["penicillin"],
            source_evidence={
                "chief_complaint": "I have chest pain.",
                "history_of_present_illness.duration": "It started two days ago.",
                "history_of_present_illness.location": "It is in the center of my chest.",
                "history_of_present_illness.severity": "It is 7 out of 10.",
                "associated_symptoms": "I also feel nausea.",
                "medications": "I take metformin 500 mg once a day.",
                "allergies": "I am allergic to penicillin.",
            },
        )
    ])
    result = StructuringAgent(llm).structure(
        """Patient: I have chest pain.
Assistant: When did it start?
Patient: It started two days ago.
Assistant: Where is it and how severe is it?
Patient: It is in the center of my chest. It is 7 out of 10.
Patient: I also feel nausea. I take metformin 500 mg once a day. I am allergic to penicillin."""
    )
    assert result.chief_complaint == "chest pain"
    assert result.history_of_present_illness.duration == "2 days"
    assert result.history_of_present_illness.location == "center of my chest"
    assert result.history_of_present_illness.severity == 7
    assert result.associated_symptoms == ["nausea"]
    assert result.medications[0].name_as_reported == "metformin"
    assert result.allergies == ["penicillin"]
    assert llm.calls[0]["schema"] is ClinicalHistory


def test_minimal_history_leaves_other_fields_unknown() -> None:
    result = StructuringAgent(ScriptedLLM([
        payload(chief_complaint="chest pain", source_evidence={"chief_complaint": "I have chest pain."})
    ])).structure("I have chest pain.")
    assert result.chief_complaint == "chest pain"
    assert result.medications == []
    assert result.allergies == []
    assert "duration" in result.unknown_information


def test_reported_severity_descriptor_is_preserved_only_when_grounded() -> None:
    result = StructuringAgent(ScriptedLLM([
        payload(
            chief_complaint="chest pain",
            history_of_present_illness={"duration": "2 hours", "severity": "severe"},
            source_evidence={
                "chief_complaint": "I have had severe chest pain for 2 hours.",
                "history_of_present_illness.duration": "I have had severe chest pain for 2 hours.",
                "history_of_present_illness.severity": "I have had severe chest pain for 2 hours.",
            },
        )
    ])).structure("I have had severe chest pain for 2 hours.")
    assert result.history_of_present_illness.severity == "severe"


def test_missing_information_uses_empty_and_unknown_representations() -> None:
    result = StructuringAgent(ScriptedLLM([
        payload(chief_complaint="headache", source_evidence={"chief_complaint": "I have a headache."})
    ])).structure("I have a headache.")
    assert result.history_of_present_illness.onset is None
    assert result.past_medical_history == []
    assert result.unknown_information == result.missing_information


def test_patient_uncertainty_is_not_a_confirmed_condition() -> None:
    result = StructuringAgent(ScriptedLLM([
        payload(
            chief_complaint="diabetes",
            past_medical_history=["diabetes"],
            source_evidence={
                "chief_complaint": "I think I have diabetes.",
                "past_medical_history": "I think I have diabetes.",
            },
        )
    ])).structure("I think I have diabetes.")
    assert result.chief_complaint is None
    assert result.past_medical_history == []
    assert any("diabetes" in concern.lower() for concern in result.patient_reported_concerns)


def test_medication_is_extracted_as_reported() -> None:
    result = StructuringAgent(ScriptedLLM([
        payload(
            medications=[{"name_as_reported": "metformin", "dose_as_reported": "500 mg", "frequency_as_reported": "once a day"}],
            source_evidence={"medications": "I take metformin 500 mg once a day."},
        )
    ])).structure("I take metformin 500 mg once a day.")
    medication = result.medications[0]
    assert (medication.name_as_reported, medication.dose_as_reported, medication.frequency_as_reported) == ("metformin", "500 mg", "once a day")


def test_allergy_is_extracted_as_reported() -> None:
    result = StructuringAgent(ScriptedLLM([
        payload(allergies=["penicillin"], source_evidence={"allergies": "I am allergic to penicillin."})
    ])).structure("I am allergic to penicillin.")
    assert result.allergies == ["penicillin"]


def test_conflicting_medication_statements_are_flagged() -> None:
    result = StructuringAgent(ScriptedLLM([
        payload(medications=[{"name_as_reported": "metformin"}], source_evidence={"medications": "I take metformin."})
    ])).structure("Patient: I do not take any medications.\nPatient: I take metformin.")
    assert result.contradictions == ["Medication history contains conflicting statements."]


def test_empty_conversation_is_handled_without_an_llm_call() -> None:
    llm = ScriptedLLM([])
    result = StructuringAgent(llm).structure([])
    assert result.chief_complaint is None
    assert result.unknown_information
    assert not llm.calls


def test_malformed_llm_json_raises_controlled_error_after_repair() -> None:
    llm = ScriptedLLM(["{invalid json", "still not json"])
    with pytest.raises(StructuredOutputError):
        StructuringAgent(llm).structure("I have a headache.")
    assert len(llm.calls) == 2


def test_hallucinated_facts_are_removed() -> None:
    result = StructuringAgent(ScriptedLLM([
        payload(
            chief_complaint="headache",
            past_medical_history=["diabetes"],
            medications=[{"name_as_reported": "metformin"}],
            allergies=["penicillin"],
            source_evidence={"chief_complaint": "I have a headache."},
        )
    ])).structure("I have a headache.")
    assert result.chief_complaint == "headache"
    assert result.past_medical_history == []
    assert result.medications == []
    assert result.allergies == []
    assert not hasattr(result, "diagnosis")


def test_successful_result_passes_the_pydantic_schema() -> None:
    result = StructuringAgent(ScriptedLLM([
        payload(chief_complaint="headache", source_evidence={"chief_complaint": "I have a headache."})
    ])).structure("I have a headache.")
    assert ClinicalHistory.model_validate(result.model_dump()) == result


def test_diagnosis_question_never_becomes_a_diagnosis() -> None:
    result = StructuringAgent(ScriptedLLM([
        payload(patient_reported_concerns=["Do I have a heart attack?"], source_evidence={})
    ])).structure("Do I have a heart attack?")
    assert not hasattr(result, "diagnosis")
    assert result.past_medical_history == []
    assert any("heart attack" in concern.lower() for concern in result.patient_reported_concerns)


def test_phase_one_interview_result_is_accepted_without_transformation() -> None:
    interview_llm = ScriptedLLM([
        InterviewLLMResponse(
            assistant_message="When did the chest pain start?",
            field_updates=[FieldUpdate(category="chief_complaint", value="chest pain", status=InformationStatus.EXPLICIT, patient_excerpt="I have chest pain.")],
            next_question_category="onset",
        )
    ])
    interview = InterviewAgent(interview_llm, session_id="phase-one-session")
    interview_result = interview.handle_message("I have chest pain.")
    structuring_llm = ScriptedLLM([
        payload(chief_complaint="chest pain", source_evidence={"chief_complaint": "I have chest pain."})
    ])
    history = StructuringAgent(structuring_llm).structure(interview_result)
    assert history.session_id == "phase-one-session"
    assert history.chief_complaint == "chest pain"
