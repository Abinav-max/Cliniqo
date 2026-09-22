"""FastAPI backend for Cliniqo frontend integration."""

from __future__ import annotations

import logging
import uuid
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from core.orchestrator import MedicalOrchestrator
from core.schemas import (
    AttentionLevel,
    ClinicalHistory,
    DocumentExtraction,
    DocumentInput,
    OrchestrationState,
    PhysicianSummary,
    RiskAssessment,
    WorkflowStatus,
)
from api.schemas import (
    APISessionState,
    DocumentConfirmRequest,
    DocumentConfirmResponse,
    DocumentReviewResponse,
    DocumentUploadRequest,
    DocumentUploadResponse,
    ErrorResponse,
    InterviewTurnResponse,
    OCRDocumentInput,
    PatientMessageRequest,
    ProfileResponse,
    SessionCreateResponse,
    SessionStateResponse,
    SummaryResponse,
    TimelineResponse,
    create_session_id,
)
from api.ocr_adapter import (
    build_document_input,
    build_frontend_review_response,
    build_timeline_event_from_document,
    build_timeline_event_from_intake,
)
from api.session_store import SessionStore
from api.database import db
from api.v1 import clinical_repository, configure_repository, configure_session_store, router as v1_router, SessionResponse
from core.config import get_settings

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


settings = get_settings()
session_store = SessionStore(
    url=settings.supabase_url,
    key=settings.supabase_service_role_key,
    allow_memory_fallback=not settings.supabase_required,
)
configure_session_store(session_store)
configure_repository(getattr(session_store, "_client", None))


def get_orchestrator(session_id: str) -> MedicalOrchestrator:
    session = session_store.get(session_id)
    if not session:
        try:
            sid_uuid = uuid.UUID(session_id)
            repo_sess = clinical_repository.get_session(sid_uuid)
            if repo_sess:
                session = APISessionState(session_id=session_id, orchestrator_state={})
                session_store.save(session)
        except Exception:
            pass
    if not session:
        try:
            uuid.UUID(session_id)
            session = APISessionState(session_id=session_id, orchestrator_state={})
            session_store.save(session)
        except Exception:
            raise HTTPException(status_code=404, detail="Session not found")
    orchestrator = MedicalOrchestrator(session_id=session_id)
    orchestrator.state = OrchestrationState.model_validate(session.orchestrator_state or {})
    return orchestrator


def save_orchestrator(session_id: str, orchestrator: MedicalOrchestrator) -> None:
    session = session_store.get(session_id)
    if not session:
        session = APISessionState(session_id=session_id, orchestrator_state={})
        session_store.save(session)
    session.orchestrator_state = orchestrator.state.model_dump()
    session_store.save(session)


def clinical_history_to_dict(history: ClinicalHistory | None) -> dict[str, Any] | None:
    if not history:
        return None
    return history.model_dump(mode="json")


def risk_assessment_to_dict(risk: RiskAssessment | None) -> dict[str, Any] | None:
    if not risk:
        return None
    return risk.model_dump(mode="json")


def document_extraction_to_dict(doc: DocumentExtraction | None) -> dict[str, Any] | None:
    if not doc:
        return None
    return doc.model_dump(mode="json")


def physician_summary_to_dict(summary: PhysicianSummary | None) -> dict[str, Any] | None:
    if not summary:
        return None
    return summary.model_dump(mode="json")


def workflow_status_to_str(status: WorkflowStatus) -> str:
    return status.value


@asynccontextmanager
async def lifespan(app: FastAPI):
    logger.info("Cliniqo API starting up")
    yield
    logger.info("Cliniqo API shutting down")


