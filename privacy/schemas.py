"""Pydantic models separating raw application data from safe LLM data."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field


class PrivacyResult(BaseModel):
    """Non-sensitive result metadata for one de-identification operation."""

    model_config = ConfigDict(extra="forbid")

    safe_text: str = ""
    detected_categories: list[str] = Field(default_factory=list)
    redaction_count: int = Field(default=0, ge=0)
    blocked: bool = False
    reason: str | None = None
    source_type: str


class SafeLLMPayload(BaseModel):
    """The only payload shape approved for an outbound model request.

    This deliberately contains no reversible token mapping or original text.
    """

    model_config = ConfigDict(extra="forbid")

    safe_text: str = Field(..., min_length=1)
    source_type: str
    detected_categories: list[str] = Field(default_factory=list)
    redaction_count: int = Field(default=0, ge=0)
    payload_size: int = Field(default=0, ge=0)
