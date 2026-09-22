"""Pydantic schemas for the medical AI layer.

These models structure information for clinician review. They do not encode
diagnoses, prescriptions, or treatment decisions.
"""

from __future__ import annotations

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


class Role(str, Enum):
    PATIENT = "patient"
    CLINICIAN = "clinician"
    SYSTEM = "system"


class RiskSeverity(str, Enum):
    LOW = "low"
    MODERATE = "moderate"
    HIGH = "high"
    UNKNOWN = "unknown"


class AttentionLevel(str, Enum):
    """Controlled clinician-review priority; this is not a diagnosis."""

    ROUTINE = "routine"
    ATTENTION = "attention"
    URGENT = "urgent"


class SummarySourceType(str, Enum):
    """The only provenance categories a physician-summary fact may claim."""

    CLINICAL_HISTORY = "clinical_history"
    RISK_ASSESSMENT = "risk_assessment"
    DOCUMENT = "document"
    PATIENT_CONVERSATION = "patient_conversation"


class WorkflowStatus(str, Enum):
    """Lifecycle state for a multi-agent clinical-information workflow."""

    IDLE = "idle"
    COMPLETED = "completed"
    PARTIAL_FAILURE = "partial_failure"
    FAILED = "failed"


class SafetyMixin(BaseModel):
    """Shared reminder that outputs are for clinician review only."""

    model_config = ConfigDict(extra="forbid")

    for_clinician_review_only: bool = Field(
        default=True,
        description="Outputs assist clinicians; they are not diagnoses or orders.",
    )


class PatientMessage(SafetyMixin):
    """A single message captured during an interview (synthetic/de-identified)."""

    message_id: Optional[str] = None
    session_id: Optional[str] = None
    role: Role = Role.PATIENT
    content: str = Field(..., min_length=1)
    timestamp: datetime = Field(default_factory=_utc_now)
    language: Optional[str] = None


