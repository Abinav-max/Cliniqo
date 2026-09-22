"""Application-level de-identification for every outbound LLM payload.

Raw application data must never be passed to an external LLM client directly.
Use :class:`PrivacyGateway` to create a :class:`SafeLLMPayload` first.
"""

from privacy.errors import PrivacyGatewayError, PrivacyPayloadBlockedError
from privacy.gateway import PrivacyGateway
from privacy.schemas import PrivacyResult, SafeLLMPayload

__all__ = [
    "PrivacyGateway",
    "PrivacyGatewayError",
    "PrivacyPayloadBlockedError",
    "PrivacyResult",
    "SafeLLMPayload",
]
