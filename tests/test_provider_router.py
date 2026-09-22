"""Centralized Groq-primary/Ollama-secondary routing tests."""

from __future__ import annotations

import pytest

from core.llm_provider import (
    FallbackLLMProvider,
    ProviderError,
    ProviderFailureKind,
    ProviderRequest,
    ProviderResponse,
)
from privacy import SafeLLMPayload


class ScriptedProvider:
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


def _request() -> ProviderRequest:
    return ProviderRequest(payload=SafeLLMPayload(safe_text="chest pain", source_type="test"))


def test_groq_success_never_calls_ollama() -> None:
    gemini = ScriptedProvider("groq", ["groq result"])
    ollama = ScriptedProvider("ollama", ["ollama result"])
    router = FallbackLLMProvider(gemini, ollama)
    assert router.generate(_request()).provider == "groq"
    assert len(gemini.requests) == 1 and not ollama.requests
    assert router.last_metadata.final_provider == "groq"


@pytest.mark.parametrize("kind", [ProviderFailureKind.RATE_LIMIT, ProviderFailureKind.TRANSIENT, ProviderFailureKind.TIMEOUT])
def test_supported_groq_failure_uses_exactly_one_ollama_fallback(kind: ProviderFailureKind) -> None:
    gemini = ScriptedProvider("groq", [ProviderError("GROQ_FAILURE", kind)])
    ollama = ScriptedProvider("ollama", ["ollama result"])
    router = FallbackLLMProvider(gemini, ollama)
    request = _request()
    assert router.generate(request).provider == "ollama"
    assert len(gemini.requests) == 1 and len(ollama.requests) == 1
    assert gemini.requests[0] is ollama.requests[0] is request
    assert router.last_metadata.fallback_used is True
    assert router.last_metadata.final_provider == "ollama"


@pytest.mark.parametrize("kind", [ProviderFailureKind.AUTHENTICATION, ProviderFailureKind.SAFETY])
def test_non_fallback_groq_failure_never_calls_ollama(kind: ProviderFailureKind) -> None:
    gemini = ScriptedProvider("groq", [ProviderError("GROQ_REJECTED", kind)])
    ollama = ScriptedProvider("ollama", ["unused"])
    router = FallbackLLMProvider(gemini, ollama)
    with pytest.raises(ProviderError):
        router.generate(_request())
    assert len(gemini.requests) == 1 and not ollama.requests


def test_request_failure_uses_ollama_fallback() -> None:
    gemini = ScriptedProvider(
        "groq",
        [ProviderError("GROQ_REQUEST_FAILED", ProviderFailureKind.REQUEST)],
    )
    ollama = ScriptedProvider("ollama", ["ollama result"])
    router = FallbackLLMProvider(gemini, ollama)
    assert router.generate(_request()).provider == "ollama"
    assert router.last_metadata.fallback_used is True
    assert router.last_metadata.fallback_reason == "request"


def test_fallback_disabled_never_calls_ollama() -> None:
    gemini = ScriptedProvider("groq", [ProviderError("GROQ_RATE_LIMIT", ProviderFailureKind.RATE_LIMIT)])
    ollama = ScriptedProvider("ollama", ["unused"])
    router = FallbackLLMProvider(gemini, ollama, fallback_enabled=False)
    with pytest.raises(ProviderError, match="GROQ_RATE_LIMIT"):
        router.generate(_request())
    assert not ollama.requests


def test_ollama_failure_stops_after_one_attempt_without_loop() -> None:
    gemini = ScriptedProvider("groq", [ProviderError("GROQ_RATE_LIMIT", ProviderFailureKind.RATE_LIMIT)])
    ollama = ScriptedProvider("ollama", [ProviderError("OLLAMA_UNAVAILABLE", ProviderFailureKind.UNAVAILABLE)])
    router = FallbackLLMProvider(gemini, ollama)
    with pytest.raises(ProviderError, match="LLM_FALLBACK_FAILED"):
        router.generate(_request())
    assert len(gemini.requests) == 1 and len(ollama.requests) == 1
