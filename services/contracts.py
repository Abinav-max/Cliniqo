from __future__ import annotations

from typing import Any, Literal, Protocol

from pydantic import BaseModel, Field


class NLPResult(BaseModel):
    text: str = Field(min_length=1)
    language: str | None = None
    confidence: float | None = Field(default=None, ge=0, le=1)
    source: Literal['voice', 'text'] = 'text'
    processing_status: Literal['completed', 'failed'] = 'completed'
    entities: dict[str, Any] = Field(default_factory=dict)


class OCRResult(BaseModel):
    document_type: str | None = None
    raw_text: str = ''
    extracted_fields: dict[str, Any] = Field(default_factory=dict)
    confidence: float | None = Field(default=None, ge=0, le=1)
    warnings: list[str] = Field(default_factory=list)


class TriageFlag(BaseModel):
    is_red_flag: bool
    severity: Literal['low', 'medium', 'high', 'urgent'] = 'low'
    category: str
    reason: str
    source: Literal['rule', 'llm', 'both', 'clinician'] = 'rule'


class LLMClinicalOutput(BaseModel):
    chief_complaint: str | None = None
    symptoms: list[str] = Field(default_factory=list)
    duration: str | None = None
    severity: str | None = None
    medical_history: list[str] = Field(default_factory=list)
    medications: list[str] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    family_history: list[str] = Field(default_factory=list)
    lifestyle: dict[str, Any] = Field(default_factory=dict)
    document_findings: list[str] = Field(default_factory=list)
    clinical_observations: list[str] = Field(default_factory=list)
    red_flags: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    confidence: float = Field(default=0, ge=0, le=1)


class LLMService(Protocol):
    def structure(self, text: str) -> LLMClinicalOutput: ...


class OCRService(Protocol):
    def extract(self, content: bytes, filename: str, mime_type: str) -> OCRResult: ...


class NLPService(Protocol):
    def process(self, text: str, *, source: Literal['voice', 'text'], language: str | None = None) -> NLPResult: ...


class StorageService(Protocol):
    def upload(self, content: bytes, path: str, mime_type: str) -> str: ...
    def delete(self, path: str) -> None: ...


class SummaryService(Protocol):
    def generate(self, clinical_data: dict[str, Any]) -> dict[str, Any]: ...


class TriageService(Protocol):
    def evaluate(self, text: str) -> list[TriageFlag]: ...
