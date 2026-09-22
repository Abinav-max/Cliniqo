"""Provider-independent, privacy-safe LLM transport and fallback routing.

Providers receive :class:`privacy.SafeLLMPayload`, never raw application text.
The caller owns privacy transformation and response validation; this module owns
only the provider request, classified failures, and one-way fallback routing.
"""

from __future__ import annotations

from copy import deepcopy
import json
import socket
from dataclasses import dataclass
from enum import Enum
from typing import Any, Optional, Protocol
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen

from groq import Groq
from pydantic import BaseModel

from core.config import Settings
from privacy import SafeLLMPayload


class ProviderFailureKind(str, Enum):
    RATE_LIMIT = "rate_limit"
    TRANSIENT = "transient"
    TIMEOUT = "timeout"
    AUTHENTICATION = "authentication"
    SAFETY = "safety"
    REQUEST = "request"
    UNAVAILABLE = "unavailable"


_FALLBACK_ELIGIBLE = {
    ProviderFailureKind.RATE_LIMIT,
    ProviderFailureKind.TRANSIENT,
    ProviderFailureKind.TIMEOUT,
    ProviderFailureKind.UNAVAILABLE,
    # A valid key can still encounter a provider-side request failure, such
    # as an unavailable model. Local Ollama should remain an operational
    # fallback for those failures.
    ProviderFailureKind.REQUEST,
}


class ProviderError(Exception):
    """A safe, classified provider failure with no request/response content."""

    def __init__(self, code: str, kind: ProviderFailureKind) -> None:
        super().__init__(code)
        self.code = code
        self.kind = kind

    @property
    def fallback_eligible(self) -> bool:
        return self.kind in _FALLBACK_ELIGIBLE


@dataclass(frozen=True)
class ProviderRequest:
    """One outbound request whose content has already passed PrivacyGateway."""

    payload: SafeLLMPayload
    system_instruction: Optional[str] = None
    temperature: Optional[float] = None
    response_mime_type: Optional[str] = None
    response_schema: Optional[type[Any]] = None


@dataclass(frozen=True)
class ProviderResponse:
    text: str
    provider: str


@dataclass(frozen=True)
class ProviderMetadata:
    primary_provider: str = "groq"
    fallback_used: bool = False
    final_provider: str = "groq"
    fallback_reason: Optional[str] = None

    def as_dict(self) -> dict[str, Any]:
        return {
            "primary_provider": self.primary_provider,
            "fallback_used": self.fallback_used,
            "final_provider": self.final_provider,
            "fallback_reason": self.fallback_reason,
        }


class LLMProvider(Protocol):
    """Transport-only provider contract used by the shared LLM client."""

    name: str

    def generate(self, request: ProviderRequest) -> ProviderResponse: ...


def _status_code(error: BaseException) -> Optional[int]:
    """Read structured SDK/HTTP status data before using a text fallback."""
    for attribute in ("status_code", "code", "status"):
        value = getattr(error, attribute, None)
        if callable(value):
            try:
                value = value()
            except Exception:  # no raw error handling or logging here
                continue
        if isinstance(value, int):
            return value
        if isinstance(value, str) and value.isdigit():
            return int(value)
    return None


def classify_provider_error(error: BaseException, *, provider: str) -> ProviderError:
    """Classify a provider error using status metadata, then bounded text clues."""
    status = _status_code(error)
    if status == 429:
        return ProviderError(f"{provider.upper()}_RATE_LIMIT", ProviderFailureKind.RATE_LIMIT)
    if status in {408, 504}:
        return ProviderError(f"{provider.upper()}_TIMEOUT", ProviderFailureKind.TIMEOUT)
    if status in {500, 502, 503}:
        return ProviderError(f"{provider.upper()}_TRANSIENT_FAILURE", ProviderFailureKind.TRANSIENT)
    if status in {401, 403}:
        return ProviderError(f"{provider.upper()}_AUTHENTICATION_FAILED", ProviderFailureKind.AUTHENTICATION)
    if status is not None and 400 <= status < 500:
        return ProviderError(f"{provider.upper()}_REQUEST_REJECTED", ProviderFailureKind.REQUEST)

    if isinstance(error, (TimeoutError, socket.timeout)):
        return ProviderError(f"{provider.upper()}_TIMEOUT", ProviderFailureKind.TIMEOUT)
    # Providers may expose transport errors without inheriting Python's
    # ConnectionError. Recognize this family by name: no provider received a
    # usable response, so a local fallback is appropriate.
    error_type = error.__class__.__name__
    if error_type in {"ConnectError", "NetworkError", "TransportError"}:
        return ProviderError(f"{provider.upper()}_UNAVAILABLE", ProviderFailureKind.UNAVAILABLE)
    # SDKs do not consistently expose HTTP status for every transport failure.
    # These cues are consulted only after structured fields above.
    detail = str(error).lower()
    if any(term in detail for term in ("rate limit", "quota", "resource_exhausted", "too many requests")):
        return ProviderError(f"{provider.upper()}_RATE_LIMIT", ProviderFailureKind.RATE_LIMIT)
    if any(term in detail for term in ("timed out", "timeout")):
        return ProviderError(f"{provider.upper()}_TIMEOUT", ProviderFailureKind.TIMEOUT)
    if any(term in detail for term in ("safety", "blocked", "policy")):
        return ProviderError(f"{provider.upper()}_SAFETY_REJECTED", ProviderFailureKind.SAFETY)
    if any(term in detail for term in ("invalid api key", "authentication", "unauthenticated", "permission denied")):
        return ProviderError(f"{provider.upper()}_AUTHENTICATION_FAILED", ProviderFailureKind.AUTHENTICATION)
    if isinstance(error, URLError) or any(
        term in detail for term in ("nodename nor servname", "connection refused", "name or service not known")
    ):
        return ProviderError(f"{provider.upper()}_UNAVAILABLE", ProviderFailureKind.UNAVAILABLE)
    return ProviderError(f"{provider.upper()}_REQUEST_FAILED", ProviderFailureKind.REQUEST)


