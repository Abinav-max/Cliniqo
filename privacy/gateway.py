"""Mandatory application-side gateway for outbound LLM content."""

from __future__ import annotations

from privacy.detector import IdentifierDetector
from privacy.errors import PrivacyGatewayError, PrivacyPayloadBlockedError
from privacy.minimizer import PayloadMinimizer
from privacy.schemas import PrivacyResult, SafeLLMPayload


class PrivacyGateway:
    """Detect, redact, minimize, and validate an outbound LLM payload.

    The gateway never stores a reversible identifier mapping. Any processing
    failure raises a safe typed error, so callers fail closed rather than sending
    the original value.
    """

    def __init__(
        self,
        detector: IdentifierDetector | None = None,
        minimizer: PayloadMinimizer | None = None,
        *,
        max_payload_chars: int = 40_000,
    ) -> None:
        if max_payload_chars <= 0:
            raise ValueError("max_payload_chars must be positive.")
        self._detector = detector or IdentifierDetector()
        self._minimizer = minimizer or PayloadMinimizer()
        self._max_payload_chars = max_payload_chars

    def prepare(self, text: str, *, source_type: str) -> SafeLLMPayload:
        """Create a validated payload or raise without exposing raw content."""
        if not isinstance(text, str) or not text.strip():
            raise PrivacyPayloadBlockedError("PRIVACY_PAYLOAD_INVALID")
        if len(text) > self._max_payload_chars:
            raise PrivacyPayloadBlockedError("PRIVACY_PAYLOAD_TOO_LARGE")
        try:
            safe_text, categories, count = self._detector.redact(text)
            safe_text = self._minimizer.minimize(safe_text, source_type=source_type)
            if not safe_text:
                raise PrivacyPayloadBlockedError("PRIVACY_PAYLOAD_EMPTY")
            # A second scan is a fail-closed guard against a detector/minimizer
            # regression. It receives only the proposed outbound text.
            _, residual_categories, residual_count = self._detector.redact(safe_text)
            if residual_count:
                raise PrivacyPayloadBlockedError("PRIVACY_VALIDATION_FAILED")
        except PrivacyGatewayError:
            raise
        except Exception as exc:  # Detector failures must never permit raw egress.
            raise PrivacyGatewayError("PRIVACY_GATEWAY_UNAVAILABLE") from exc
        return SafeLLMPayload(
            safe_text=safe_text,
            source_type=source_type,
            detected_categories=categories,
            redaction_count=count,
            payload_size=len(safe_text),
        )

    def result(self, text: str, *, source_type: str) -> PrivacyResult:
        """Return safe result metadata for callers that do not need a model call."""
        try:
            payload = self.prepare(text, source_type=source_type)
        except PrivacyGatewayError as exc:
            return PrivacyResult(
                blocked=True,
                # A detector/integration implementation must not be able to
                # surface raw input through this convenience result.
                reason="PRIVACY_GATEWAY_BLOCKED",
                source_type=source_type,
            )
        return PrivacyResult(
            safe_text=payload.safe_text,
            detected_categories=payload.detected_categories,
            redaction_count=payload.redaction_count,
            source_type=source_type,
        )
