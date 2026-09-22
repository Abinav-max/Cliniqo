"""Consolidated LLM / NLP / OCR test cases (synthetic data; no quota by default).

The offline members use mock LLMs, the deterministic rule-based NLP baseline,
and the local text/PDF OCR path, so a default pytest run never calls a provider.

Opt-in live members are skipped unless the matching env var is set:
    RUN_LIVE_GROQ_TESTS=1       live Groq structured turn (needs GROQ_API_KEY)
    RUN_LIVE_GEMINI_TESTS=1     live Gemini NLP extraction
    RUN_LIVE_TESSERACT_TESTS=1  real Tesseract image OCR (needs tesseract CLI)
"""

from __future__ import annotations

import json
import os
import shutil
import subprocess
from io import BytesIO
from typing import Any, Optional

import pytest
from pydantic import BaseModel

from agents.interview_agent import (
    FieldUpdate,
    InformationStatus,
    InterviewAgent,
    InterviewLLMResponse,
)
from agents.summary_agent import SummaryAgent
from core.llm_client import LLMClient
from core.schemas import AttentionLevel, ClinicalHistory, HistoryOfPresentIllness, PhysicianSummary
from core.llm_provider import ProviderResponse
from services.nlp_service import BasicNLPService
from services.ocr_service import LocalOCRService, OCRServiceError


class ScriptedLLM:
    """Queue of structured predictions. No network access."""

    def __init__(self, responses: list[Any]) -> None:
        self.prompts: list[str] = []
        self._queue = list(responses)

    def generate_json(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any:
        self.prompts.append(prompt)
        if not self._queue:
            raise AssertionError("ScriptedLLM has no remaining responses.")
        return self._queue.pop(0)


class CapturingGroqProvider:
    """Fake Groq provider that records the privacy-safe payload it received."""

    name = "groq"

    def __init__(self) -> None:
        self.safe_texts: list[str] = []

    def generate(self, request: Any) -> ProviderResponse:
        self.safe_texts.append(request.payload.safe_text or "")
        return ProviderResponse(text='{"assistant_message": "How long does this last?", "next_question_category": "duration", "interview_complete": false, "missing_information": ["duration"], "field_updates": [], "patient_reported_concerns": [], "urgent_symptoms_mentioned": []}', provider="groq")


# ---------------------------------------------------------------------------
# LLM: the interview asks a follow-up question and keeps the conversation
# ---------------------------------------------------------------------------

def test_llm_interview_asks_and_keeps_follow_up() -> None:
    llm = ScriptedLLM([
        InterviewLLMResponse(
            assistant_message="When did the headache start?",
            field_updates=[
                FieldUpdate(category="chief_complaint", value="headache", status=InformationStatus.EXPLICIT)
            ],
            missing_information=["onset"],
            next_question_category="onset",
            interview_complete=False,
        ),
        InterviewLLMResponse(
            assistant_message="How many days ago did the headache begin?",
            field_updates=[
                FieldUpdate(category="onset", value="2 days ago", status=InformationStatus.EXPLICIT)
            ],
            missing_information=[],
            next_question_category=None,
            interview_complete=True,
        ),
    ])
    agent = InterviewAgent(llm=llm)

    first = agent.handle_message("I have a headache")
    assert "start" in first.assistant_message
    assert first.next_question_category == "onset"
    assert agent.state.next_question_category == "onset"

    second = agent.handle_message("Two days ago")
    assert "headache" in second.assistant_message

    roles = [t.role for t in agent.state.conversation_history]
    assert roles == ["patient", "assistant", "patient", "assistant"]
    # The whole Q&A is retained, not just the latest turn.
    assert "I have a headache" in agent.state.conversation_history[0].content
    assert "When did the headache start?" in agent.state.conversation_history[1].content
    assert "Two days ago" in agent.state.conversation_history[2].content


# ---------------------------------------------------------------------------
# LLM: summary overview is clean, non-diagnostic, and carries a disclaimer
# ---------------------------------------------------------------------------

def _chest_history() -> ClinicalHistory:
    return ClinicalHistory(
        session_id="s-smoke-2",
        chief_complaint="chest pain",
        associated_symptoms=["breathlessness"],
        history_of_present_illness=HistoryOfPresentIllness(duration="2 days", severity=7),
    )


def test_llm_summary_overview_clean_and_not_diagnostic() -> None:
    llm = ScriptedLLM([
        {"overview": "Patient reported chest pain with breathlessness for 2 days.", "overall_attention_level": "attention"},
    ])
    result = SummaryAgent(llm).summarize(_chest_history(), None, [])
    assert isinstance(result, PhysicianSummary)
    assert result.overview.startswith("Patient reported")
    assert result.overall_attention_level in {AttentionLevel.ROUTINE, AttentionLevel.ATTENTION, AttentionLevel.URGENT}
    assert "diagnosis:" not in result.overview.lower()


def test_llm_prompt_payload_is_privacy_sanitized() -> None:
    provider = CapturingGroqProvider()
    client = LLMClient(provider=provider)
    schema = InterviewLLMResponse
    model = client.generate_json(
        "Patient name John Peter, phone +91 9876543210, reports crushing chest pain.",
        schema=schema,
        system_instruction="Interview the patient.",
    )
    assert isinstance(model, schema)
    sent = " ".join(provider.safe_texts)
    assert "John Peter" not in sent
    assert "9876543210" not in sent


# ---------------------------------------------------------------------------
# NLP
# ---------------------------------------------------------------------------

def test_nlp_english_rule_based_extraction() -> None:
    result = BasicNLPService().process("I have a headache since 2 days", source="text", language="en")
    assert result.entities["intent"] == "symptom_report"
    assert any("headache" in s.lower() for s in result.entities["symptoms"])
    assert "2 days" in result.entities["duration"]


def test_nlp_hinglish_red_flag_smoke() -> None:
    result = BasicNLPService().process("seene me dard hai", source="text", language="hi")
    joined = " ".join(result.entities.get("red_flags", []))
    assert "Cardiorespiratory" in joined


# ---------------------------------------------------------------------------
# OCR
# ---------------------------------------------------------------------------

def test_ocr_text_document_smoke() -> None:
    result = LocalOCRService().extract(b"Pt reports left knee pain since one week.", "note.txt", "text/plain")
    assert result.raw_text == "Pt reports left knee pain since one week."


def test_ocr_blank_pdf_controlled_error() -> None:
    from pypdf import PdfWriter

    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=72, height=72)
    writer.write(output)
    with pytest.raises(OCRServiceError, match="no extractable text"):
        LocalOCRService().extract(output.getvalue(), "blank.pdf", "application/pdf")


