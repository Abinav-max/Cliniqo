"""Errors raised when a payload cannot safely cross the LLM boundary."""


class PrivacyGatewayError(Exception):
    """Base error for privacy processing failures."""


class PrivacyPayloadBlockedError(PrivacyGatewayError):
    """Raised when the gateway cannot produce a validated safe payload."""
