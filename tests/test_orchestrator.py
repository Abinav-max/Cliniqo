"""Phase 6 workflow tests using injected, deterministic fake agents."""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

from core.orchestrator import MedicalOrchestrator
from core.schemas import (
    AttentionLevel,
    ClinicalHistory,
    DocumentExtraction,
    DocumentInput,
    PhysicianSummary,
    RiskAssessment,
    RiskFlag,
    RiskSeverity,
    WorkflowStatus,
)
from agents.interview_agent import ConversationTurn, InterviewState


class FakeInterview:
    def __init__(self) -> None:
        self.state = InterviewState(session_id="workflow-session")
        self.calls = 0

    def handle_message(self, text: str) -> Any:
        self.calls += 1
        self.state.conversation_history.append(ConversationTurn(role="patient", content=text))
        self.state.conversation_history.append(ConversationTurn(role="assistant", content="Synthetic follow-up"))
        return SimpleNamespace(state=self.state)


class FakeStructuring:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def structure(self, result: Any, *, session_id: str | None = None) -> ClinicalHistory:
        self.calls += 1
        if self.fail:
            raise RuntimeError("structuring unavailable")
        patient_text = " ".join(t.content.lower() for t in result.state.conversation_history if t.role == "patient")
        symptoms = ["breathlessness"] if "breathlessness" in patient_text else []
        severity = 7 if "7/10" in patient_text else None
        duration = "2 days" if "two days" in patient_text else None
        from core.schemas import HistoryOfPresentIllness
        return ClinicalHistory(
            session_id=session_id,
            chief_complaint="chest pain" if "chest pain" in patient_text else "headache",
            associated_symptoms=symptoms,
            history_of_present_illness=HistoryOfPresentIllness(duration=duration, severity=severity),
        )


class FakeRisk:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def assess(self, history: ClinicalHistory) -> RiskAssessment:
        self.calls += 1
        if self.fail:
            raise RuntimeError("risk unavailable")
        if history.chief_complaint == "chest pain" and "breathlessness" in history.associated_symptoms:
            return RiskAssessment(
                overall_attention_level=AttentionLevel.URGENT,
                risk_flags=[RiskFlag(category="urgent_symptom", description="Chest pain with breathlessness warrants review.", severity=RiskSeverity.HIGH, evidence="chest pain and breathlessness", requires_clinician_review=True)],
            )
        return RiskAssessment()


class FakeDocument:
    def __init__(self, fail: bool = False) -> None:
        self.calls = 0
        self.fail = fail

    def extract(self, document: DocumentInput) -> DocumentExtraction:
        self.calls += 1
        if self.fail:
            raise RuntimeError("document unavailable")
        return DocumentExtraction(document_id=document.document_id, source_excerpt=document.ocr_text)


class FakeSummary:
    def __init__(self, *, fail: bool = False, downgrade: bool = False, advice: bool = False, diagnosis: bool = False) -> None:
        self.calls = 0
        self.fail, self.downgrade, self.advice, self.diagnosis = fail, downgrade, advice, diagnosis

    def summarize(self, history: ClinicalHistory, risk: RiskAssessment, documents: list[DocumentExtraction], *, patient_conversation: list[str] | None = None) -> PhysicianSummary:
        self.calls += 1
        if self.fail:
            raise RuntimeError("summary unavailable")
        safety = [f"{flag.description} Evidence: {flag.evidence}" for flag in risk.risk_flags]
        result = PhysicianSummary(
            session_id=history.session_id,
            overview="Stop metformin." if self.advice else f"Reported {history.chief_complaint}.",
            safety_items_to_review=safety,
            overall_attention_level=AttentionLevel.ROUTINE if self.downgrade else risk.overall_attention_level,
            document_derived_findings=["Uploaded document available."] if documents else [],
            source_evidence={"safety_items_to_review.0": "risk_assessment"} if safety else {},
        )
        if self.diagnosis:
            # Simulate a malformed downstream object bypassing the normal
            # Summary Agent schema, so the orchestrator's final guard is tested.
            result.__dict__["diagnosis"] = "heart attack"
        return result


