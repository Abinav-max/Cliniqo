"""Fallback tests that prove both providers receive only Phase 8 safe payloads."""

from __future__ import annotations

from typing import Any

import pytest

from agents.risk_agent import RiskAgent
from agents.structuring_agent import StructuringAgent
from core.config import Settings
from core.exceptions import LLMConnectionError, StructuredOutputError
from core.llm_client import LLMClient
from core.llm_provider import (
    FallbackLLMProvider,
    ProviderError,
    ProviderFailureKind,
    ProviderRequest,
    ProviderResponse,
)
from core.schemas import ClinicalHistory
from privacy import PrivacyGatewayError


class CaptureProvider:
    def __init__(self, name: str, outcomes: list[object]) -> None:
        self.name = name
        self.outcomes = list(outcomes)
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, BaseException):
            raise outcome
        return ProviderResponse(str(outcome), self.name)


def test_fallback_reuses_deidentified_payload_for_ollama() -> None:
    gemini = CaptureProvider("groq", [ProviderError("GROQ_RATE_LIMIT", ProviderFailureKind.RATE_LIMIT)])
    ollama = CaptureProvider("ollama", ["OK"])
    client = LLMClient(
        Settings(groq_api_key="test-not-a-real-key"),
        provider=FallbackLLMProvider(gemini, ollama),
    )
    assert client.generate_text("Name: TEST_PERSON_123; Phone: 9999999999; MRN: TEST_MRN_123; chest pain for two days.") == "OK"
    safe = ollama.requests[0].payload.safe_text
    for identifier in ("TEST_PERSON_123", "9999999999", "TEST_MRN_123"):
        assert identifier not in safe
    assert "chest pain for two days" in safe.lower()
    assert client.provider_metadata["fallback_used"] is True
    assert client.provider_metadata["final_provider"] == "ollama"


def test_privacy_gateway_failure_prevents_both_provider_attempts() -> None:
    class BrokenGateway:
        def prepare(self, *_: Any, **__: Any) -> Any:
            raise PrivacyGatewayError("raw patient data")

    gemini = CaptureProvider("groq", ["unused"])
    ollama = CaptureProvider("ollama", ["unused"])
    client = LLMClient(
        Settings(groq_api_key="test-not-a-real-key"),
        privacy_gateway=BrokenGateway(),
        provider=FallbackLLMProvider(gemini, ollama),
    )
    with pytest.raises(LLMConnectionError, match="PRIVACY_GATEWAY_BLOCKED"):
        client.generate_text("Name: TEST_PERSON_123; chest pain")
    assert not gemini.requests and not ollama.requests


def test_invalid_fallback_json_still_uses_bounded_agent_repair() -> None:
    gemini = CaptureProvider("groq", [
        ProviderError("GROQ_RATE_LIMIT", ProviderFailureKind.RATE_LIMIT),
        ProviderError("GROQ_RATE_LIMIT", ProviderFailureKind.RATE_LIMIT),
    ])
    ollama = CaptureProvider("ollama", ["{bad json", "{still bad"])
    client = LLMClient(Settings(groq_api_key="test-not-a-real-key"), provider=FallbackLLMProvider(gemini, ollama))
    with pytest.raises(StructuredOutputError):
        StructuringAgent(client).structure("Name: TEST_PERSON_123\nI have chest pain.")
    assert len(gemini.requests) == 2 and len(ollama.requests) == 2
    assert all("TEST_PERSON_123" not in request.payload.safe_text for request in ollama.requests)


def test_urgent_deterministic_risk_survives_ollama_fallback() -> None:
    gemini = CaptureProvider("groq", [ProviderError("GROQ_RATE_LIMIT", ProviderFailureKind.RATE_LIMIT)])
    ollama = CaptureProvider("ollama", ["{}"])
    client = LLMClient(Settings(groq_api_key="test-not-a-real-key"), provider=FallbackLLMProvider(gemini, ollama))
    risk = RiskAgent(client).assess(ClinicalHistory(chief_complaint="chest pain", associated_symptoms=["breathlessness"]))
    assert risk.overall_attention_level.value == "urgent"
    assert risk.risk_flags
