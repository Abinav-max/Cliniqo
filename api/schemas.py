"""API request/response schemas for the Cliniqo frontend integration."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Optional
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field


def _utc_now() -> datetime:
    return datetime.now(datetime.utcnow().utcoffset() or datetime.min.utcoffset())


class SessionCreateResponse(BaseModel):
    session_id: str
    status: str = "created"
    created_at: datetime = Field(default_factory=_utc_now)


class SessionStateResponse(BaseModel):
    session_id: str
    status: str
    current_screen: Optional[str] = None
    interview: Optional[dict[str, Any]] = None
    clinical_history: Optional[dict[str, Any]] = None
    risk_assessment: Optional[dict[str, Any]] = None
    documents: list[dict[str, Any]] = Field(default_factory=list)
    physician_summary: Optional[dict[str, Any]] = None
    timeline: list[dict[str, Any]] = Field(default_factory=list)
    errors: list[dict[str, Any]] = Field(default_factory=list)
    workflow_status: str = "idle"


class PatientMessageRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    channel: Optional[str] = "voice"
    patient_id: Optional[str] = None


class InterviewTurnResponse(BaseModel):
    session_id: str
    assistant_message: str
    information_collected: dict[str, Any]
    missing_information: list[str]
    next_question_category: Optional[str] = None
    interview_complete: bool = False
    clinical_history: Optional[dict[str, Any]] = None
    risk_assessment: Optional[dict[str, Any]] = None
    physician_summary: Optional[dict[str, Any]] = None
    current_diagnosis: Optional[str] = None
    current_screen: Optional[str] = None
    next_screen: Optional[str] = None


class DocumentUploadRequest(BaseModel):
    session_id: str
    document_id: Optional[str] = None
    document_type: Optional[str] = None
    document_date: Optional[str] = None
    ocr_text: str
    filename: Optional[str] = None
    mime_type: Optional[str] = None
    size_bytes: Optional[int] = None
    page_count: Optional[int] = None
    classification: Optional[dict[str, Any]] = None
    quality: Optional[dict[str, Any]] = None
    ocr: Optional[dict[str, Any]] = None
    extracted_fields: list[dict[str, Any]] = Field(default_factory=list)
    custom_fields: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    review: Optional[dict[str, Any]] = None
    structured_data: Optional[dict[str, Any]] = None
    status: str = "review_required"


class DocumentUploadResponse(BaseModel):
    document_id: str
    session_id: str
    status: str
    review_required: bool
    extracted_fields_count: int
    classification: Optional[dict[str, Any]] = None
    quality: Optional[dict[str, Any]] = None
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    temporal_context: dict[str, Any] = Field(default_factory=dict)


class DocumentReviewResponse(BaseModel):
    document_id: str
    document_type: Optional[str] = None
    review_status: str
    ocr_confidence: Optional[float] = None
    extraction_completeness: Optional[float] = None
    classification: Optional[dict[str, Any]] = None
    quality: Optional[dict[str, Any]] = None
    pages: list[dict[str, Any]] = Field(default_factory=list)
    extracted_fields: list[dict[str, Any]] = Field(default_factory=list)
    warnings: list[dict[str, Any]] = Field(default_factory=list)
    review_required: bool = False
    structured_data: Optional[dict[str, Any]] = None


class DocumentConfirmRequest(BaseModel):
    session_id: str
    document_id: str
    confirmed_fields: list[dict[str, Any]] = Field(default_factory=list)


class DocumentConfirmResponse(BaseModel):
    document_id: str
    session_id: str
    status: str
    validated_extraction: Optional[dict[str, Any]] = None
    physician_summary: Optional[dict[str, Any]] = None


class SummaryResponse(BaseModel):
    session_id: str
    overview: str
    structured_history_highlights: list[str] = Field(default_factory=list)
    safety_items_to_review: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    questions_for_clinician: list[str] = Field(default_factory=list)
    document_derived_findings: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    patient_reported_concerns: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    overall_attention_level: str = "routine"
    source_evidence: dict[str, str] = Field(default_factory=dict)
    generated_at: datetime = Field(default_factory=_utc_now)


class TimelineResponse(BaseModel):
    session_id: str
    events: list[dict[str, Any]] = Field(default_factory=list)


class ProfileResponse(BaseModel):
    name: Optional[str] = None
    dob: Optional[str] = None
    mobile: Optional[str] = None
    emergency_contact: Optional[str] = None
    blood_group: Optional[str] = None
    abha_id: Optional[str] = None
    phr_id: Optional[str] = None
    linked_health_id: Optional[str] = None


class HealthProfileExport(BaseModel):
    patient_profile: dict[str, Any]
    current_intake: dict[str, Any]
    medical_history: list[dict[str, Any]]
    active_medications: list[dict[str, Any]]
    allergies: list[dict[str, Any]]
    lifestyle: dict[str, Any]
    vault_metadata: dict[str, Any]


class ErrorResponse(BaseModel):
    error: str
    code: str
    details: Optional[dict[str, Any]] = None


class OCRDocumentInput(BaseModel):
    document_id: Optional[str] = None
    filename: str
    mime_type: str
    size_bytes: int
    page_count: int
    uploaded_at: str
    ocr_text: str
    classification: dict[str, Any]
    quality: dict[str, Any]
    ocr: dict[str, Any]
    extracted_fields: list[dict[str, Any]]
    custom_fields: list[dict[str, Any]]
    warnings: list[dict[str, Any]]
    review: dict[str, Any]
    structured_data: dict[str, Any]
    status: str = "review_required"


class APISessionState(BaseModel):
    session_id: str
    orchestrator_state: dict[str, Any]
    created_at: datetime = Field(default_factory=_utc_now)
    updated_at: datetime = Field(default_factory=_utc_now)


def create_session_id() -> str:
    return str(uuid4())