def build(**overrides: Any) -> tuple[MedicalOrchestrator, dict[str, Any]]:
    agents: dict[str, Any] = {
        "interview_agent": FakeInterview(), "structuring_agent": FakeStructuring(),
        "risk_agent": FakeRisk(), "document_agent": FakeDocument(), "summary_agent": FakeSummary(),
    }
    agents.update(overrides)
    return MedicalOrchestrator(**agents), agents


def test_patient_conversation_only_skips_document_agent() -> None:
    orchestrator, agents = build()
    state = orchestrator.handle_patient_message("I have chest pain.")
    assert state.workflow_status is WorkflowStatus.COMPLETED
    assert state.physician_summary is not None
    assert agents["document_agent"].calls == 0


def test_patient_and_ocr_document_runs_every_stage() -> None:
    orchestrator, agents = build()
    state = orchestrator.handle_patient_message("I have chest pain.", documents=[{"document_id": "d1", "ocr_text": "Metformin 500 mg"}])
    assert state.workflow_status is WorkflowStatus.COMPLETED
    assert len(state.documents) == 1
    assert agents["document_agent"].calls == 1


def test_multiple_turns_keep_same_session_and_conversation() -> None:
    orchestrator, _ = build()
    first = orchestrator.handle_patient_message("I have chest pain.")
    second = orchestrator.handle_patient_message("It started two days ago.")
    assert first.session_id == second.session_id == "workflow-session"
    assert len(second.conversation) == 4


def test_new_patient_information_updates_structured_history() -> None:
    orchestrator, _ = build()
    orchestrator.handle_patient_message("I have chest pain.")
    state = orchestrator.handle_patient_message("It is 7/10.")
    assert state.clinical_history.history_of_present_illness.severity == 7


def test_later_breathlessness_re_evaluates_risk() -> None:
    orchestrator, agents = build()
    orchestrator.handle_patient_message("I have chest pain.")
    state = orchestrator.handle_patient_message("I also have breathlessness.")
    assert state.risk_assessment.overall_attention_level is AttentionLevel.URGENT
    assert agents["risk_agent"].calls == 2


def test_urgent_risk_flag_is_preserved_in_final_state() -> None:
    orchestrator, _ = build()
    state = orchestrator.handle_patient_message("I have chest pain and breathlessness.")
    assert state.workflow_status is WorkflowStatus.COMPLETED
    assert state.risk_assessment.risk_flags
    assert state.physician_summary.overall_attention_level is AttentionLevel.URGENT


def test_summary_risk_downgrade_causes_visible_failure() -> None:
    orchestrator, _ = build(summary_agent=FakeSummary(downgrade=True))
    state = orchestrator.handle_patient_message("I have chest pain and breathlessness.")
    assert state.workflow_status is WorkflowStatus.PARTIAL_FAILURE
    assert state.physician_summary is None
    assert state.errors[-1].stage == "final_validation"


def test_absent_document_never_calls_document_stage() -> None:
    orchestrator, agents = build()
    orchestrator.handle_patient_message("I have a headache.")
    assert agents["document_agent"].calls == 0


def test_same_document_is_processed_once() -> None:
    orchestrator, agents = build()
    document = {"document_id": "d1", "ocr_text": "Synthetic OCR"}
    orchestrator.handle_patient_message("I have a headache.", documents=[document])
    state = orchestrator.handle_patient_message("It is 7/10.", documents=[document])
    assert len(state.documents) == 1
    assert agents["document_agent"].calls == 1


def test_multiple_documents_are_preserved() -> None:
    orchestrator, _ = build()
    state = orchestrator.handle_patient_message("I have a headache.", documents=[{"document_id": "d1", "ocr_text": "one"}, {"document_id": "d2", "ocr_text": "two"}])
    assert [document.document_id for document in state.documents] == ["d1", "d2"]


