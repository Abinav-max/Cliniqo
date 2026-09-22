"""Stateful coordination of the five validated medical-information agents.

The orchestrator deliberately contains no interviewing, extraction, triage, or
summary logic. It only sequences agent calls, preserves validated outputs, and
makes failures and safety invariants visible to callers.
"""

from __future__ import annotations

import hashlib
import logging
import re
from typing import Any, Iterable, Optional, Protocol

from core.exceptions import MedicalAIError
from core.schemas import (
    AttentionLevel,
    ClinicalHistory,
    DocumentExtraction,
    DocumentInput,
    OrchestrationState,
    PhysicianSummary,
    RiskAssessment,
    WorkflowError,
    WorkflowStatus,
)

logger = logging.getLogger(__name__)


class InterviewStage(Protocol):
    def handle_message(self, patient_message: str) -> Any: ...


class StructuringStage(Protocol):
    def structure(self, conversation: Any, *, session_id: Optional[str] = None) -> ClinicalHistory: ...


class RiskStage(Protocol):
    def assess(self, history: ClinicalHistory) -> RiskAssessment: ...


class DocumentStage(Protocol):
    def extract(self, document: DocumentInput) -> DocumentExtraction: ...


class SummaryStage(Protocol):
    def summarize(
        self,
        clinical_history: ClinicalHistory,
        risk_assessment: RiskAssessment,
        document_extractions: list[DocumentExtraction],
        *,
        patient_conversation: Optional[list[str]] = None,
    ) -> PhysicianSummary: ...


_ATTENTION_ORDER = {
    AttentionLevel.ROUTINE: 0,
    AttentionLevel.ATTENTION: 1,
    AttentionLevel.URGENT: 2,
}
_MEDICATION_ADVICE = re.compile(
    r"\b(?:start|stop|continue|increase|decrease|change|adjust|switch)\s+"
    r"(?:taking\s+)?(?:your\s+)?(?:medication|medicine|meds|dose|dosage|[a-z][a-z-]{2,})\b",
    re.IGNORECASE,
)