def _groq_strict_response_schema(schema: type[Any]) -> dict[str, Any]:
    """Make a Pydantic schema conform to Groq strict-output requirements.

    Groq strict schemas require every object property to be required and every
    object to forbid extra properties. Optional Pydantic fields already accept
    ``null`` in their generated schema. Dynamic maps cannot be represented in
    this strict subset, so providers are instructed to emit them as empty
    objects; application code reconstructs deterministic provenance from the
    validated upstream record instead of trusting provider-generated map data.
    """
    if not isinstance(schema, type) or not issubclass(schema, BaseModel):
        raise TypeError("Groq strict output requires a Pydantic response schema.")

    def normalize(value: Any) -> Any:
        if isinstance(value, list):
            return [normalize(item) for item in value]
        if not isinstance(value, dict):
            return value
        result = {key: normalize(item) for key, item in value.items()}
        if result.get("type") == "object" or "properties" in result:
            properties = result.get("properties", {})
            if properties:
                result["required"] = list(properties)
            # Dynamic map values (for example source_evidence) are deliberately
            # empty at the provider boundary under strict mode.
            result["additionalProperties"] = False
        return result

    return normalize(deepcopy(schema.model_json_schema()))


class GroqProvider:
    """Groq SDK transport, gated by ``SafeLLMPayload``.

    The official SDK owns its authenticated transport setup. This avoids subtle
    differences in hand-built HTTP headers/proxy handling while preserving this
    module's provider-neutral request and classified-error interfaces.
    """

    name = "groq"

    def __init__(self, settings: Settings, *, client: Any = None) -> None:
        self._api_key = settings.require_api_key()
        self._model = settings.groq_model
        self._reasoning_effort = settings.groq_reasoning_effort
        self._timeout_seconds = settings.llm_timeout_seconds
        self._default_temperature = settings.llm_temperature
        # ``max_retries=0`` preserves application-level routing semantics: one
        # Groq attempt, then at most one eligible Ollama fallback attempt.
        self._client = client or Groq(
            api_key=self._api_key,
            timeout=self._timeout_seconds,
            max_retries=0,
        )

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not isinstance(request.payload, SafeLLMPayload):
            raise ProviderError("PRIVACY_PAYLOAD_REQUIRED", ProviderFailureKind.REQUEST)
        messages: list[dict[str, str]] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": request.system_instruction})
        messages.append({"role": "user", "content": request.payload.safe_text})
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "temperature": self._default_temperature if request.temperature is None else request.temperature,
            "reasoning_effort": self._reasoning_effort,
        }
        if request.response_schema is not None:
            body["response_format"] = {
                "type": "json_schema",
                "json_schema": {
                    "name": request.response_schema.__name__.lower(),
                    "strict": True,
                    "schema": _groq_strict_response_schema(request.response_schema),
                },
            }
        elif request.response_mime_type == "application/json":
            body["response_format"] = {"type": "json_object"}
        try:
            response = self._client.chat.completions.create(**body)
            text = response.choices[0].message.content
            if not isinstance(text, str):
                raise ProviderError("GROQ_INVALID_RESPONSE", ProviderFailureKind.REQUEST)
        except ProviderError:
            raise
        except (IndexError, TypeError, ValueError) as exc:
            raise ProviderError("GROQ_INVALID_RESPONSE", ProviderFailureKind.REQUEST) from exc
        except Exception as exc:
            raise classify_provider_error(exc, provider=self.name) from exc
        return ProviderResponse(text=text, provider=self.name)


