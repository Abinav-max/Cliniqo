"""Foundation tests: config load, client init, optional live Groq call."""

from __future__ import annotations

import pytest
import os
from pydantic import BaseModel

from core.config import Settings, get_settings
from core.exceptions import LLMConnectionError, MissingAPIKeyError
from core.llm_client import LLMClient
from core.prompts import CONNECTION_TEST_PROMPT, SAFETY_SYSTEM_INSTRUCTION


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_settings_load_from_environment(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-not-a-real-key")
    monkeypatch.setenv("GROQ_MODEL", "openai/gpt-oss-20b")
    get_settings.cache_clear()
    settings = Settings()
    assert settings.has_api_key
    assert settings.require_api_key() == "test-not-a-real-key"
    assert settings.groq_model == "openai/gpt-oss-20b"
    assert settings.groq_reasoning_effort == "low"


def test_missing_api_key_fails_clearly(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "")
    get_settings.cache_clear()
    settings = Settings()
    assert settings.has_api_key is False
    with pytest.raises(MissingAPIKeyError, match="GROQ_API_KEY"):
        settings.require_api_key()


def test_llm_client_initializes_when_key_present(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-not-a-real-key")
    get_settings.cache_clear()
    client = LLMClient(Settings())
    assert client is not None


@pytest.mark.skipif(
    not (get_settings().has_api_key and os.getenv("RUN_LIVE_GROQ_TESTS") == "1"),
    reason="Set RUN_LIVE_GROQ_TESTS=1 with GROQ_API_KEY to run the optional live call.",
)
def test_live_text_prompt_when_key_exists() -> None:
    client = LLMClient()
    try:
        reply = client.generate_text(
            CONNECTION_TEST_PROMPT,
            system_instruction=SAFETY_SYSTEM_INSTRUCTION,
            temperature=0.0,
        )
    except LLMConnectionError as exc:
        if "RESOURCE_EXHAUSTED" in str(exc) or "429" in str(exc):
            pytest.skip("Groq quota exhausted; text connectivity already attempted.")
        raise
    assert reply
    assert "OK" in reply.upper()


class _PingSchema(BaseModel):
    status: str


def test_generate_json_validates_schema(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("GROQ_API_KEY", "test-not-a-real-key")
    get_settings.cache_clear()
    client = LLMClient(Settings())

    class _FakeResponse:
        text = '{"status": "ok"}'

    monkeypatch.setattr(client, "_generate", lambda *args, **kwargs: _FakeResponse())
    result = client.generate_json("ping", schema=_PingSchema)
    assert isinstance(result, _PingSchema)
    assert result.status == "ok"
