"""Privacy-gated LLM client. Secrets stay in the environment, never in logs."""

from __future__ import annotations

import json
import logging
from typing import Any, Optional, TypeVar, Union, overload

from pydantic import BaseModel, ValidationError

from core.config import Settings, get_settings
from core.exceptions import (
    LLMConnectionError,
    LLMResponseError,
    StructuredOutputError,
)
from core.llm_provider import (
    FallbackLLMProvider,
    GroqProvider,
    LLMProvider,
    OllamaProvider,
    ProviderError,
    ProviderMetadata,
    ProviderRequest,
    ProviderResponse,
)
from privacy import PrivacyGateway, PrivacyGatewayError, SafeLLMPayload

logger = logging.getLogger(__name__)

TModel = TypeVar("TModel", bound=BaseModel)


class LLMClient:
    """Privacy-gated provider-independent LLM facade.

    Groq remains primary. The fallback controller may send the same approved
    payload to local Ollama only after a classified Groq quota/transient
    failure. JSON parsing and Pydantic validation remain here for both models.
    """

    def __init__(
        self,
        settings: Optional[Settings] = None,
        *,
        privacy_gateway: Optional[PrivacyGateway] = None,
        provider: Optional[LLMProvider] = None,
    ) -> None:
        self._settings = settings or get_settings()
        if provider is None:
            primary = GroqProvider(self._settings)
            fallback = OllamaProvider(self._settings) if self._settings.llm_fallback_enabled else None
            provider = FallbackLLMProvider(
                primary,
                fallback,
                fallback_enabled=self._settings.llm_fallback_enabled,
            )
        self._provider = provider
        self._last_provider_metadata = ProviderMetadata(
            primary_provider="groq",
            fallback_used=False,
            final_provider="groq",
        )
        # This is the last application-side boundary before the external SDK.
        # Agents also gate their prompts so injected test doubles receive safe
        # text, but no production caller can bypass this final check.
        self._privacy_gateway = privacy_gateway or PrivacyGateway()

    @property
    def provider_metadata(self) -> dict[str, Any]:
        """Safe routing metadata for the most recent provider request."""
        return self._last_provider_metadata.as_dict()

    def generate_text(
        self,
        prompt: str,
        *,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> str:
        """Send a prompt and return the model’s plain-text reply."""
        response = self._generate(
            prompt,
            system_instruction=system_instruction,
            temperature=temperature,
        )
        text = (response.text or "").strip()
        if not text:
            raise LLMResponseError("The model returned an empty text response.")
        return text

    @overload
    def generate_json(
        self,
        prompt: str,
        *,
        schema: type[TModel],
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> TModel: ...

    @overload
    def generate_json(
        self,
        prompt: str,
        *,
        schema: None = None,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> dict[str, Any]: ...

    def generate_json(
        self,
        prompt: str,
        *,
        schema: Optional[type[BaseModel]] = None,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Union[BaseModel, dict[str, Any]]:
        """Request JSON. If ``schema`` is a Pydantic model, the payload is validated."""
        json_instruction = (
            "Respond with valid JSON only. Do not wrap the JSON in markdown fences."
        )
        if system_instruction:
            combined = f"{system_instruction}\n\n{json_instruction}"
        else:
            combined = json_instruction

        config_kwargs: dict[str, Any] = {
            "response_mime_type": "application/json",
        }
        if schema is not None:
            config_kwargs["response_schema"] = schema

        response = self._generate(
            prompt,
            system_instruction=combined,
            temperature=temperature,
            extra_config=config_kwargs,
        )
        raw = (response.text or "").strip()
        if not raw:
            raise LLMResponseError("The model returned an empty JSON response.")

        try:
            payload = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise StructuredOutputError(
                "The model response was not valid JSON."
            ) from exc

        if not isinstance(payload, dict):
            raise StructuredOutputError(
                "Expected a JSON object at the top level of the model response."
            )

        if schema is None:
            return payload

        try:
            return schema.model_validate(payload)
        except ValidationError as exc:
            raise StructuredOutputError(
                "JSON did not match the requested schema."
            ) from exc

    def generate_safe_json(
        self,
        payload: SafeLLMPayload,
        *,
        schema: Optional[type[BaseModel]] = None,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Union[BaseModel, dict[str, Any]]:
        """Generate JSON from an already-approved payload.

        The payload is validated again at the client boundary. This public API
        gives future callers a typed alternative to passing arbitrary strings.
        """
        if not isinstance(payload, SafeLLMPayload):
            raise LLMConnectionError("PRIVACY_PAYLOAD_REQUIRED")
        return self.generate_json(
            payload.safe_text,
            schema=schema,
            system_instruction=system_instruction,
            temperature=temperature,
        )

    def _approved_payload(self, prompt: str, *, source_type: str) -> SafeLLMPayload:
        try:
            return self._privacy_gateway.prepare(prompt, source_type=source_type)
        except PrivacyGatewayError as exc:
            logger.warning("llm_request_blocked privacy_reason=blocked")
            raise LLMConnectionError("PRIVACY_GATEWAY_BLOCKED") from exc

    def _generate(
        self,
        prompt: str,
        *,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        extra_config: Optional[dict[str, Any]] = None,
    ) -> ProviderResponse:
        """Legacy internal hook that still gates every raw prompt."""
        return self._generate_safe(
            self._approved_payload(prompt, source_type="llm_client"),
            system_instruction=system_instruction,
            temperature=temperature,
            extra_config=extra_config,
        )

    def _generate_safe(
        self,
        payload: SafeLLMPayload,
        *,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
        extra_config: Optional[dict[str, Any]] = None,
    ) -> ProviderResponse:
        if not isinstance(payload, SafeLLMPayload) or not payload.safe_text.strip():
            raise LLMResponseError("Approved LLM payload must be non-empty.")
        options = extra_config or {}
        request = ProviderRequest(
            payload=payload,
            system_instruction=system_instruction,
            temperature=temperature,
            response_mime_type=options.get("response_mime_type"),
            response_schema=options.get("response_schema"),
        )
        try:
            response = self._provider.generate(request)
        except ProviderError as exc:
            metadata = getattr(self._provider, "last_metadata", self._last_provider_metadata)
            if isinstance(metadata, ProviderMetadata):
                self._last_provider_metadata = metadata
            logger.warning(
                "llm_provider_failure code=%s fallback_used=%s",
                exc.code,
                self._last_provider_metadata.fallback_used,
            )
            raise LLMConnectionError(exc.code) from exc
        metadata = getattr(self._provider, "last_metadata", self._last_provider_metadata)
        if isinstance(metadata, ProviderMetadata):
            self._last_provider_metadata = metadata
        return response