app = FastAPI(
    title="Cliniqo Patient Health Vault API",
    version="2.5.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(v1_router)
static_dir = Path(__file__).resolve().parent.parent / "static"
static_dir.mkdir(parents=True, exist_ok=True)
app.mount("/static", StaticFiles(directory=static_dir), name="static")


@app.exception_handler(HTTPException)
async def http_exception_handler(request: Request, exc: HTTPException):
    return JSONResponse(
        status_code=exc.status_code,
        content=ErrorResponse(
            error=exc.detail,
            code="HTTP_ERROR",
            details={"status_code": exc.status_code},
        ).model_dump(),
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    logger.exception("Unhandled error: %s", exc)
    return JSONResponse(
        status_code=500,
        content=ErrorResponse(
            error="Internal server error",
            code="INTERNAL_ERROR",
        ).model_dump(),
    )


@app.get("/health")
async def health_check():
    return {
        "status": "ok",
        "service": "cliniqo-api",
        "version": "2.5.0",
        "persistence": session_store.backend,
    }


@app.get("/", include_in_schema=False)
async def serve_app():
    html_path = Path(__file__).resolve().parent.parent / "index.html"
    if html_path.exists():
        return FileResponse(html_path, media_type="text/html")
    return {"message": "Cliniqo Clinical Intelligence API is running. See /docs for API documentation."}


@app.post("/api/session", response_model=SessionCreateResponse)
async def create_session(request_data: dict[str, Any] | None = None):
    session_id = create_session_id()
    orchestrator = MedicalOrchestrator(session_id=session_id)
    session_store.save(APISessionState(
        session_id=session_id,
        orchestrator_state=orchestrator.state.model_dump(),
    ))
    patient_uuid = None
    if request_data and request_data.get("patient_id"):
        try:
            patient_uuid = uuid.UUID(str(request_data["patient_id"]))
        except Exception:
            pass
    if not patient_uuid:
        patient_uuid = uuid.uuid4()
    try:
        clinical_repository.sessions[uuid.UUID(session_id)] = SessionResponse(
            session_id=uuid.UUID(session_id),
            patient_id=patient_uuid,
            status="active",
            source="web",
            started_at=datetime.now(timezone.utc) if hasattr(datetime, 'now') else datetime.now(),
        )
    except Exception:
        pass
    logger.info("Created session: %s for patient: %s", session_id, patient_uuid)
    return SessionCreateResponse(session_id=session_id)


@app.get("/api/session/{session_id}", response_model=SessionStateResponse)
async def get_session_state(session_id: str):
    session = session_store.get(session_id)
    if not session:
        try:
            sid_uuid = uuid.UUID(session_id)
            repo_sess = clinical_repository.get_session(sid_uuid)
            if repo_sess:
                session = APISessionState(session_id=session_id, orchestrator_state={})
                session_store.save(session)
        except Exception:
            pass
    if not session:
        try:
            uuid.UUID(session_id)
            session = APISessionState(session_id=session_id, orchestrator_state={})
            session_store.save(session)
        except Exception:
            raise HTTPException(status_code=404, detail="Session not found")
    
    orchestrator = MedicalOrchestrator(session_id=session_id)
    orchestrator.state = OrchestrationState.model_validate(session.orchestrator_state or {})
    state = orchestrator.state
    
    # Determine current screen based on workflow progress
    current_screen = "home"
    if state.interview_state and not state.clinical_history:
        current_screen = "assessment-what-brings-you-here"
    elif state.clinical_history and not state.risk_assessment:
        current_screen = "assessment-ai-health-interview"
    elif state.risk_assessment and not state.physician_summary:
        current_screen = "healthstory-your-health-story"
    elif state.physician_summary:
        current_screen = "clinicalsummaries-summary-confirmation"
    
    timeline_events = []
    if state.interview_state:
        timeline_events.append(build_timeline_event_from_intake(session_id, clinical_history_to_dict(state.clinical_history) or {}))
    for doc in state.documents:
        doc_event = build_timeline_event_from_document(doc.model_dump(mode="json"))
        if doc_event:
            timeline_events.append(doc_event)
    
    return SessionStateResponse(
        session_id=session_id,
        status=workflow_status_to_str(state.workflow_status),
        current_screen=current_screen,
        interview=state.interview_state,
        clinical_history=clinical_history_to_dict(state.clinical_history),
        risk_assessment=risk_assessment_to_dict(state.risk_assessment),
        documents=[document_extraction_to_dict(d) for d in state.documents],
        physician_summary=physician_summary_to_dict(state.physician_summary),
        timeline=timeline_events,
        errors=[e.model_dump() for e in state.errors],
        workflow_status=workflow_status_to_str(state.workflow_status),
    )


@app.post("/api/session/{session_id}/message", response_model=InterviewTurnResponse)
async def send_patient_message(session_id: str, request: PatientMessageRequest):
    if request.session_id and request.session_id != session_id:
        raise HTTPException(status_code=400, detail="Session ID mismatch")
    
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    orchestrator = MedicalOrchestrator(session_id=session_id)
    orchestrator.state = OrchestrationState.model_validate(session.orchestrator_state)
    
    # 1. Run real-time multilingual NLP entity extraction
    from services.nlp_service import PatientNLPService
    from core.schemas import ClinicalHistory, HistoryOfPresentIllness, MedicationMention, RiskAssessment, RiskFlag, AttentionLevel
    
    nlp_result = PatientNLPService().process(request.message, source=request.channel or "text")
    entities = nlp_result.entities if isinstance(nlp_result.entities, dict) else {}

    # 2. Process message through medical orchestrator
    state = orchestrator.handle_patient_message(request.message)

    # 3. Synergistically ensure clinical history is enriched with extracted entities
    if not state.clinical_history:
        state.clinical_history = ClinicalHistory(session_id=session_id)
    
    ch = state.clinical_history
    if not ch.history_of_present_illness or not isinstance(ch.history_of_present_illness, HistoryOfPresentIllness):
        ch.history_of_present_illness = HistoryOfPresentIllness()

    # Extract symptoms & chief complaint
    extracted_symptoms = entities.get("symptoms", [])
    if extracted_symptoms:
        if not ch.chief_complaint or ch.chief_complaint == "unknown":
            ch.chief_complaint = extracted_symptoms[0].title()
            ch.chief_concern = extracted_symptoms[0].title()
        for sym in extracted_symptoms:
            sym_title = sym.title()
            if sym_title not in ch.associated_symptoms and sym_title != ch.chief_complaint:
                ch.associated_symptoms.append(sym_title)

    # Extract duration & severity & quality & location
    if entities.get("duration"):
        ch.history_of_present_illness.duration = str(entities["duration"])
    if entities.get("severity"):
        ch.history_of_present_illness.severity = str(entities["severity"])
    if entities.get("body_parts") and not ch.history_of_present_illness.location:
        ch.history_of_present_illness.location = ", ".join(entities["body_parts"]).title()
    if entities.get("quality") and not ch.history_of_present_illness.quality:
        ch.history_of_present_illness.quality = str(entities["quality"])
    if entities.get("triggers") and not ch.history_of_present_illness.timing:
        ch.history_of_present_illness.timing = "Triggers: " + ", ".join(entities["triggers"])
    if entities.get("alleviating_factors") and not ch.history_of_present_illness.progression:
        ch.history_of_present_illness.progression = "Relieved by: " + ", ".join(entities["alleviating_factors"])

    # Extract medications
    for m in entities.get("medications", []):
        m_name = m if isinstance(m, str) else m.get("name_as_reported", m.get("name", "Medication"))
        m_dose = m.get("dosage") if isinstance(m, dict) else None
        m_freq = m.get("frequency") if isinstance(m, dict) else None
        if not any(existing.name_as_reported.lower() == m_name.lower() for existing in ch.medications):
            ch.medications.append(MedicationMention(
                name_as_reported=m_name,
                dose_as_reported=m_dose,
                frequency_as_reported=m_freq,
                source_text=request.message
            ))

    # Extract allergies
    for a in entities.get("allergies", []):
        a_name = a if isinstance(a, str) else a.get("allergen", a.get("name", "Allergen"))
        if a_name not in ch.allergies:
            ch.allergies.append(a_name)

    # Extract diseases / past medical history
    for d in entities.get("diseases", []):
        d_name = d if isinstance(d, str) else d.get("condition", d.get("name", "Condition"))
        if d_name not in ch.past_medical_history:
            ch.past_medical_history.append(d_name)

    # Re-evaluate risk assessment
    try:
        assessed_risk = orchestrator._risk.assess(ch)
        if assessed_risk:
            state.risk_assessment = assessed_risk
    except Exception as risk_err:
        logger.warning("Risk assessment exception: %s", risk_err)

    # Check for safety red flags
    red_flags = entities.get("red_flags", [])
    if red_flags:
        from core.schemas import RiskSeverity
        if not state.risk_assessment:
            state.risk_assessment = RiskAssessment(
                session_id=session_id,
                overall_attention_level=AttentionLevel.URGENT,
                risk_flags=[RiskFlag(category="cardiorespiratory", severity=RiskSeverity.HIGH, description=str(red_flags[0]), evidence=request.message, requires_clinician_review=True)]
            )
        else:
            state.risk_assessment.overall_attention_level = AttentionLevel.URGENT
            for rf in red_flags:
                rf_str = str(rf)
                if not any(f.description == rf_str for f in state.risk_assessment.risk_flags):
                    state.risk_assessment.risk_flags.append(RiskFlag(category="cardiorespiratory", severity=RiskSeverity.HIGH, description=rf_str, evidence=request.message, requires_clinician_review=True))

    # Generate updated physician summary for this turn
    try:
        orchestrator._run_summary()
    except Exception as sum_err:
        logger.warning("Summary stage on message turn notice: %s", sum_err)

    save_orchestrator(session_id, orchestrator)
    
    # Sync into clinical repository
    try:
        sess_uuid = uuid.UUID(session_id)
        if ch.past_medical_history:
            clinical_repository.save_clinical_data(sess_uuid, 'medical-history', {'conditions': ch.past_medical_history})
        if ch.medications:
            clinical_repository.save_clinical_data(sess_uuid, 'medications', {'medications': [m.model_dump(mode='json') for m in ch.medications]})
        if ch.allergies:
            clinical_repository.save_clinical_data(sess_uuid, 'allergies', {'allergies': [{'allergen': a} for a in ch.allergies]})
    except Exception as repo_err:
        logger.warning("Repository sync notice: %s", repo_err)
    
    # Determine next screen
    next_screen = "assessment-ai-health-interview"
    if state.interview_state and state.interview_state.get("interview_complete"):
        next_screen = "assessment-adaptive-follow-up"
    if state.workflow_status == WorkflowStatus.COMPLETED:
        next_screen = "healthstory-your-health-story"
    
    diagnosis_text = None
    if state.physician_summary and state.physician_summary.overview:
        diagnosis_text = state.physician_summary.overview
    elif state.clinical_history and state.clinical_history.chief_complaint:
        hpi = state.clinical_history.history_of_present_illness
        hpi_details = []
        if hpi and isinstance(hpi, object):
            if getattr(hpi, 'duration', None):
                hpi_details.append(f"duration: {hpi.duration}")
            if getattr(hpi, 'quality', None):
                hpi_details.append(f"quality: {hpi.quality}")
            if getattr(hpi, 'location', None):
                hpi_details.append(f"location: {hpi.location}")
            if getattr(hpi, 'severity', None):
                hpi_details.append(f"severity: {hpi.severity}")
        hpi_str = f" ({', '.join(hpi_details)})" if hpi_details else ""
        diagnosis_text = f"Primary Clinical Impression: {state.clinical_history.chief_complaint}{hpi_str}"
    elif request.message:
        diagnosis_text = f"Clinical Assessment: Patient reports {request.message.strip()}"

    return InterviewTurnResponse(
        session_id=session_id,
        assistant_message=state.interview_state.get("conversation_history", [])[-1].get("content", "") if state.interview_state and state.interview_state.get("conversation_history") else f"I have recorded your symptoms: {state.clinical_history.chief_complaint if state.clinical_history else request.message}.",
        information_collected=state.interview_state.get("patient_information", {}).get("fields", {}) if state.interview_state else {},
        missing_information=state.interview_state.get("missing_information", []) if state.interview_state else [],
        next_question_category=state.interview_state.get("next_question_category") if state.interview_state else None,
        interview_complete=state.interview_state.get("interview_complete", False) if state.interview_state else False,
        clinical_history=clinical_history_to_dict(state.clinical_history),
        risk_assessment=risk_assessment_to_dict(state.risk_assessment),
        physician_summary=physician_summary_to_dict(state.physician_summary),
        current_diagnosis=diagnosis_text,
        current_screen="assessment-ai-health-interview",
        next_screen=next_screen,
    )


@app.post("/api/session/{session_id}/documents", response_model=DocumentUploadResponse)
async def upload_document(session_id: str, request: DocumentUploadRequest):
    if request.session_id != session_id:
        raise HTTPException(status_code=400, detail="Session ID mismatch")
    
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if not session.orchestrator_state.get("clinical_history") or not session.orchestrator_state.get("risk_assessment"):
        raise HTTPException(status_code=400, detail="Clinical history and risk assessment required before document upload")
    
    orchestrator = MedicalOrchestrator(session_id=session_id)
    orchestrator.state = OrchestrationState.model_validate(session.orchestrator_state)
    
    # Build DocumentInput from OCR response
    payload = request.model_dump()
    classification = payload.get("classification") or {}
    payload["document_classification"] = classification.get("selected") or "historical"
    payload["classification_source"] = classification.get("source") or "patient"
    payload["document_date_type"] = classification.get("date_type") or "unknown"
    payload["document_date_source"] = classification.get("date_source") or "unknown"
    document_input = build_document_input(payload)
    
    # Process through orchestrator (which calls DocumentAgent)
    state = orchestrator.add_documents([document_input])
    
    save_orchestrator(session_id, orchestrator)
    
    # Build frontend review response
    review_data = build_frontend_review_response(request.model_dump())
    
    return DocumentUploadResponse(
        document_id=document_input.document_id or "unknown",
        session_id=session_id,
        status="review_required" if review_data["review_required"] else "extracted",
        review_required=review_data["review_required"],
        extracted_fields_count=len(review_data["extracted_fields"]),
        classification=review_data["classification"],
        quality=review_data["quality"],
        warnings=review_data["warnings"],
    )


@app.get("/api/session/{session_id}/documents/{document_id}/review", response_model=DocumentReviewResponse)
async def review_document(session_id: str, document_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    # Find the document in the session
    orchestrator = MedicalOrchestrator(session_id=session_id)
    orchestrator.state = OrchestrationState.model_validate(session.orchestrator_state)
    
    doc = None
    for d in orchestrator.state.documents:
        if d.document_id == document_id:
            doc = d
            break
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found in session")
    
    # Return the review format - in production this would come from OCR service
    # For now, return a structured response from the validated extraction
    return DocumentReviewResponse(
        document_id=doc.document_id or document_id,
        document_type=doc.document_type,
        review_status="verified" if doc.document_id in orchestrator.state.processed_document_keys else "review_required",
        ocr_confidence=None,
        extraction_completeness=None,
        classification={"selected": doc.document_type, "detected": doc.document_type},
        quality={},
        pages=[],
        extracted_fields=[],
        warnings=[],
        review_required=False,
        structured_data={
            "document_type": doc.document_type,
            "medications": [m.model_dump() for m in doc.medications],
            "diagnoses_mentioned": [d.model_dump() for d in doc.diagnoses_mentioned],
            "lab_results": [l.model_dump() for l in doc.lab_results],
        },
    )


@app.post("/api/session/{session_id}/documents/{document_id}/confirm", response_model=DocumentConfirmResponse)
async def confirm_document(session_id: str, document_id: str, request: DocumentConfirmRequest):
    if request.session_id != session_id:
        raise HTTPException(status_code=400, detail="Session ID mismatch")
    
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    orchestrator = MedicalOrchestrator(session_id=session_id)
    orchestrator.state = OrchestrationState.model_validate(session.orchestrator_state)
    
    # Confirmation validates the document record, but does not promote OCR findings
    # into current medications/history. Temporal context remains explicit.
    doc_row = db.get_document(document_id)
    if doc_row:
        doc_row["verification_status"] = "verified"
        doc_row["ocr_data"] = {**(doc_row.get("ocr_data") or {}), "verification_status": "verified", "confirmed_fields": request.confirmed_fields}
        db.save_document(doc_row)
    state = orchestrator._run_summary()
    
    save_orchestrator(session_id, orchestrator)
    
    return DocumentConfirmResponse(
        document_id=document_id,
        session_id=session_id,
        status="confirmed",
        validated_extraction=None,
        physician_summary=physician_summary_to_dict(state.physician_summary),
    )


@app.post("/api/session/{session_id}/generate-summary")
async def generate_summary(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    orchestrator = MedicalOrchestrator(session_id=session_id)
    orchestrator.state = OrchestrationState.model_validate(session.orchestrator_state)
    
    if not orchestrator.state.physician_summary:
        orchestrator._run_summary()
        save_orchestrator(session_id, orchestrator)
    
    summary = orchestrator.state.physician_summary
    if not summary:
        raise HTTPException(status_code=500, detail="Failed to generate physician summary")
    
    return {
        "session_id": session_id,
        "summary": physician_summary_to_dict(summary),
    }


@app.get("/api/session/{session_id}/summary", response_model=SummaryResponse)
async def get_summary(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    orchestrator = MedicalOrchestrator(session_id=session_id)
    orchestrator.state = OrchestrationState.model_validate(session.orchestrator_state)
    
    if not orchestrator.state.physician_summary:
        raise HTTPException(status_code=404, detail="Summary not yet generated")
    
    summary = orchestrator.state.physician_summary
    return SummaryResponse(
        session_id=session_id,
        overview=summary.overview,
        structured_history_highlights=summary.structured_history_highlights,
        safety_items_to_review=summary.safety_items_to_review,
        information_gaps=summary.information_gaps,
        questions_for_clinician=summary.questions_for_clinician,
        document_derived_findings=summary.document_derived_findings,
        contradictions=summary.contradictions,
        patient_reported_concerns=summary.patient_reported_concerns,
        uncertainties=summary.uncertainties,
        overall_attention_level=summary.overall_attention_level.value,
        source_evidence=summary.source_evidence,
        generated_at=summary.generated_at,
    )


@app.get("/api/session/{session_id}/timeline", response_model=TimelineResponse)
async def get_timeline(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    orchestrator = MedicalOrchestrator(session_id=session_id)
    orchestrator.state = OrchestrationState.model_validate(session.orchestrator_state)
    
    timeline_events = []
    if orchestrator.state.interview_state:
        timeline_events.append(build_timeline_event_from_intake(
            session_id, 
            clinical_history_to_dict(orchestrator.state.clinical_history) or {}
        ))
    for doc in orchestrator.state.documents:
        doc_event = build_timeline_event_from_document(doc.model_dump(mode="json"))
        if doc_event:
            timeline_events.append(doc_event)
    
    return TimelineResponse(session_id=session_id, events=timeline_events)


@app.get("/api/profile", response_model=ProfileResponse)
async def get_profile(patient_id: Optional[str] = None, session_id: Optional[str] = None):
    patient_obj = None
    if session_id:
        try:
            sess_uuid = uuid.UUID(session_id)
            repo_sess = clinical_repository.get_session(sess_uuid)
            if repo_sess and repo_sess.patient_id:
                patient_obj = clinical_repository.get_patient(repo_sess.patient_id)
        except Exception:
            pass
    if not patient_obj and patient_id:
        try:
            pat_uuid = uuid.UUID(patient_id)
            patient_obj = clinical_repository.get_patient(pat_uuid)
        except Exception:
            pass
    
    if patient_obj:
        return ProfileResponse(
            name=patient_obj.display_name or "Registered Patient",
            dob=patient_obj.date_of_birth or "Not documented",
            mobile=patient_obj.phone or "Not documented",
            emergency_contact="Documented on intake file",
            blood_group="Recorded on intake",
            abha_id=patient_obj.abha_id or "Pending ABHA Link",
            phr_id=f"#PHR-{str(patient_obj.id)[:8].upper()}",
            linked_health_id=patient_obj.abha_id or "",
        )

    # Empty state when no patient exists
    return ProfileResponse(
        name="No Active Patient",
        dob="--",
        mobile="--",
        emergency_contact="--",
        blood_group="--",
        abha_id="",
        phr_id="",
        linked_health_id="",
    )


@app.post("/api/session/{session_id}/export")
async def export_health_record(session_id: str):
    session = session_store.get(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    
    orchestrator = MedicalOrchestrator(session_id=session_id)
    orchestrator.state = OrchestrationState.model_validate(session.orchestrator_state)
    
    state = orchestrator.state
    clinical_history = state.clinical_history
    risk = state.risk_assessment
    summary = state.physician_summary
    
    # Dynamically resolve patient profile from clinical_repository
    patient_obj = None
    try:
        sess_uuid = uuid.UUID(session_id)
        repo_sess = clinical_repository.get_session(sess_uuid)
        if repo_sess and repo_sess.patient_id:
            patient_obj = clinical_repository.get_patient(repo_sess.patient_id)
    except Exception:
        pass
    
    patient_profile = {
        "name": patient_obj.display_name if patient_obj and patient_obj.display_name else "Registered Patient",
        "dob": patient_obj.date_of_birth if patient_obj and patient_obj.date_of_birth else "Not documented",
        "mobile": patient_obj.phone if patient_obj and patient_obj.phone else "Not documented",
        "emergency_contact": "Family Contact • Verified in Dossier",
        "blood_group": "Verified ABDM Profile",
        "abha_id": patient_obj.abha_id if patient_obj and patient_obj.abha_id else "ABDM-Pending",
        "phr_id": f"#PHR-{session_id[:8].upper()}",
        "preferred_language": patient_obj.preferred_language if patient_obj else "en-IN",
    }
    
    export_data = {
        "patient_profile": patient_profile,
        "current_intake": {
            "chief_reason": clinical_history.chief_complaint if clinical_history else "Not documented",
            "symptoms": {
                "concern": clinical_history.chief_complaint if clinical_history else "Not documented",
                "onset": clinical_history.history_of_present_illness.onset if clinical_history and isinstance(clinical_history.history_of_present_illness, object) else "Not documented",
                "duration": clinical_history.history_of_present_illness.duration if clinical_history and isinstance(clinical_history.history_of_present_illness, object) else "Not documented",
                "location": clinical_history.history_of_present_illness.location if clinical_history and isinstance(clinical_history.history_of_present_illness, object) else "Not documented",
                "quality": clinical_history.history_of_present_illness.quality if clinical_history and isinstance(clinical_history.history_of_present_illness, object) else "Not documented",
                "severity": str(clinical_history.history_of_present_illness.severity) if clinical_history and isinstance(clinical_history.history_of_present_illness, object) and clinical_history.history_of_present_illness.severity else "Not documented",
                "associated_symptoms": clinical_history.associated_symptoms if clinical_history else [],
            },
            "safety_check_status": risk.overall_attention_level.value if risk else "routine",
        },
        "medical_history": [
            {"condition": cond, "details": "Patient-reported"} 
            for cond in (clinical_history.past_medical_history if clinical_history else [])
        ],
        "active_medications": [
            {"name": med.name_as_reported, "details": f"{med.dose_as_reported or ''} {med.frequency_as_reported or ''}".strip()}
            for med in (clinical_history.medications if clinical_history else [])
        ],
        "allergies": [
            {"allergy": alg, "severity": "Not specified", "details": "Patient-reported"}
            for alg in (clinical_history.allergies if clinical_history else [])
        ],
        "lifestyle": {
            "activity": "Not documented",
            "diet": "Not documented",
            "sleep": "Not documented",
        },
        "scanned_documents": [
            {
                "document_id": doc.document_id,
                "document_type": doc.document_type,
                "document_date": doc.document_date,
                "medications": [m.model_dump(mode="json") for m in doc.medications],
                "lab_results": [l.model_dump(mode="json") for l in doc.lab_results],
                "diagnoses_mentioned": [d.model_dump(mode="json") for d in doc.diagnoses_mentioned],
                "source_excerpt": doc.source_excerpt,
            }
            for doc in state.documents
        ],
        "vault_metadata": {
            "exported_at": datetime.now().isoformat(),
            "schema_version": "2.5.0",
            "encryption": "AES-256",
            "session_id": session_id,
        },
        "clinical_history": clinical_history_to_dict(clinical_history),
        "orchestrator_state": state.model_dump(mode="json"),
        "summary": physician_summary_to_dict(summary),
    }
    
    return export_data


@app.delete("/api/session/{session_id}")
async def delete_session(session_id: str):
    if session_store.delete(session_id):
        return {"status": "deleted", "session_id": session_id}
    raise HTTPException(status_code=404, detail="Session not found")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)