class MedicalOrchestrator:
    """Coordinate existing agents with dependency injection and retained state."""

    def __init__(
        self,
        interview_agent: Optional[InterviewStage] = None,
        structuring_agent: Optional[StructuringStage] = None,
        risk_agent: Optional[RiskStage] = None,
        document_agent: Optional[DocumentStage] = None,
        summary_agent: Optional[SummaryStage] = None,
        *,
        session_id: Optional[str] = None,
    ) -> None:
        # Imports are local so this coordinator does not create a schemas/agents
        # cycle and tests may inject deterministic fakes without SDK access.
        if interview_agent is None:
            from agents.interview_agent import InterviewAgent

            interview_agent = InterviewAgent(session_id=session_id)
        if structuring_agent is None:
            from agents.structuring_agent import StructuringAgent

            structuring_agent = StructuringAgent()
        if risk_agent is None:
            from agents.risk_agent import RiskAgent

            risk_agent = RiskAgent()
        if document_agent is None:
            from agents.document_agent import DocumentAgent

            document_agent = DocumentAgent()
        if summary_agent is None:
            from agents.summary_agent import SummaryAgent

            summary_agent = SummaryAgent()
        self._interview = interview_agent
        self._structuring = structuring_agent
        self._risk = risk_agent
        self._document = document_agent
        self._summary = summary_agent
        self.state = OrchestrationState(session_id=session_id)
        self.patient_context: dict[str, Any] = {}

    def set_patient_context(self, context: dict[str, Any]) -> None:
        """Set longitudinal patient profile context for adaptive interview turns."""
        self.patient_context = context or {}
        if hasattr(self._interview, "set_patient_context"):
            self._interview.set_patient_context(context)

    def handle_patient_message(
        self,
        patient_message: str,
        *,
        documents: Optional[Iterable[DocumentInput | dict[str, Any]]] = None,
    ) -> OrchestrationState:
        """Process one patient turn and optional newly supplied OCR documents."""
        text = (patient_message or "").strip()
        if not text:
            return self._failure("interview", "Patient message must be a non-empty string.", failed=True)

        self.state.errors = []
        self.state.physician_summary = None
        try:
            interview_result = self._interview.handle_message(text)
        except Exception as exc:  # agent exceptions are exposed, never hidden
            return self._failure("interview", exc)
        self._capture_interview(interview_result)

        try:
            history = self._structuring.structure(
                interview_result, session_id=self.state.session_id
            )
        except Exception as exc:
            return self._failure("structuring", exc)
        self.state.clinical_history = history

        try:
            risk = self._risk.assess(history)
        except Exception as exc:
            return self._failure("risk", exc)
        self.state.risk_assessment = risk

        self._process_new_documents(documents)
        return self._run_summary()

    process_turn = handle_patient_message

    def clear_session(self) -> None:
        """Discard the in-memory workflow state for the current session.

        This prototype does not persist state itself. Callers that no longer need
        a session can use this explicit boundary to release the retained raw
        conversation and derived outputs without affecting other orchestrators.
        """
        self.state = OrchestrationState()

    def add_documents(
        self, documents: Iterable[DocumentInput | dict[str, Any]]
    ) -> OrchestrationState:
        """Process new documents without restarting the patient interview."""
        if not self.state.clinical_history or not self.state.risk_assessment:
            return self._failure(
                "document", "Validated clinical history and risk assessment are required first."
            )
        self.state.errors = []
        self._process_new_documents(documents)
        return self._run_summary()

    def _capture_interview(self, result: Any) -> None:
        interview_state = getattr(result, "state", None)
        if interview_state is None:
            raise MedicalAIError("Interview Agent did not return a state snapshot.")
        self.state.session_id = getattr(interview_state, "session_id", self.state.session_id)
        self.state.interview_state = interview_state.model_dump()
        self.state.conversation = [
            {"role": str(turn.role), "content": turn.content}
            for turn in interview_state.conversation_history
        ]

    def _process_new_documents(
        self, documents: Optional[Iterable[DocumentInput | dict[str, Any]]]
    ) -> None:
        if documents is None:
            return
        for raw_document in documents:
            try:
                document = (
                    raw_document
                    if isinstance(raw_document, DocumentInput)
                    else DocumentInput.model_validate(raw_document)
                )
            except Exception as exc:
                self._record_error("document", exc)
                continue
            key = self._document_key(document)
            if key in self.state.processed_document_keys:
                continue
            try:
                extraction = self._document.extract(document)
            except Exception as exc:
                self._record_error("document", exc)
                self.state.processed_document_keys.append(key)
                continue
            self.state.documents.append(extraction)
            self.state.processed_document_keys.append(key)

    def _run_summary(self) -> OrchestrationState:
        history, risk = self.state.clinical_history, self.state.risk_assessment
        if not history or not risk:
            return self._failure("summary", "Validated history and risk assessment are required.")
        try:
            summary = self._summary.summarize(
                history,
                risk,
                self.state.documents,
                patient_conversation=[turn["content"] for turn in self.state.conversation if turn["role"] == "patient"],
                ayush_assessment=self.state.ayush_assessment,
            )
        except Exception as exc:
            return self._failure("summary", exc)
        if any(error.stage == "document" for error in self.state.errors):
            summary.information_gaps = _unique(
                summary.information_gaps
                + ["Document processing unavailable; uploaded document findings could not be incorporated."]
            )
            summary.source_evidence.setdefault("information_gaps.document_processing", "orchestrator")
        try:
            self._validate_final(summary)
        except Exception as exc:
            self.state.physician_summary = None
            return self._failure("final_validation", exc)
        self.state.physician_summary = summary
        self.state.workflow_status = (
            WorkflowStatus.PARTIAL_FAILURE if self.state.errors else WorkflowStatus.COMPLETED
        )
        self._log_stage("workflow", self.state.workflow_status.value)
        return self.state

    def _validate_final(self, summary: PhysicianSummary) -> None:
        if not isinstance(summary, PhysicianSummary):
            raise MedicalAIError("Summary stage did not return a validated PhysicianSummary.")
        risk = self.state.risk_assessment
        if self.state.clinical_history is not None and risk is None:
            raise MedicalAIError("Risk assessment is required for structured clinical history.")
        if risk is None:
            return
        if _ATTENTION_ORDER[summary.overall_attention_level] < _ATTENTION_ORDER[risk.overall_attention_level]:
            raise MedicalAIError("Physician summary downgraded upstream risk attention level.")
        summary_text = " ".join(summary.safety_items_to_review).lower()
        for flag in risk.risk_flags:
            # Preserve the actual flag, not merely the attention level.
            evidence = (flag.evidence or "").lower()
            description_words = [word for word in flag.description.lower().split() if len(word) > 4]
            if evidence and evidence not in summary_text and not any(word in summary_text for word in description_words):
                raise MedicalAIError("Physician summary omitted an upstream risk flag.")
        if any(item.source_type != "document" for document in self.state.documents for item in document.medications):
            raise MedicalAIError("Document-derived medication lost its source attribution.")
        # Phase 5 owns detailed content safety; this confirms the final model
        # still has no diagnostic field and remains clinician-review-only.
        if hasattr(summary, "diagnosis"):
            raise MedicalAIError("Physician summary must not contain a diagnosis field.")
        summary_content = " ".join(
            [summary.overview]
            + summary.structured_history_highlights
            + summary.safety_items_to_review
            + summary.document_derived_findings
        )
        if _MEDICATION_ADVICE.search(summary_content):
            raise MedicalAIError("Physician summary contains prohibited medication advice.")
        if not summary.for_clinician_review_only:
            raise MedicalAIError("Final summary must remain for clinician review only.")

    def _failure(self, stage: str, error: Exception | str, *, failed: bool = False) -> OrchestrationState:
        self._record_error(stage, error)
        self.state.workflow_status = WorkflowStatus.FAILED if failed else WorkflowStatus.PARTIAL_FAILURE
        self._log_stage(stage, self.state.workflow_status.value)
        return self.state

    def _record_error(self, stage: str, error: Exception | str) -> None:
        # Exceptions can originate in SDKs, parsers, or injected integrations.
        # Do not serialize their text into user-visible workflow state because it
        # may contain prompts, OCR, identifiers, or credentials.
        codes = {
            "interview": "INTERVIEW_STAGE_FAILED",
            "structuring": "STRUCTURING_STAGE_FAILED",
            "risk": "RISK_STAGE_FAILED",
            "document": "DOCUMENT_STAGE_FAILED",
            "summary": "SUMMARY_STAGE_FAILED",
            "final_validation": "FINAL_VALIDATION_FAILED",
        }
        self.state.errors.append(WorkflowError(stage=stage, message=codes.get(stage, "WORKFLOW_STAGE_FAILED")))
        self._log_stage(stage, "failed")

    @staticmethod
    def _document_key(document: DocumentInput) -> str:
        if document.document_id:
            return f"id:{document.document_id}"
        return "ocr:" + hashlib.sha256(document.ocr_text.encode("utf-8")).hexdigest()

    @staticmethod
    def _log_stage(stage: str, status: str) -> None:
        logger.info("orchestrator_stage=%s status=%s", stage, status)


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = value.strip().lower()
        if key and key not in seen:
            seen.add(key)
            result.append(value)
    return result
