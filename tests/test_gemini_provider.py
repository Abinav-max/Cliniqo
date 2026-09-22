"""Mocked Groq transport classification tests; no live calls are used."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from core.config import Settings
from core.llm_provider import (
    GroqProvider,
    ProviderError,
    ProviderFailureKind,
    ProviderRequest,
    _groq_strict_response_schema,
)
from core.schemas import PhysicianSummary
from privacy import SafeLLMPayload


class FakeGroqClient:
    def __init__(self, result: object) -> None:
        self.result = result
        self.calls: list[dict[str, object]] = []
        self.chat = SimpleNamespace(completions=self)

    def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        if isinstance(self.result, BaseException):
            raise self.result
        return self.result


class StatusError(Exception):
    def __init__(self, status_code: int, detail: str = "provider error") -> None:
        self.status_code = status_code
        super().__init__(detail)


def _request() -> ProviderRequest:
    return ProviderRequest(payload=SafeLLMPayload(safe_text="chest pain", source_type="test"))


def test_groq_provider_uses_sdk_with_safe_payload_and_never_serializes_key() -> None:
    client = FakeGroqClient(SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]))
    provider = GroqProvider(Settings(groq_api_key="test-not-a-real-key"), client=client)
    assert provider.generate(_request()).text == "OK"
    body = client.calls[0]
    assert body["messages"][-1]["content"] == "chest pain"
    assert body["model"] == "openai/gpt-oss-120b"
    assert body["reasoning_effort"] == "low"
    assert "test-not-a-real-key" not in repr(body)


def test_groq_provider_classifies_transport_connection_as_unavailable() -> None:
    class APIConnectionError(Exception):
        pass

    provider = GroqProvider(
        Settings(groq_api_key="test-not-a-real-key"),
        client=FakeGroqClient(APIConnectionError("connection refused")),
    )
    with pytest.raises(ProviderError) as captured:
        provider.generate(_request())
    assert captured.value.kind is ProviderFailureKind.UNAVAILABLE


@pytest.mark.parametrize(
    "status,kind,code",
    [
        (429, ProviderFailureKind.RATE_LIMIT, "GEMINI_RATE_LIMIT"),
        (500, ProviderFailureKind.TRANSIENT, "GEMINI_TRANSIENT_FAILURE"),
        (503, ProviderFailureKind.TRANSIENT, "GEMINI_TRANSIENT_FAILURE"),
        (401, ProviderFailureKind.AUTHENTICATION, "GEMINI_AUTHENTICATION_FAILED"),
    ],
)
def test_groq_provider_classifies_structured_status(
    status: int, kind: ProviderFailureKind, code: str
) -> None:
    provider = GroqProvider(
        Settings(groq_api_key="test-not-a-real-key"),
        client=FakeGroqClient(StatusError(status)),
    )
    with pytest.raises(ProviderError) as captured:
        provider.generate(_request())
    assert captured.value.kind is kind
    assert captured.value.code == code.replace("GEMINI", "GROQ")


def test_groq_authentication_error_is_safe_and_is_not_reclassified_from_secret_text() -> None:
    secret = "test-not-a-real-key"
    provider = GroqProvider(
        Settings(groq_api_key=secret),
        client=FakeGroqClient(StatusError(401, f"authorization failed for {secret}")),
    )
    with pytest.raises(ProviderError) as captured:
        provider.generate(_request())
    assert captured.value.code == "GROQ_AUTHENTICATION_FAILED"
    assert captured.value.kind is ProviderFailureKind.AUTHENTICATION
    assert secret not in str(captured.value)


def test_valid_groq_configuration_initializes_sdk_provider_without_authentication_failure() -> None:
    client = FakeGroqClient(SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="OK"))]))
    provider = GroqProvider(Settings(groq_api_key="test-not-a-real-key"), client=client)
    response = provider.generate(_request())
    assert response.provider == "groq"


def test_groq_strict_schema_makes_all_fields_required_and_blocks_dynamic_map_values() -> None:
    schema = _groq_strict_response_schema(PhysicianSummary)
    assert set(schema["required"]) == set(schema["properties"])
    assert schema["additionalProperties"] is False
    source_evidence = schema["properties"]["source_evidence"]
    assert source_evidence["additionalProperties"] is False


def test_groq_api_key_strips_surrounding_quotes_and_whitespace(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", '  "gsk_test_key_12345"  ')
    settings = Settings()
    assert settings.require_api_key() == "gsk_test_key_12345"


def test_groq_provider_does_not_misclassify_bad_request_as_authentication_failed() -> None:
    provider = GroqProvider(
        Settings(groq_api_key="gsk_valid_key"),
        client=FakeGroqClient(StatusError(400, "bad request schema")),
    )
    with pytest.raises(ProviderError) as captured:
        provider.generate(_request())
    assert captured.value.kind is ProviderFailureKind.REQUEST
    assert captured.value.code == "GROQ_REQUEST_REJECTED"
    assert captured.value.fallback_eligible is True


def test_groq_authentication_failure_is_not_fallback_eligible() -> None:
    provider = GroqProvider(
        Settings(groq_api_key="gsk_invalid_key"),
        client=FakeGroqClient(StatusError(401, "unauthorized")),
    )
    with pytest.raises(ProviderError) as captured:
        provider.generate(_request())
    assert captured.value.kind is ProviderFailureKind.AUTHENTICATION
    assert captured.value.code == "GROQ_AUTHENTICATION_FAILED"
    assert captured.value.fallback_eligible is False
    assert "gsk_invalid_key" not in str(captured.value)

