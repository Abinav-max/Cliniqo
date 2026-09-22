"""Interview Agent unit tests (mocked LLM) and one optional live call."""

from __future__ import annotations

import re
import os
from typing import Any, Optional

import pytest
from pydantic import BaseModel

from agents.interview_agent import (
    FieldUpdate,
    InformationStatus,
    InterviewAgent,
    InterviewLLMResponse,
)
from core.config import get_settings
from core.exceptions import LLMConnectionError, StructuredOutputError
from core.llm_client import LLMClient


class ScriptedLLM:
    """Queue of structured interview turns. No network."""

    def __init__(self, responses: list[InterviewLLMResponse]) -> None:
        self._responses = list(responses)
        self.prompts: list[str] = []

    def generate_json(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        self.prompts.append(prompt)
        if not self._responses:
            raise AssertionError("ScriptedLLM has no remaining responses.")
        item = self._responses.pop(0)
        if schema is not None and not isinstance(item, schema):
            return schema.model_validate(item.model_dump())
        return item


def _turn(
    assistant_message: str,
    *,
    next_question_category: str,
    field_updates: list[FieldUpdate] | None = None,
    missing: list[str] | None = None,
    complete: bool = False,
    concerns: list[str] | None = None,
    urgent: list[str] | None = None,
) -> InterviewLLMResponse:
    return InterviewLLMResponse(
        assistant_message=assistant_message,
        field_updates=field_updates or [],
        missing_information=missing or [],
        next_question_category=next_question_category,
        interview_complete=complete,
        patient_reported_concerns=concerns or [],
        urgent_symptoms_mentioned=urgent or [],
    )


def test_headache_asks_relevant_follow_up() -> None:
    llm = ScriptedLLM(
        [
            _turn(
                "When did the headache start?",
                next_question_category="onset",
                field_updates=[
                    FieldUpdate(
                        category="chief_complaint",
                        value="headache",
                        status=InformationStatus.EXPLICIT,
                        patient_excerpt="I have a headache",
                    )
                ],
            )
        ]
    )
    agent = InterviewAgent(llm)
    result = agent.handle_message("I have a headache.")
    assert "headache" in str(result.information_collected["chief_complaint"]["value"])
    assert result.next_question_category in {
        "onset",
        "duration",
        "location",
        "character",
        "severity",
        "timing",
        "associated_symptoms",
    }
    lowered = result.assistant_message.lower()
    assert any(
        token in lowered
        for token in ("when", "where", "how long", "severe", "feel", "start")
    )
    assert not result.interview_complete


def test_chest_pain_gathers_symptom_details() -> None:
    llm = ScriptedLLM(
        [
            _turn(
                "When did the chest pain start?",
                next_question_category="onset",
                field_updates=[
                    FieldUpdate(
                        category="chief_complaint",
                        value="chest pain",
                        status=InformationStatus.EXPLICIT,
                        patient_excerpt="I have chest pain",
                    )
                ],
                urgent=["chest pain"],
            )
        ]
    )
    agent = InterviewAgent(llm)
    result = agent.handle_message("I have chest pain.")
    collected = result.information_collected
    assert collected["chief_complaint"]["value"]
    assert "chest pain" in collected["chief_complaint"]["value"]
    assert collected["urgent_symptoms_mentioned"]
    assert result.next_question_category is not None
    assert not _has_diagnostic_claim(result.assistant_message)


def test_does_not_reask_duration_and_severity() -> None:
    llm = ScriptedLLM(
        [
            _turn(
                "How long has this been going on? How severe is it on a scale of 0 to 10?",
                next_question_category="duration",
                field_updates=[
                    FieldUpdate(
                        category="chief_complaint",
                        value="headache",
                        status=InformationStatus.EXPLICIT,
                        patient_excerpt="headache",
                    ),
                    FieldUpdate(
                        category="duration",
                        value="3 days",
                        status=InformationStatus.EXPLICIT,
                        patient_excerpt="for 3 days",
                    ),
                    FieldUpdate(
                        category="severity",
                        value="7",
                        status=InformationStatus.EXPLICIT,
                        patient_excerpt="severity 7/10",
                    ),
                ],
            )
        ]
    )
    agent = InterviewAgent(llm)
    result = agent.handle_message(
        "I have a headache for 3 days, severity 7/10."
    )
    assert result.information_collected["duration"]["status"] == "explicit"
    assert result.information_collected["severity"]["status"] == "explicit"
    lowered = result.assistant_message.lower()
    assert "how long" not in lowered
    assert "0 to 10" not in lowered
    assert "0-10" not in lowered
    assert result.next_question_category not in {"duration", "severity"}


def test_i_dont_know_leaves_field_unknown() -> None:
    llm = ScriptedLLM(
        [
            _turn("When did the headache start?", next_question_category="onset"),
            _turn(
                "Where do you feel the headache?",
                next_question_category="location",
                field_updates=[
                    FieldUpdate(
                        category="onset",
                        value="last Tuesday",
                        status=InformationStatus.EXPLICIT,
                        patient_excerpt="last Tuesday",
                    )
                ],
            ),
        ]
    )
    agent = InterviewAgent(llm)
    agent.handle_message("I have a headache.")
    result = agent.handle_message("I don't know.")
    onset = result.information_collected["onset"]
    assert onset["status"] == "unknown"
    assert onset["value"] is None


def test_does_not_diagnose_when_patient_asks_for_disease() -> None:
    llm = ScriptedLLM(
        [
            _turn(
                "You have a migraine. That is your diagnosis.",
                next_question_category="onset",
            )
        ]
    )
    agent = InterviewAgent(llm)
    result = agent.handle_message("What disease do I have?")
    lowered = result.assistant_message.lower()
    assert "you have a migraine" not in lowered
    assert "your diagnosis" not in lowered
    assert "can't diagnose" in lowered or "cannot diagnose" in lowered
    assert result.information_collected["chief_complaint"]["status"] != "explicit" or (
        "migraine"
        not in (result.information_collected["chief_complaint"]["value"] or "")
    )


def test_conversation_state_persists_across_turns() -> None:
    llm = ScriptedLLM(
        [
            _turn("When did the chest pain start?", next_question_category="onset"),
            _turn("Where exactly do you feel the pain?", next_question_category="location"),
        ]
    )
    agent = InterviewAgent(llm, session_id="session-persist")
    first = agent.handle_message("I have chest pain.")
    second = agent.handle_message("Two days ago.")
    assert first.state.session_id == second.state.session_id == "session-persist"
    assert agent is not None
    roles = [turn.role for turn in agent.state.conversation_history]
    assert roles == ["patient", "assistant", "patient", "assistant"]
    assert agent.state.conversation_history[0].content == "I have chest pain."
    assert "Two days ago." in agent.state.conversation_history[2].content
    onset = second.information_collected["onset"]
    assert onset["status"] == "explicit"
    assert "two days" in (onset["value"] or "").lower()


def test_does_not_hallucinate_patient_facts() -> None:
    llm = ScriptedLLM(
        [
            _turn(
                "When did the headache start?",
                next_question_category="onset",
                field_updates=[
                    FieldUpdate(
                        category="past_medical_history",
                        value="diabetes",
                        status=InformationStatus.EXPLICIT,
                        patient_excerpt="diabetes",
                    ),
                    FieldUpdate(
                        category="current_medications",
                        value="metformin",
                        status=InformationStatus.EXPLICIT,
                        patient_excerpt="metformin",
                    ),
                    FieldUpdate(
                        category="chief_complaint",
                        value="headache",
                        status=InformationStatus.EXPLICIT,
                        patient_excerpt="headache",
                    ),
                ],
            )
        ]
    )
    agent = InterviewAgent(llm)
    result = agent.handle_message("I have a headache.")
    past = result.information_collected["past_medical_history"]
    meds = result.information_collected["current_medications"]
    assert past["value"] != "diabetes"
    assert past["status"] != "explicit" or past["value"] is None
    assert meds["value"] != "metformin"
    assert "diabetes" not in result.assistant_message.lower()
    assert "metformin" not in result.assistant_message.lower()


def test_self_diagnosis_is_stored_as_reported_concern() -> None:
    llm = ScriptedLLM(
        [
            _turn(
                "When did the chest pain start?",
                next_question_category="onset",
                concerns=["I think I have a heart attack"],
                urgent=["chest pain", "heart attack"],
            )
        ]
    )
    agent = InterviewAgent(llm)
    result = agent.handle_message("I think I have a heart attack. I have chest pain.")
    concerns = result.information_collected["patient_reported_concerns"]
    assert any("heart attack" in item.lower() for item in concerns)
    assert not _has_diagnostic_claim(result.assistant_message)


def test_inferred_is_not_treated_as_fact() -> None:
    llm = ScriptedLLM(
        [
            _turn(
                "Have you noticed any nausea?",
                next_question_category="associated_symptoms",
                field_updates=[
                    FieldUpdate(
                        category="associated_symptoms",
                        value="possible migraine-related nausea",
                        status=InformationStatus.INFERRED,
                    )
                ],
            )
        ]
    )
    agent = InterviewAgent(llm)
    result = agent.handle_message("I have a headache.")
    associated = result.information_collected["associated_symptoms"]
    if associated["value"]:
        assert associated["status"] == "inferred"


@pytest.mark.parametrize(
    ("script", "messages", "must_not_diagnose"),
    [
        (
            [
                _turn("When did the cough start?", next_question_category="onset"),
                _turn("Is it a dry cough or do you bring anything up?", next_question_category="character"),
            ],
            ["I have a cough.", "Since yesterday."],
            True,
        ),
        (
            [
                _turn("Where is the abdominal pain?", next_question_category="location"),
                _turn("How severe is it on a scale of 0 to 10?", next_question_category="severity"),
            ],
            ["I have abdominal pain.", "Around my belly button."],
            True,
        ),
        (
            [
                _turn("When did the dizziness start?", next_question_category="onset"),
                _turn("Does anything make it better or worse?", next_question_category="timing"),
            ],
            ["I feel dizzy.", "It started this morning."],
            True,
        ),
        (
            [
                _turn("Are you taking any medications?", next_question_category="current_medications"),
            ],
            ["I have a rash on my arm."],
            True,
        ),
        (
            [
                _turn("Have you had anything like this sore throat before?", next_question_category="previous_similar_episodes"),
                _turn("Do you have any allergies?", next_question_category="allergies"),
            ],
            ["I have a sore throat.", "No, this is the first time."],
            True,
        ),
    ],
)
def test_five_synthetic_conversations(
    script: list[InterviewLLMResponse],
    messages: list[str],
    must_not_diagnose: bool,
) -> None:
    agent = InterviewAgent(ScriptedLLM(script))
    result = None
    for message in messages:
        result = agent.handle_message(message)
    assert result is not None
    if must_not_diagnose:
        assert not _has_diagnostic_claim(result.assistant_message)
    patient_blob = " ".join(messages).lower()
    for name, item in result.information_collected.items():
        if name in {"patient_reported_concerns", "urgent_symptoms_mentioned"}:
            continue
        if item["status"] == "explicit" and item["value"]:
            assert _is_subset_of_conversation(item["value"], patient_blob), (
                f"Un-grounded explicit field {name}: {item['value']!r}"
            )


def _has_diagnostic_claim(message: str) -> bool:
    """True only for language that assigns a condition, not refusals or questions."""
    lowered = message.lower()
    if re.search(r"\b(can't|cannot|do not|don't)\s+diagnos", lowered):
        refusal = True
    else:
        refusal = False
    if re.search(
        r"\b(you have (a |an )?(migraine|heart attack|stroke|infection)|"
        r"your diagnosis|i diagnose|you likely have|you probably have|"
        r"this is (a |an )?(heart attack|stroke|migraine))\b",
        lowered,
    ):
        return True
    if "your diagnosis" in lowered or "i diagnose" in lowered:
        return True
    return (not refusal) and bool(re.search(r"\byour diagnosis\b", lowered))


def _is_subset_of_conversation(value: str, patient_blob: str) -> bool:
    tokens = [t for t in value.lower().split() if len(t) > 2]
    if not tokens:
        return value.lower() in patient_blob
    return all(token.strip(".,") in patient_blob for token in tokens)


@pytest.mark.skipif(
    not (get_settings().has_api_key and os.getenv("RUN_LIVE_GROQ_TESTS") == "1"),
    reason="Set RUN_LIVE_GROQ_TESTS=1 with GROQ_API_KEY to run the optional live call.",
)
def test_optional_live_interview_turn() -> None:
    """Single synthetic turn only — avoid extra Groq usage."""
    agent = InterviewAgent(LLMClient(), session_id="synthetic-live")
    try:
        result = agent.handle_message("I have a headache. This is synthetic test data.")
    except StructuredOutputError:
        pytest.skip("Live model JSON was not parseable; unit tests cover interview logic.")
    except LLMConnectionError as exc:
        detail = str(exc)
        if "RESOURCE_EXHAUSTED" in detail or "429" in detail:
            pytest.skip("Groq quota exhausted.")
        raise
    assert result.assistant_message
    assert not _has_diagnostic_claim(result.assistant_message)
    diabetes = result.information_collected["past_medical_history"]
    assert diabetes["status"] != "explicit" or diabetes["value"] is None
