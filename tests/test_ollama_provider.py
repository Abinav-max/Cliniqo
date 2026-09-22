"""Mocked local Ollama chat transport tests."""

from __future__ import annotations

import io
import json
import os
from urllib.error import URLError

import pytest
from pydantic import BaseModel

from core.config import Settings
from core.llm_provider import OllamaProvider, ProviderError, ProviderFailureKind, ProviderRequest
from privacy import SafeLLMPayload


class FakeResponse:
    def __init__(self, payload: object) -> None:
        self._payload = payload

    def read(self) -> bytes:
        return json.dumps(self._payload).encode("utf-8")

    def __enter__(self) -> "FakeResponse":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _request() -> ProviderRequest:
    return ProviderRequest(
        payload=SafeLLMPayload(safe_text="chest pain for two days", source_type="test"),
        system_instruction="Do not diagnose.",
        response_mime_type="application/json",
    )


class _StructuredStatus(BaseModel):
    status: str


def test_ollama_provider_posts_local_chat_payload_without_groq_key() -> None:
    captured = []

    def opener(request: object, **_: object) -> FakeResponse:
        captured.append(request)
        return FakeResponse({"message": {"content": '{"status": "ok"}'}})

    provider = OllamaProvider(Settings(groq_api_key="test-not-a-real-key"), opener=opener)
    assert provider.generate(_request()).text == '{"status": "ok"}'
    body = json.loads(captured[0].data.decode("utf-8"))
    assert body["model"] == "gemma3:12b"
    assert body["messages"][-1]["content"] == "chest pain for two days"
    assert "test-not-a-real-key" not in json.dumps(body)


def test_ollama_provider_accepts_pydantic_schema_on_structured_fallback_path() -> None:
    captured = []

    def opener(request: object, **_: object) -> FakeResponse:
        captured.append(request)
        return FakeResponse({"message": {"content": '{"status": "ok"}'}})

    provider = OllamaProvider(Settings(groq_api_key="test-not-a-real-key"), opener=opener)
    request = ProviderRequest(
        payload=SafeLLMPayload(safe_text="synthetic", source_type="test"),
        response_mime_type="application/json",
        response_schema=_StructuredStatus,
    )
    assert provider.generate(request).text == '{"status": "ok"}'
    body = json.loads(captured[0].data.decode("utf-8"))
    assert isinstance(body["format"], dict)


def test_ollama_provider_unavailable_is_structured() -> None:
    def unavailable(*_: object, **__: object) -> object:
        raise URLError("connection refused")

    provider = OllamaProvider(Settings(groq_api_key="test-not-a-real-key"), opener=unavailable)
    with pytest.raises(ProviderError) as captured:
        provider.generate(_request())
    assert captured.value.kind is ProviderFailureKind.UNAVAILABLE


@pytest.mark.parametrize("url", ["https://remote.example", "http://10.0.0.1:11434", "http://localhost:11434/path"])
def test_ollama_provider_rejects_nonlocal_or_path_urls(url: str) -> None:
    with pytest.raises(ValueError):
        OllamaProvider(Settings(groq_api_key="test-not-a-real-key", ollama_base_url=url))


@pytest.mark.skipif(os.getenv("RUN_LIVE_OLLAMA_TESTS") != "1", reason="Set RUN_LIVE_OLLAMA_TESTS=1 to use local Ollama.")
def test_optional_live_ollama_chat_uses_synthetic_prompt() -> None:
    provider = OllamaProvider(Settings())
    try:
        result = provider.generate(ProviderRequest(payload=SafeLLMPayload(safe_text="Reply with OK. Synthetic test only.", source_type="live_test")))
    except ProviderError as exc:
        pytest.skip(f"Local Ollama unavailable: {exc.code}")
    assert result.text