class OllamaProvider:
    """Local Ollama chat transport. It never receives Groq credentials."""

    name = "ollama"

    def __init__(self, settings: Settings, *, opener: Any = urlopen) -> None:
        self._base_url = self._validate_local_base_url(settings.ollama_base_url)
        self._model = settings.ollama_model
        self._timeout_seconds = settings.ollama_timeout_seconds
        self._opener = opener

    @staticmethod
    def _validate_local_base_url(value: str) -> str:
        parsed = urlparse(value)
        if (
            parsed.scheme != "http"
            or parsed.hostname not in {"localhost", "127.0.0.1"}
            or parsed.username
            or parsed.password
            or parsed.path not in {"", "/"}
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError("OLLAMA_BASE_URL must be a local http://localhost or 127.0.0.1 URL.")
        return value.rstrip("/")

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not isinstance(request.payload, SafeLLMPayload):
            raise ProviderError("PRIVACY_PAYLOAD_REQUIRED", ProviderFailureKind.REQUEST)
        messages: list[dict[str, str]] = []
        if request.system_instruction:
            messages.append({"role": "system", "content": request.system_instruction})
        messages.append({"role": "user", "content": request.payload.safe_text})
        body: dict[str, Any] = {
            "model": self._model,
            "messages": messages,
            "stream": False,
            "options": {"temperature": request.temperature},
        }
        if request.response_schema is not None:
            if isinstance(request.response_schema, type) and issubclass(request.response_schema, BaseModel):
                body["format"] = request.response_schema.model_json_schema()
            elif isinstance(request.response_schema, dict):
                body["format"] = request.response_schema
            elif request.response_mime_type == "application/json":
                body["format"] = "json"
        elif request.response_mime_type == "application/json":
            body["format"] = "json"
        request_object = Request(
            f"{self._base_url}/api/chat",
            data=json.dumps(body).encode("utf-8"),
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            with self._opener(request_object, timeout=self._timeout_seconds) as response:
                raw = response.read().decode("utf-8")
            payload = json.loads(raw)
            text = payload.get("message", {}).get("content")
            if not isinstance(text, str):
                raise ProviderError("OLLAMA_INVALID_RESPONSE", ProviderFailureKind.REQUEST)
        except ProviderError:
            raise
        except HTTPError as exc:
            raise classify_provider_error(exc, provider=self.name) from exc
        except (URLError, TimeoutError, socket.timeout) as exc:
            raise classify_provider_error(exc, provider=self.name) from exc
        except (UnicodeDecodeError, json.JSONDecodeError, KeyError, TypeError, ValueError) as exc:
            raise ProviderError("OLLAMA_INVALID_RESPONSE", ProviderFailureKind.REQUEST) from exc
        return ProviderResponse(text=text, provider=self.name)


class FallbackLLMProvider:
    """Groq-first router with at most one eligible Ollama fallback attempt."""

    def __init__(
        self,
        primary: LLMProvider,
        fallback: Optional[LLMProvider] = None,
        *,
        fallback_enabled: bool = True,
    ) -> None:
        if primary.name != "groq":
            raise ValueError("Groq must remain the primary provider.")
        if fallback is not None and fallback.name != "ollama":
            raise ValueError("Ollama must remain the secondary provider.")
        self._primary = primary
        self._fallback = fallback
        self._fallback_enabled = fallback_enabled
        self.last_metadata = ProviderMetadata()

    def generate(self, request: ProviderRequest) -> ProviderResponse:
        if not isinstance(request.payload, SafeLLMPayload):
            raise ProviderError("PRIVACY_PAYLOAD_REQUIRED", ProviderFailureKind.REQUEST)
        try:
            response = self._primary.generate(request)
        except ProviderError as primary_error:
            self.last_metadata = ProviderMetadata(
                primary_provider=self._primary.name,
                fallback_used=False,
                final_provider=self._primary.name,
                fallback_reason=primary_error.kind.value,
            )
            if not (
                self._fallback_enabled
                and self._fallback is not None
                and primary_error.fallback_eligible
            ):
                raise
            try:
                # Reuse this exact safe request. No raw record is reconstructed.
                response = self._fallback.generate(request)
            except ProviderError as fallback_error:
                self.last_metadata = ProviderMetadata(
                    primary_provider=self._primary.name,
                    fallback_used=True,
                    final_provider=self._fallback.name,
                    fallback_reason=primary_error.kind.value,
                )
                raise ProviderError("LLM_FALLBACK_FAILED", fallback_error.kind) from fallback_error
            self.last_metadata = ProviderMetadata(
                primary_provider=self._primary.name,
                fallback_used=True,
                final_provider=self._fallback.name,
                fallback_reason=primary_error.kind.value,
            )
            return response
        self.last_metadata = ProviderMetadata(
            primary_provider=self._primary.name,
            fallback_used=False,
            final_provider=self._primary.name,
        )
        return response