class MedicationMention(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name_as_reported: str
    dose_as_reported: Optional[str] = None
    frequency_as_reported: Optional[str] = None
    notes: Optional[str] = None


class HistoryOfPresentIllness(BaseModel):
    """Reported details of the current concern; each field may be unknown."""

    model_config = ConfigDict(extra="forbid")

    onset: Optional[str] = None
    duration: Optional[str] = None
    location: Optional[str] = None
    quality: Optional[str] = None
    # A patient may report a numeric score (for example ``7/10``) or an
    # explicit descriptor (for example ``severe``). The Structuring Agent's
    # evidence-grounding layer decides whether either value is retained.
    severity: Optional[int | str] = Field(default=None)
    timing: Optional[str] = None
    progression: Optional[str] = None

    @field_validator("severity", mode="before")
    @classmethod
    def parse_reported_severity(cls, value: object) -> object:
        """Accept a simple reported numeric value, without interpreting it."""
        if isinstance(value, str) and value.strip().isdigit():
            numeric = int(value.strip())
            if 0 <= numeric <= 10:
                return numeric
            raise ValueError("Reported numeric severity must be between 0 and 10.")
        return value


class ClinicalHistory(SafetyMixin):
    """Structured history extracted from interview or documents.

    Fields capture reported information only. Absence of a field means
    missing information, not a negative clinical finding.
    """

    session_id: Optional[str] = None
    # Existing Phase 1 fields are retained.  The new names below are the
    # canonical structured representation used by StructuringAgent.
    chief_concern: Optional[str] = None
    chief_complaint: Optional[str] = None
    # ``str`` remains accepted for callers using the foundation schema. New
    # structuring output always uses ``HistoryOfPresentIllness``.
    history_of_present_illness: HistoryOfPresentIllness | str | None = Field(
        default_factory=HistoryOfPresentIllness
    )
    reported_symptoms: list[str] = Field(default_factory=list)
    reported_allergies: list[str] = Field(default_factory=list)
    reported_medications: list[MedicationMention] = Field(default_factory=list)
    past_medical_history: list[str] = Field(default_factory=list)
    family_history: list[str] = Field(default_factory=list)
    social_history: Optional[str] = None
    missing_information: list[str] = Field(default_factory=list)
    source_notes: Optional[str] = None

    associated_symptoms: list[str] = Field(default_factory=list)
    previous_similar_episodes: list[str] = Field(default_factory=list)
    medications: list[MedicationMention] = Field(default_factory=list)
    allergies: list[str] = Field(default_factory=list)
    personal_history: dict[str, Any] = Field(default_factory=dict)
    previous_investigations: list[str] = Field(default_factory=list)
    patient_reported_concerns: list[str] = Field(default_factory=list)
    unknown_information: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    source_evidence: dict[str, str] = Field(default_factory=dict)


class AyushAssessment(SafetyMixin):
    """Patient-reported AYUSH/Dashavidha assessment; clinician review required."""

    prakriti: Optional[str] = None
    vikriti: Optional[str] = None
    sara: Optional[str] = None
    samhanana: Optional[str] = None
    pramana: Optional[str] = None
    satmya: Optional[str] = None
    sattva: Optional[str] = None
    ahara_shakti: Optional[str] = None
    vyayama_shakti: Optional[str] = None
    vaya: Optional[str] = None
    ahara_vihara: dict[str, Any] = Field(default_factory=dict)
    source: Literal["patient", "clinician", "unknown"] = "unknown"
    verification_status: Literal["pending", "verified"] = "pending"


class RiskFlag(SafetyMixin):
    """A possible safety concern for clinician attention — not a diagnosis."""

    flag_id: Optional[str] = None
    category: str = Field(
        ...,
        description="e.g. missing_information, allergy_mention, red_flag_symptom",
    )
    description: str
    severity: RiskSeverity = RiskSeverity.UNKNOWN
    evidence: Optional[str] = None
    reason: Optional[str] = None
    requires_clinician_review: bool = False
    recommended_clinician_check: Optional[str] = Field(
        default=None,
        description="What a clinician may want to verify; not a treatment plan.",
    )


class RiskAssessment(SafetyMixin):
    """Validated safety review of reported history, never a diagnosis."""

    session_id: Optional[str] = None
    risk_flags: list[RiskFlag] = Field(default_factory=list)
    emergency_indicators: list[str] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    overall_attention_level: AttentionLevel = AttentionLevel.ROUTINE
    # An explicit invariant makes diagnosis-bearing LLM payloads invalid.
    diagnosis: Literal[None] = None


class DocumentInput(BaseModel):
    """OCR text and patient-confirmed temporal context for a document."""

    model_config = ConfigDict(extra="forbid")

    document_id: Optional[str] = None
    document_type: Optional[str] = None
    document_date: Optional[str] = None
    document_date_type: Literal["exact", "approximate", "unknown"] = "unknown"
    document_date_source: Literal["ocr", "patient", "clinician", "unknown"] = "unknown"
    document_classification: Literal["current", "historical"] = "historical"
    classification_source: Literal["patient", "clinician"] = "patient"
    ocr_text: str


class DocumentEvidenceItem(BaseModel):
    """One document-derived item with its OCR evidence preserved."""

    model_config = ConfigDict(extra="forbid")

    text: str = Field(..., min_length=1)
    source_text: str = Field(..., min_length=1)
    uncertain: bool = False
    source_type: Literal["document"] = "document"


class DocumentMedication(BaseModel):
    """Medication text as reported by the OCR document, not an instruction."""

    model_config = ConfigDict(extra="forbid")

    name_as_reported: str = Field(..., min_length=1)
    dose_as_reported: Optional[str] = None
    frequency_as_reported: Optional[str] = None
    route_as_reported: Optional[str] = None
    duration_as_reported: Optional[str] = None
    source_text: str = Field(..., min_length=1)
    uncertain: bool = False
    source_type: Literal["document"] = "document"


class LabResult(BaseModel):
    """A laboratory value explicitly reported in OCR text; no interpretation."""

    model_config = ConfigDict(extra="forbid")

    test_name: str = Field(..., min_length=1)
    value_as_reported: Optional[str] = None
    unit_as_reported: Optional[str] = None
    reference_range_as_reported: Optional[str] = None
    date_as_reported: Optional[str] = None
    source_text: str = Field(..., min_length=1)
    uncertain: bool = False
    source_type: Literal["document"] = "document"


class DocumentExtraction(SafetyMixin):
    """Structured content pulled from OCR plus verified temporal context.

    Document-derived facts are never implicitly promoted to current patient facts.
    """

    document_id: Optional[str] = None
    document_type: Optional[str] = None
    document_date: Optional[str] = None
    document_date_type: Literal["exact", "approximate", "unknown"] = "unknown"
    document_date_source: Literal["ocr", "patient", "clinician", "unknown"] = "unknown"
    document_classification: Literal["current", "historical"] = "historical"
    classification_source: Literal["patient", "clinician"] = "patient"
    temporal_status: Literal["current", "historical", "unknown"] = "unknown"
    verification_status: Literal["pending", "verified", "rejected"] = "pending"
    document_date_source_text: Optional[str] = None
    extracted_text_summary: Optional[str] = None
    key_findings: list[str] = Field(default_factory=list)
    reported_values: dict[str, str] = Field(default_factory=dict)
    missing_or_illegible_sections: list[str] = Field(default_factory=list)
    source_excerpt: Optional[str] = None

    source_type: Literal["document"] = "document"
    medications: list[DocumentMedication] = Field(default_factory=list)
    diagnoses_mentioned: list[DocumentEvidenceItem] = Field(default_factory=list)
    lab_results: list[LabResult] = Field(default_factory=list)
    procedures: list[DocumentEvidenceItem] = Field(default_factory=list)
    symptoms: list[DocumentEvidenceItem] = Field(default_factory=list)
    allergies: list[DocumentEvidenceItem] = Field(default_factory=list)
    clinical_observations: list[DocumentEvidenceItem] = Field(default_factory=list)
    follow_up_instructions: list[DocumentEvidenceItem] = Field(default_factory=list)
    unknown_or_unclear: list[DocumentEvidenceItem] = Field(default_factory=list)


class SummaryInput(BaseModel):
    """Validated upstream payloads accepted by the Physician Summary Agent."""

    model_config = ConfigDict(extra="forbid")

    clinical_history: Optional[ClinicalHistory] = None
    risk_assessment: Optional[RiskAssessment] = None
    document_extractions: list[DocumentExtraction] = Field(default_factory=list)
    # Optional secondary context. It is never preferred over validated history.
    patient_conversation: list[str] = Field(default_factory=list)
    ayush_assessment: Optional[AyushAssessment] = None


class WorkflowError(BaseModel):
    """A visible, non-sensitive error associated with one orchestration stage."""

    model_config = ConfigDict(extra="forbid")

    stage: str
    message: str


class OrchestrationState(BaseModel):
    """Validated state retained by the Phase 6 orchestrator between turns."""

    model_config = ConfigDict(extra="forbid")

    session_id: Optional[str] = None
    conversation: list[dict[str, str]] = Field(default_factory=list)
    # Phase 1's state model lives in the Interview Agent module; a serialized
    # snapshot avoids a schemas-to-agents import cycle.
    interview_state: Optional[dict[str, Any]] = None
    clinical_history: Optional[ClinicalHistory] = None
    risk_assessment: Optional[RiskAssessment] = None
    documents: list[DocumentExtraction] = Field(default_factory=list)
    ayush_assessment: Optional[AyushAssessment] = None
    physician_summary: Optional["PhysicianSummary"] = None
    processed_document_keys: list[str] = Field(default_factory=list)
    workflow_status: WorkflowStatus = WorkflowStatus.IDLE
    errors: list[WorkflowError] = Field(default_factory=list)


class PhysicianSummary(SafetyMixin):
    """Concise briefing for a physician. Not a diagnosis or care plan."""

    session_id: Optional[str] = None
    overview: str
    structured_history_highlights: list[str] = Field(default_factory=list)
    safety_items_to_review: list[str] = Field(default_factory=list)
    information_gaps: list[str] = Field(default_factory=list)
    questions_for_clinician: list[str] = Field(default_factory=list)
    document_derived_findings: list[str] = Field(default_factory=list)
    contradictions: list[str] = Field(default_factory=list)
    patient_reported_concerns: list[str] = Field(default_factory=list)
    uncertainties: list[str] = Field(default_factory=list)
    overall_attention_level: AttentionLevel = AttentionLevel.ROUTINE
    # Maps summary statement IDs to an enumerated upstream source category.
    # Exact patient/OCR excerpts remain in upstream validated objects.
    source_evidence: dict[str, SummarySourceType] = Field(default_factory=dict)
    disclaimer: str = Field(
        default=(
            "For licensed clinician review only. This prototype does not diagnose, "
            "prescribe, or replace clinical judgment."
        )
    )
    generated_at: datetime = Field(default_factory=_utc_now)
