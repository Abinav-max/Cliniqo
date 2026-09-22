"""Shared LLM, config, schemas, and safety primitives for the medical AI layer."""

from core.config import Settings, get_settings
from core.exceptions import (
    ConfigurationError,
    LLMClientError,
    LLMConnectionError,
    LLMResponseError,
    MedicalSafetyError,
    MissingAPIKeyError,
    StructuredOutputError,
)
from core.llm_client import LLMClient
from core.orchestrator import MedicalOrchestrator
from core.prompts import SAFETY_SYSTEM_INSTRUCTION
from core.schemas import (
    ClinicalHistory,
    HistoryOfPresentIllness,
    AttentionLevel,
    DocumentInput,
    DocumentEvidenceItem,
    DocumentMedication,
    LabResult,
    SummaryInput,
    WorkflowError,
    WorkflowStatus,
    OrchestrationState,
    DocumentExtraction,
    PatientMessage,
    PhysicianSummary,
    RiskFlag,
    RiskAssessment,
)

__all__ = [
    "ClinicalHistory",
    "HistoryOfPresentIllness",
    "AttentionLevel",
    "DocumentInput",
    "DocumentEvidenceItem",
    "DocumentMedication",
    "LabResult",
    "SummaryInput",
    "WorkflowError",
    "WorkflowStatus",
    "OrchestrationState",
    "ConfigurationError",
    "DocumentExtraction",
    "LLMClient",
    "MedicalOrchestrator",
    "LLMClientError",
    "LLMConnectionError",
    "LLMResponseError",
    "MedicalSafetyError",
    "MissingAPIKeyError",
    "PatientMessage",
    "PhysicianSummary",
    "RiskFlag",
    "RiskAssessment",
    "SAFETY_SYSTEM_INSTRUCTION",
    "Settings",
    "StructuredOutputError",
    "get_settings",
]