def test_document_failure_is_partial_and_does_not_fabricate_document() -> None:
    orchestrator, _ = build(document_agent=FakeDocument(fail=True))
    state = orchestrator.handle_patient_message("I have a headache.", documents=[{"document_id": "d1", "ocr_text": "one"}])
    assert state.workflow_status is WorkflowStatus.PARTIAL_FAILURE
    assert state.documents == []
    assert any(error.stage == "document" for error in state.errors)
    assert any("Document processing unavailable" in gap for gap in state.physician_summary.information_gaps)


def test_structuring_failure_does_not_claim_completed_history() -> None:
    orchestrator, _ = build(structuring_agent=FakeStructuring(fail=True))
    state = orchestrator.handle_patient_message("I have a headache.")
    assert state.workflow_status is WorkflowStatus.PARTIAL_FAILURE
    assert state.clinical_history is None
    assert state.physician_summary is None


def test_risk_failure_is_visible_and_not_no_risk() -> None:
    orchestrator, _ = build(risk_agent=FakeRisk(fail=True))
    state = orchestrator.handle_patient_message("I have a headache.")
    assert state.risk_assessment is None
    assert state.errors[-1].stage == "risk"


def test_summary_failure_preserves_prior_validated_outputs() -> None:
    orchestrator, _ = build(summary_agent=FakeSummary(fail=True))
    state = orchestrator.handle_patient_message("I have a headache.")
    assert state.clinical_history is not None and state.risk_assessment is not None
    assert state.physician_summary is None
    assert state.errors[-1].stage == "summary"


def test_empty_patient_input_is_controlled_failure() -> None:
    orchestrator, agents = build()
    state = orchestrator.handle_patient_message(" ")
    assert state.workflow_status is WorkflowStatus.FAILED
    assert state.errors[-1].stage == "interview"
    assert agents["interview_agent"].calls == 0


def test_invalid_document_input_is_visible() -> None:
    orchestrator, _ = build()
    state = orchestrator.handle_patient_message("I have a headache.", documents=[{"document_id": "bad"}])
    assert state.workflow_status is WorkflowStatus.PARTIAL_FAILURE
    assert any(error.stage == "document" for error in state.errors)


def test_medication_advice_in_summary_is_rejected() -> None:
    orchestrator, _ = build(summary_agent=FakeSummary(advice=True))
    state = orchestrator.handle_patient_message("I have a headache.")
    assert state.workflow_status is WorkflowStatus.PARTIAL_FAILURE
    assert state.physician_summary is None


def test_diagnosis_hallucination_in_summary_is_rejected() -> None:
    orchestrator, _ = build(summary_agent=FakeSummary(diagnosis=True))
    state = orchestrator.handle_patient_message("I have a headache.")
    assert state.workflow_status is WorkflowStatus.PARTIAL_FAILURE
    assert state.physician_summary is None
    assert state.errors[-1].stage == "final_validation"


def test_state_round_trip_serializes() -> None:
    orchestrator, _ = build()
    state = orchestrator.handle_patient_message("I have a headache.")
    restored = state.__class__.model_validate_json(state.model_dump_json())
    assert restored == state


def test_add_documents_does_not_restart_interview() -> None:
    orchestrator, agents = build()
    orchestrator.handle_patient_message("I have a headache.")
    state = orchestrator.add_documents([{"document_id": "d1", "ocr_text": "one"}])
    assert state.documents and agents["interview_agent"].calls == 1


def test_full_workflow_has_validated_output() -> None:
    orchestrator, agents = build()
    state = orchestrator.handle_patient_message("I have chest pain and breathlessness.", documents=[{"document_id": "d1", "ocr_text": "Metformin 500 mg"}])
    assert state.workflow_status is WorkflowStatus.COMPLETED
    assert state.clinical_history and state.risk_assessment and state.documents and state.physician_summary
    assert all(agent.calls >= 1 for agent in agents.values())