# ---------------------------------------------------------------------------
# Live (opt-in) members
# ---------------------------------------------------------------------------

@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_GROQ_TESTS"),
    reason="set RUN_LIVE_GROQ_TESTS=1 (needs GROQ_API_KEY) to run the live Groq case",
)
def test_live_groq_structured_interview_turn() -> None:
    client = LLMClient()
    result = client.generate_json(
        "The patient said: 'I have a fever since yesterday.' Return the next interview turn.",
        schema=InterviewLLMResponse,
        system_instruction="You are a medical history interviewer. Never diagnose.",
    )
    assert isinstance(result, InterviewLLMResponse)
    assert result.assistant_message
    assert client.provider_metadata["final_provider"] in {"groq", "ollama"}


@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_GEMINI_TESTS"),
    reason="set RUN_LIVE_GEMINI_TESTS=1 (needs GEMINI_API_KEY) to run the live Gemini NLP case",
)
def test_live_gemini_nlp_extraction() -> None:
    from services.nlp_service import PatientNLPService

    result = PatientNLPService().process("I have a fever and a headache", source="text", language="en")
    entities = result.entities
    assert entities.get("success") is not False
    assert any("fever" in s.lower() for s in entities.get("symptoms", [])) or any(
        "fever" in s.lower() for s in entities.get("diseases", [])
    )


@pytest.mark.skipif(
    not os.getenv("RUN_LIVE_TESSERACT_TESTS"),
    reason="set RUN_LIVE_TESSERACT_TESTS=1 (needs tesseract CLI) to run the live image OCR case",
)
def test_live_tesseract_image_ocr() -> None:
    if shutil.which("tesseract") is None:
        pytest.skip("tesseract CLI not on PATH")
    from PIL import Image, ImageDraw

    output = BytesIO()
    img = Image.new("RGB", (300, 60), "white")
    draw = ImageDraw.Draw(img)
    draw.text((10, 10), "Chest pain since morning", fill="black")
    img.save(output, format="PNG")

    result = LocalOCRService().extract(output.getvalue(), "note.png", "image/png")
    assert "chest pain" in result.raw_text.lower()