"""Provider-independent validation tests for the shared LLM facade."""

from __future__ import annotations

from typing import Any

import pytest
from pydantic import BaseModel

from core.config import Settings
from core.exceptions import LLMConnectionError, StructuredOutputError
from core.llm_client import LLMClient
from core.llm_provider import ProviderError, ProviderFailureKind, ProviderRequest, ProviderResponse
from privacy import SafeLLMPayload


class TextProvider:
    name = "groq"

    def __init__(self, text: str) -> None:
        self.text = text
        self.requests: list[ProviderRequest] = []

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        self.requests.append(request)
        return ProviderResponse(self.text, self.name)


class Status(BaseModel):
    status: str


def test_shared_client_validates_json_for_any_provider() -> None:
    provider = TextProvider('{"status": "ok"}')
    client = LLMClient(Settings(groq_api_key="test-not-a-real-key"), provider=provider)
    assert client.generate_json("chest pain", schema=Status) == Status(status="ok")
    assert provider.requests[0].response_schema is Status


def test_shared_client_rejects_invalid_provider_json() -> None:
    client = LLMClient(Settings(groq_api_key="test-not-a-real-key"), provider=TextProvider("{bad"))
    with pytest.raises(StructuredOutputError):
        client.generate_json("chest pain", schema=Status)


def test_shared_client_exposes_only_safe_provider_failure_code() -> None:
    class FailingProvider:
        name = "groq"

        def generate(self, _: ProviderRequest) -> ProviderResponse:
            raise ProviderError("GROQ_AUTHENTICATION_FAILED", ProviderFailureKind.AUTHENTICATION)

    client = LLMClient(Settings(groq_api_key="test-not-a-real-key"), provider=FailingProvider())
    with pytest.raises(LLMConnectionError, match="GROQ_AUTHENTICATION_FAILED"):
        client.generate_text("Name: TEST_PERSON_123; chest pain")


def test_provider_request_requires_safe_payload() -> None:
    safe = SafeLLMPayload(safe_text="chest pain", source_type="test")
    assert ProviderRequest(payload=safe).payload.safe_text == "chest pain"
