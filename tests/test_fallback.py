"""Client-level fallback switch and safe metadata tests."""

from __future__ import annotations

import pytest

from agents.document_agent import DocumentAgent
from agents.interview_agent import InterviewAgent
from agents.risk_agent import RiskAgent
from agents.structuring_agent import StructuringAgent
from agents.summary_agent import SummaryAgent
from core.config import Settings
from core.exceptions import LLMConnectionError
from core.llm_client import LLMClient
from core.llm_provider import FallbackLLMProvider, ProviderError, ProviderFailureKind, ProviderRequest, ProviderResponse
from core.orchestrator import MedicalOrchestrator


class FailingGemini:
    name = "groq"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, _: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        raise ProviderError("GROQ_RATE_LIMIT", ProviderFailureKind.RATE_LIMIT)


class OllamaSpy:
    name = "ollama"

    def __init__(self) -> None:
        self.calls = 0

    def generate(self, _: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        return ProviderResponse("fallback response", self.name)


class QueueProvider:
    def __init__(self, name: str, outcomes: list[object]) -> None:
        self.name = name
        self.outcomes = list(outcomes)
        self.calls = 0

    def generate(self, _: ProviderRequest) -> ProviderResponse:
        self.calls += 1
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return ProviderResponse(str(outcome), self.name)


def _pipeline_outcomes() -> list[str]:
    return [
        '{"assistant_message": "When did it start?"}',
        '{"chief_complaint": "chest pain", "associated_symptoms": ["breathlessness"], "source_evidence": {"chief_complaint": "I have chest pain and breathlessness.", "associated_symptoms": "I have chest pain and breathlessness."}}',
        "{}",
        '{"medications": [{"name_as_reported": "Metformin", "dose_as_reported": "500 mg", "source_text": "Metformin 500 mg"}]}',
        '{"fact_ids": ["clinical_history.0"]}',
    ]


def _orchestrator(client: LLMClient) -> MedicalOrchestrator:
    return MedicalOrchestrator(
        interview_agent=InterviewAgent(client),
        structuring_agent=StructuringAgent(client),
        risk_agent=RiskAgent(client),
        document_agent=DocumentAgent(client),
        summary_agent=SummaryAgent(client),
    )


def test_client_fallback_disabled_returns_primary_failure_without_ollama() -> None:
    gemini, ollama = FailingGemini(), OllamaSpy()
    client = LLMClient(
        Settings(groq_api_key="test-not-a-real-key", llm_fallback_enabled=False),
        provider=FallbackLLMProvider(gemini, ollama, fallback_enabled=False),
    )
    with pytest.raises(LLMConnectionError, match="GROQ_RATE_LIMIT"):
        client.generate_text("chest pain")
    assert gemini.calls == 1 and ollama.calls == 0
    assert client.provider_metadata["fallback_used"] is False


def test_client_records_safe_fallback_metadata() -> None:
    gemini, ollama = FailingGemini(), OllamaSpy()
    client = LLMClient(
        Settings(groq_api_key="test-not-a-real-key"),
        provider=FallbackLLMProvider(gemini, ollama),
    )
    assert client.generate_text("chest pain") == "fallback response"
    assert client.provider_metadata == {
        "primary_provider": "groq",
        "fallback_used": True,
        "final_provider": "ollama",
        "fallback_reason": "rate_limit",
    }


def test_complete_pipeline_uses_gemini_when_primary_succeeds() -> None:
    gemini = QueueProvider("groq", _pipeline_outcomes())
    ollama = QueueProvider("ollama", [])
    client = LLMClient(Settings(groq_api_key="test-not-a-real-key"), provider=FallbackLLMProvider(gemini, ollama))
    state = _orchestrator(client).handle_patient_message(
        "I have chest pain and breathlessness.",
        documents=[{"document_id": "d1", "ocr_text": "Metformin 500 mg"}],
    )
    assert state.physician_summary is not None
    assert state.risk_assessment.overall_attention_level.value == "urgent"
    assert gemini.calls == 5 and ollama.calls == 0


def test_complete_pipeline_continues_after_one_risk_fallback() -> None:
    outcomes = _pipeline_outcomes()
    gemini = QueueProvider("groq", [outcomes[0], outcomes[1], ProviderError("GROQ_RATE_LIMIT", ProviderFailureKind.RATE_LIMIT), outcomes[3], outcomes[4]])
    ollama = QueueProvider("ollama", [outcomes[2]])
    client = LLMClient(Settings(groq_api_key="test-not-a-real-key"), provider=FallbackLLMProvider(gemini, ollama))
    state = _orchestrator(client).handle_patient_message(
        "I have chest pain and breathlessness.",
        documents=[{"document_id": "d1", "ocr_text": "Metformin 500 mg"}],
    )
    assert state.physician_summary is not None
    assert state.risk_assessment.overall_attention_level.value == "urgent"
    assert gemini.calls == 5 and ollama.calls == 1
