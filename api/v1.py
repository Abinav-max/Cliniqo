from __future__ import annotations

import logging
import json
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from fastapi import APIRouter, File, HTTPException, UploadFile
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)

from api.auth import (
    AuthLoginRequest,
    AuthRegisterRequest,
    AuthResponse,
    ChangeEmailRequest,
    ChangePasswordRequest,
    ProfileUpdateRequest,
    SendVerificationCodeRequest,
    UserProfile,
    UserRecord,
    email_verification_service,
    hash_password,
    verify_password,
)
from api.database import db, DB_DIR
from api.schemas import APISessionState
from api.session_store import SessionStore
from core.orchestrator import MedicalOrchestrator
from services.ocr_service import LocalOCRService, OCRServiceError
from services.nlp_service import PatientNLPService
from services.storage_service import StorageServiceError, SupabaseStorageService
from services.triage_service import DeterministicTriageService


router = APIRouter(prefix="/api/v1", tags=["Cliniqo v1"])


class PatientCreateRequest(BaseModel):
    abha_id: str | None = None
    display_name: str | None = None
    date_of_birth: str | None = None
    phone: str | None = None
    gender: str | None = None
    emergency_contact: str | None = None
    blood_group: str | None = None
    preferred_language: str | None = None


class PatientResponse(PatientCreateRequest):
    patient_id: UUID
    created_at: datetime
    updated_at: datetime


class PatientUpdateRequest(BaseModel):
    abha_id: str | None = None
    display_name: str | None = None
    date_of_birth: str | None = None
    phone: str | None = None
    gender: str | None = None
    emergency_contact: str | None = None
    blood_group: str | None = None
    preferred_language: str | None = None


class SessionCreateRequest(BaseModel):
    patient_id: UUID
    source: str = "web"
    department: str = "general"
    opd_mode: str = "general"
    token_number: int | None = None
    triage_level: str = "routine"
    consent_given: bool = False
    language_preference: str = "en"


class SessionResponse(SessionCreateRequest):
    session_id: UUID
    status: str
    started_at: datetime
    completed_at: datetime | None = None
    doctor_verified: bool = False
    doctor_notes: str | None = None
    doctor_verified_at: str | None = None


class MessageCreateRequest(BaseModel):
    role: str = Field(pattern="^(patient|kiosk|doctor|assistant|system)$")
    content: str
    source: str = "text"
    language: str | None = None
    confidence: float | None = None


class MessageResponse(MessageCreateRequest):
    message_id: UUID
    session_id: UUID
    created_at: datetime
    assistant_message: str | None = None


class TranscriptRequest(BaseModel):
    text: str
    language: str | None = None
    confidence: float | None = 1.0


class LanguageProcessResponse(BaseModel):
    text: str
    language: str | None = None
    confidence: float = 1.0
    source: str = "voice"
    processing_status: str = "completed"
    entities: dict[str, Any] = Field(default_factory=dict)
    red_flags: list[dict[str, Any]] = Field(default_factory=list)


class RedFlagCreateRequest(BaseModel):
    category: str
    severity: str
    reason: str
    source: str
    is_resolved: bool = False


class RedFlagResponse(RedFlagCreateRequest):
    red_flag_id: UUID
    session_id: UUID
    created_at: datetime


class ConsentCreateRequest(BaseModel):
    consent_type: str
    granted: bool
    consent_version: str = "1.0"
    recorded_by: str = "patient"


class ConsentResponse(ConsentCreateRequest):
    consent_id: UUID
    session_id: UUID
    created_at: datetime


class SummaryResponseV1(BaseModel):
    session_id: UUID
    content: dict[str, Any]
    clinician_reviewed: bool = False
    updated_at: datetime


class DataPayload(BaseModel):
    data: dict[str, Any]


class DocumentResponse(BaseModel):
    document_id: UUID
    session_id: UUID
    file_name: str
    file_type: str
    file_size: int
    storage_path: str
    upload_status: str
    ocr_status: str
    document_type: str | None = None
    ocr: dict[str, Any] | None = None
    document_classification: str = "historical"
    classification_source: str = "patient"
    document_date: str | None = None
    document_date_type: str = "unknown"
    document_date_source: str = "unknown"
    temporal_status: str = "unknown"
    verification_status: str = "pending"
    created_at: datetime


class ClinicalRepository:
    """Production clinical repository; uses persistent SQLite database with Supabase synchronization."""

    def __init__(self, client: Any = None) -> None:
        self.client = client
        self.patients: dict[UUID, PatientResponse] = {}
        self.sessions: dict[UUID, SessionResponse] = {}
        self.messages: dict[UUID, list[MessageResponse]] = {}
        self.clinical_data: dict[UUID, dict[str, dict[str, Any]]] = {}
        self.red_flags: dict[UUID, list[RedFlagResponse]] = {}
        self.consents: dict[UUID, list[ConsentResponse]] = {}
        self.summaries: dict[UUID, SummaryResponseV1] = {}
        self.doctor_cases: dict[UUID, dict[str, Any]] = {}
        self.documents: dict[UUID, DocumentResponse] = {}
        self.document_contents: dict[UUID, bytes] = {}
        self.users: dict[UUID, UserRecord] = {}
        self._warm_up_from_db()

    def _warm_up_from_db(self) -> None:
        """Warm up local in-memory dictionaries from the persistent SQLite store."""
        try:
            db.ensure_default_hospital_user()
            for u in db.list_users():
                try:
                    uid = UUID(u["user_id"])
                    self.users[uid] = UserRecord(
                        user_id=uid,
                        email=u["email"],
                        display_name=u["display_name"],
                        avatar_url=u.get("avatar_url"),
                        patient_id=UUID(u["patient_id"]) if u.get("patient_id") else None,
                        role=u.get("role", "patient"),
                        password_hash=u["password_hash"],
                        password_salt=u["password_salt"],
                        created_at=datetime.fromisoformat(u["created_at"]) if isinstance(u["created_at"], str) else u["created_at"],
                        updated_at=datetime.fromisoformat(u["updated_at"]) if isinstance(u["updated_at"], str) else u["updated_at"],
                    )
                except Exception as ex:
                    logger.debug("Warmup user skip: %s", ex)

            for p in db.list_patients():
                try:
                    pid = UUID(p["patient_id"])
                    self.patients[pid] = PatientResponse(
                        patient_id=pid,
                        abha_id=p.get("abha_id"),
                        display_name=p.get("display_name"),
                        date_of_birth=p.get("date_of_birth"),
                        gender=p.get("gender"),
                        phone=p.get("phone"),
                        emergency_contact=p.get("emergency_contact"),
                        blood_group=p.get("blood_group"),
                        preferred_language=p.get("preferred_language", "en-IN"),
                        created_at=datetime.fromisoformat(p["created_at"]) if isinstance(p["created_at"], str) else p["created_at"],
                        updated_at=datetime.fromisoformat(p["updated_at"]) if isinstance(p["updated_at"], str) else p["updated_at"],
                    )
                except Exception as ex:
                    logger.debug("Warmup patient skip: %s", ex)

            for s in db.list_all_sessions():
                try:
                    sid = UUID(s["session_id"])
                    self.sessions[sid] = SessionResponse(
                        session_id=sid,
                        patient_id=UUID(s["patient_id"]),
                        status=s.get("status", "active"),
                        source=s.get("source", "web"),
                        started_at=datetime.fromisoformat(s["started_at"]) if isinstance(s["started_at"], str) else s["started_at"],
                        completed_at=datetime.fromisoformat(s["completed_at"]) if s.get("completed_at") and isinstance(s["completed_at"], str) else None,
                        department=s.get("department", "general"),
                        opd_mode=s.get("opd_mode", "general"),
                        token_number=int(s.get("token_number") or 0),
                        triage_level=s.get("triage_level", "routine"),
                        consent_given=bool(s.get("consent_given", 0)),
                        language_preference=s.get("language_preference", "en"),
                        doctor_verified=bool(s.get("doctor_verified", 0)),
                        doctor_notes=s.get("doctor_notes"),
                        doctor_verified_at=s.get("doctor_verified_at"),
                    )
                except Exception as ex:
                    logger.debug("Warmup session skip: %s", ex)
        except Exception as exc:
            logger.warning("Error during database warmup: %s", exc)

    def create_user(self, request: AuthRegisterRequest) -> tuple[UserRecord, SessionResponse]:
        norm_email = request.email.lower().strip()
        existing = self.get_user_by_email(norm_email)
        if existing:
            raise HTTPException(status_code=400, detail="An account with this email address already exists")
        
        p_hash, p_salt = hash_password(request.password)
        now = datetime.now(timezone.utc)
        patient = self.create_patient(PatientCreateRequest(
            display_name=request.display_name,
            preferred_language="en-IN"
        ))
        session = self.create_session(SessionCreateRequest(patient_id=patient.patient_id, source="web"))
        user = UserRecord(
            user_id=uuid4(),
            email=norm_email,
            display_name=request.display_name,
            avatar_url=request.avatar_url,
            patient_id=patient.patient_id,
            role=request.role or "patient",
            password_hash=p_hash,
            password_salt=p_salt,
            created_at=now,
            updated_at=now,
        )
        self.users[user.user_id] = user
        db.save_user(user.model_dump(mode="json"))
        return user, session

    def get_user_by_email(self, email: str) -> UserRecord | None:
        norm_email = email.lower().strip()
        user = next((u for u in self.users.values() if u.email.lower().strip() == norm_email), None)
        if user:
            return user
        db_user = db.get_user_by_email(norm_email)
        if db_user:
            try:
                uid = UUID(db_user["user_id"])
                user = UserRecord(
                    user_id=uid,
                    email=db_user["email"],
                    display_name=db_user["display_name"],
                    avatar_url=db_user.get("avatar_url"),
                    patient_id=UUID(db_user["patient_id"]) if db_user.get("patient_id") else None,
                    role=db_user.get("role", "patient"),
                    password_hash=db_user["password_hash"],
                    password_salt=db_user["password_salt"],
                    created_at=datetime.fromisoformat(db_user["created_at"]) if isinstance(db_user["created_at"], str) else db_user["created_at"],
                    updated_at=datetime.fromisoformat(db_user["updated_at"]) if isinstance(db_user["updated_at"], str) else db_user["updated_at"],
                )
                self.users[uid] = user
                return user
            except Exception:
                pass
        return None

    def get_user_by_id(self, user_id: UUID) -> UserRecord | None:
        if user_id in self.users:
            return self.users[user_id]
        db_user = db.get_user_by_id(str(user_id))
        if db_user:
            try:
                uid = UUID(db_user["user_id"])
                user = UserRecord(
                    user_id=uid,
                    email=db_user["email"],
                    display_name=db_user["display_name"],
                    avatar_url=db_user.get("avatar_url"),
                    patient_id=UUID(db_user["patient_id"]) if db_user.get("patient_id") else None,
                    role=db_user.get("role", "patient"),
                    password_hash=db_user["password_hash"],
                    password_salt=db_user["password_salt"],
                    created_at=datetime.fromisoformat(db_user["created_at"]) if isinstance(db_user["created_at"], str) else db_user["created_at"],
                    updated_at=datetime.fromisoformat(db_user["updated_at"]) if isinstance(db_user["updated_at"], str) else db_user["updated_at"],
                )
                self.users[uid] = user
                return user
            except Exception:
                pass
        return None

    def authenticate_user(self, request: AuthLoginRequest) -> tuple[UserRecord, SessionResponse] | None:
        user = self.get_user_by_email(request.email)
        if not user:
            return None
        if not verify_password(request.password, user.password_hash, user.password_salt):
            return None
        
        # Find or create active session for this user's patient
        patient_id = user.patient_id or uuid4()
        active_sess = None
        for s in reversed(list(self.sessions.values())):
            if s.patient_id == patient_id and s.status == "active":
                active_sess = s
                break
        if not active_sess:
            db_sessions = db.list_sessions_for_patient(str(patient_id))
            for s_row in db_sessions:
                if s_row.get("status") == "active":
                    try:
                        sid = UUID(s_row["session_id"])
                        active_sess = SessionResponse(
                            session_id=sid,
                            patient_id=patient_id,
                            status="active",
                            source=s_row.get("source", "web"),
                            started_at=datetime.fromisoformat(s_row["started_at"]) if isinstance(s_row["started_at"], str) else s_row["started_at"],
                        )
                        self.sessions[sid] = active_sess
                        break
                    except Exception:
                        pass
        if not active_sess:
            active_sess = self.create_session(SessionCreateRequest(patient_id=patient_id, source="web"))
        return user, active_sess

    def update_user_profile(self, user_id: UUID, request: ProfileUpdateRequest) -> UserRecord:
        user = self.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User account not found")
        
        if request.email and request.email.lower().strip() != user.email.lower().strip():
            existing = self.get_user_by_email(request.email)
            if existing and existing.user_id != user_id:
                raise HTTPException(status_code=400, detail="Email address is already in use by another account")
            user.email = request.email.lower().strip()
            
        if request.display_name:
            user.display_name = request.display_name.strip()
            if user.patient_id:
                p = self.get_patient(user.patient_id)
                if p:
                    self.update_patient(user.patient_id, PatientUpdateRequest(display_name=user.display_name))
                
        if request.avatar_url is not None:
            user.avatar_url = request.avatar_url if request.avatar_url != "" else None
            
        user.updated_at = datetime.now(timezone.utc)
        self.users[user.user_id] = user
        db.save_user(user.model_dump(mode="json"))
        return user

    def change_user_password(self, user_id: UUID, request: ChangePasswordRequest) -> bool:
        user = self.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User account not found")
        
        if not verify_password(request.current_password, user.password_hash, user.password_salt):
            raise HTTPException(status_code=400, detail="Current password is incorrect")
            
        if not email_verification_service.verify_code(user.email, request.verification_code):
            raise HTTPException(status_code=400, detail="Invalid or expired email verification code. Please request a new code.")
            
        p_hash, p_salt = hash_password(request.new_password)
        user.password_hash = p_hash
        user.password_salt = p_salt
        user.updated_at = datetime.now(timezone.utc)
        self.users[user.user_id] = user
        db.save_user(user.model_dump(mode="json"))
        return True

    def change_user_email(self, user_id: UUID, request: ChangeEmailRequest) -> UserRecord:
        user = self.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User account not found")

        if not verify_password(request.current_password, user.password_hash, user.password_salt):
            raise HTTPException(status_code=400, detail="Current password is incorrect")

        new_email = request.new_email.lower().strip()
        if new_email == user.email.lower().strip():
            raise HTTPException(status_code=400, detail="New email is the same as the current email")

        existing = self.get_user_by_email(new_email)
        if existing and existing.user_id != user.user_id:
            raise HTTPException(status_code=400, detail="Email address is already in use by another account")

        if not email_verification_service.verify_code(new_email, request.verification_code):
            raise HTTPException(status_code=400, detail="Invalid or expired email verification code. Please request a new code sent to {}.".format(new_email))

        user.email = new_email
        user.updated_at = datetime.now(timezone.utc)
        self.users[user.user_id] = user
        db.save_user(user.model_dump(mode="json"))
        return user

    def get_user_patient_history(self, user_id: UUID) -> dict[str, Any]:
        user = self.get_user_by_id(user_id)
        if not user:
            raise HTTPException(status_code=404, detail="User not found")
        
        patient = self.get_patient(user.patient_id) if user.patient_id else None
        patient_sessions = [s for s in self.sessions.values() if s.patient_id == user.patient_id]
        if not patient_sessions and user.patient_id:
            for s_row in db.list_sessions_for_patient(str(user.patient_id)):
                try:
                    sid = UUID(s_row["session_id"])
                    s_resp = SessionResponse(
                        session_id=sid,
                        patient_id=user.patient_id,
                        status=s_row.get("status", "active"),
                        source=s_row.get("source", "web"),
                        started_at=datetime.fromisoformat(s_row["started_at"]) if isinstance(s_row["started_at"], str) else s_row["started_at"],
                    )
                    self.sessions[sid] = s_resp
                    patient_sessions.append(s_resp)
                except Exception:
                    pass
        
        all_docs = []
        all_messages = []
        for s in patient_sessions:
            all_docs.extend(self.get_documents(s.session_id))
            all_messages.extend(self.get_messages(s.session_id))
            
        return {
            "user": user.model_dump(mode="json", exclude={"password_hash", "password_salt"}),
            "patient": patient.model_dump(mode="json") if patient else None,
            "sessions": [s.model_dump(mode="json") for s in patient_sessions],
            "documents": [d.model_dump(mode="json") for d in all_docs],
            "total_messages": len(all_messages),
        }

    def create_patient(self, request: PatientCreateRequest) -> PatientResponse:
        if request.abha_id:
            existing = self.find_patient_by_abha(request.abha_id)
            if existing:
                return existing
        now = datetime.now(timezone.utc)
        patient = PatientResponse(patient_id=uuid4(), created_at=now, updated_at=now, **request.model_dump())
        self.patients[patient.patient_id] = patient
        db.save_patient(patient.model_dump(mode="json"))
        if self.client:
            try:
                import re
                row = patient.model_dump(mode="json")
                if row.get("date_of_birth"):
                    m = re.search(r"\d{4}-\d{2}-\d{2}", row["date_of_birth"])
                    row["date_of_birth"] = m.group(0) if m else None
                self.client.table("patients").insert(row).execute()
            except Exception as exc:
                logger.warning("Supabase create_patient fallback to local store: %s", exc)
        return patient

    def get_patient(self, patient_id: UUID) -> PatientResponse | None:
        if self.client:
            try:
                response = self.client.table("patients").select("*").eq("patient_id", str(patient_id)).limit(1).execute()
                if response.data:
                    val = PatientResponse.model_validate(response.data[0])
                    self.patients[val.patient_id] = val
                    db.save_patient(val.model_dump(mode="json"))
                    return val
            except Exception as exc:
                logger.warning("Supabase get_patient fallback to local store: %s", exc)
        if patient_id in self.patients:
            return self.patients[patient_id]
        db_p = db.get_patient(str(patient_id))
        if db_p:
            try:
                val = PatientResponse(
                    patient_id=patient_id,
                    abha_id=db_p.get("abha_id"),
                    display_name=db_p.get("display_name"),
                    date_of_birth=db_p.get("date_of_birth"),
                    gender=db_p.get("gender"),
                    phone=db_p.get("phone"),
                    emergency_contact=db_p.get("emergency_contact"),
                    blood_group=db_p.get("blood_group"),
                    preferred_language=db_p.get("preferred_language", "en-IN"),
                    created_at=datetime.fromisoformat(db_p["created_at"]) if isinstance(db_p["created_at"], str) else db_p["created_at"],
                    updated_at=datetime.fromisoformat(db_p["updated_at"]) if isinstance(db_p["updated_at"], str) else db_p["updated_at"],
                )
                self.patients[patient_id] = val
                return val
            except Exception:
                pass
        return None

    def update_patient(self, patient_id: UUID, request: PatientUpdateRequest) -> PatientResponse | None:
        patient = self.get_patient(patient_id)
        if not patient:
            return None
        updates = request.model_dump(exclude_unset=True)
        if not updates:
            return patient
        patient = patient.model_copy(update={**updates, "updated_at": datetime.now(timezone.utc)})
        self.patients[patient.patient_id] = patient
        db.save_patient(patient.model_dump(mode="json"))
        if self.client:
            try:
                row = {k: v for k, v in patient.model_dump(mode="json").items() if k in updates or k == "updated_at"}
                if row.get("date_of_birth"):
                    import re
                    m = re.search(r"\d{4}-\d{2}-\d{2}", row["date_of_birth"])
                    row["date_of_birth"] = m.group(0) if m else None
                self.client.table("patients").update(row).eq("patient_id", str(patient.patient_id)).execute()
            except Exception as exc:
                logger.warning("Supabase update_patient fallback to local store: %s", exc)
        return patient

    def find_patient_by_abha(self, abha_id: str) -> PatientResponse | None:
        if self.client:
            try:
                response = self.client.table("patients").select("*").eq("abha_id", abha_id).limit(1).execute()
                if response.data:
                    return PatientResponse.model_validate(response.data[0])
            except Exception as exc:
                logger.warning("Supabase find_patient_by_abha fallback to local store: %s", exc)
        for item in self.patients.values():
            if item.abha_id == abha_id:
                return item
        db_p = db.find_patient_by_abha(abha_id)
        if db_p:
            try:
                val = PatientResponse(
                    patient_id=UUID(db_p["patient_id"]),
                    abha_id=db_p.get("abha_id"),
                    display_name=db_p.get("display_name"),
                    date_of_birth=db_p.get("date_of_birth"),
                    gender=db_p.get("gender"),
                    phone=db_p.get("phone"),
                    emergency_contact=db_p.get("emergency_contact"),
                    blood_group=db_p.get("blood_group"),
                    preferred_language=db_p.get("preferred_language", "en-IN"),
                    created_at=datetime.fromisoformat(db_p["created_at"]) if isinstance(db_p["created_at"], str) else db_p["created_at"],
                    updated_at=datetime.fromisoformat(db_p["updated_at"]) if isinstance(db_p["updated_at"], str) else db_p["updated_at"],
                )
                self.patients[val.patient_id] = val
                return val
            except Exception:
                pass
        return None

    def list_patients(self) -> list[PatientResponse]:
        results_map = {p.patient_id: p for p in self.patients.values()}
        for p_row in db.list_patients():
            try:
                pid = UUID(p_row["patient_id"])
                if pid not in results_map:
                    results_map[pid] = PatientResponse(
                        patient_id=pid,
                        abha_id=p_row.get("abha_id"),
                        display_name=p_row.get("display_name"),
                        date_of_birth=p_row.get("date_of_birth"),
                        gender=p_row.get("gender"),
                        phone=p_row.get("phone"),
                        emergency_contact=p_row.get("emergency_contact"),
                        blood_group=p_row.get("blood_group"),
                        preferred_language=p_row.get("preferred_language", "en-IN"),
                        created_at=datetime.fromisoformat(p_row["created_at"]) if isinstance(p_row["created_at"], str) else p_row["created_at"],
                        updated_at=datetime.fromisoformat(p_row["updated_at"]) if isinstance(p_row["updated_at"], str) else p_row["updated_at"],
                    )
            except Exception:
                pass
        if self.client:
            try:
                response = self.client.table("patients").select("*").execute()
                if response.data:
                    for item in response.data:
                        val = PatientResponse.model_validate(item)
                        results_map[val.patient_id] = val
            except Exception as exc:
                logger.warning("Supabase list_patients fallback to local store: %s", exc)
        return list(results_map.values())

    def create_session(self, request: SessionCreateRequest) -> SessionResponse:
        now = datetime.now(timezone.utc)
        token = request.token_number if request.token_number and request.token_number > 0 else db.get_next_token_number()
        session = SessionResponse(
            session_id=uuid4(),
            patient_id=request.patient_id,
            status="active",
            source=request.source,
            started_at=now,
            department=request.department or "general",
            opd_mode=request.opd_mode or "general",
            token_number=token,
            triage_level=request.triage_level or "routine",
            consent_given=request.consent_given,
            language_preference=request.language_preference or "en",
        )
        self.sessions[session.session_id] = session
        self.messages.setdefault(session.session_id, [])
        db.save_session(session.model_dump(mode="json"))
        if self.client:
            try:
                self.client.table("sessions").insert(session.model_dump(mode="json")).execute()
            except Exception as exc:
                logger.warning("Supabase create_session fallback to local store: %s", exc)
        return session

    def get_session(self, session_id: UUID) -> SessionResponse | None:
        if self.client:
            try:
                response = self.client.table("sessions").select("*").eq("session_id", str(session_id)).limit(1).execute()
                if response.data:
                    val = SessionResponse.model_validate(response.data[0])
                    self.sessions[val.session_id] = val
                    db.save_session(val.model_dump(mode="json"))
                    return val
            except Exception:
                pass
        if session_id in self.sessions:
            return self.sessions.get(session_id)
        
        db_sess = db.get_session(str(session_id))
        if db_sess:
            try:
                val = SessionResponse(
                    session_id=session_id,
                    patient_id=UUID(db_sess["patient_id"]),
                    status=db_sess.get("status", "active"),
                    source=db_sess.get("source", "web"),
                    started_at=datetime.fromisoformat(db_sess["started_at"]) if isinstance(db_sess["started_at"], str) else db_sess["started_at"],
                    completed_at=datetime.fromisoformat(db_sess["completed_at"]) if db_sess.get("completed_at") and isinstance(db_sess["completed_at"], str) else None,
                    department=db_sess.get("department", "general"),
                    opd_mode=db_sess.get("opd_mode", "general"),
                    token_number=int(db_sess.get("token_number") or 0),
                    triage_level=db_sess.get("triage_level", "routine"),
                    consent_given=bool(db_sess.get("consent_given", 0)),
                    language_preference=db_sess.get("language_preference", "en"),
                    doctor_verified=bool(db_sess.get("doctor_verified", 0)),
                    doctor_notes=db_sess.get("doctor_notes"),
                    doctor_verified_at=db_sess.get("doctor_verified_at"),
                )
                self.sessions[session_id] = val
                return val
            except Exception:
                pass

        runtime_store = get_runtime_session_store()
        if runtime_store:
            stored = runtime_store.get(str(session_id))
            if stored:
                now = datetime.now(timezone.utc)
                fallback_session = SessionResponse(
                    session_id=session_id,
                    patient_id=uuid4(),
                    status="active",
                    source="web",
                    started_at=now,
                )
                self.sessions[session_id] = fallback_session
                db.save_session(fallback_session.model_dump(mode="json"))
                return fallback_session
        return None

    def complete_session(self, session_id: UUID) -> SessionResponse:
        session = self.get_session(session_id)
        if not session:
            raise HTTPException(status_code=404, detail="Session not found")
        completed = session.model_copy(update={"status": "completed", "completed_at": datetime.now(timezone.utc)})
        self.sessions[session_id] = completed
        db.save_session(completed.model_dump(mode="json"))
        if self.client:
            try:
                self.client.table("sessions").update(completed.model_dump(mode="json")).eq("session_id", str(session_id)).execute()
            except Exception as exc:
                logger.warning("Supabase complete_session fallback: %s", exc)
        return completed

    def add_message(self, message: MessageResponse) -> None:
        self.messages.setdefault(message.session_id, []).append(message)
        db.save_message(message.model_dump(mode="json"))
        if self.client:
            try:
                self.client.table("conversation_messages").insert({
                    "message_id": str(message.message_id),
                    "session_id": str(message.session_id),
                    "role": message.role,
                    "content": message.content,
                    "source": message.source,
                    "language": message.language,
                    "confidence": message.confidence,
                    "created_at": message.created_at.isoformat(),
                }).execute()
            except Exception as exc:
                logger.warning("Supabase add_message fallback: %s", exc)

    def get_messages(self, session_id: UUID) -> list[MessageResponse]:
        if self.client:
            try:
                response = self.client.table("conversation_messages").select("*").eq("session_id", str(session_id)).order("created_at").execute()
                if response.data:
                    return [MessageResponse.model_validate(item) for item in response.data]
            except Exception as exc:
                logger.warning("Supabase get_messages fallback: %s", exc)
        if session_id in self.messages and len(self.messages[session_id]) > 0:
            return self.messages[session_id]
        db_msgs = db.get_messages(str(session_id))
        if db_msgs:
            parsed = []
            for m in db_msgs:
                try:
                    parsed.append(MessageResponse(
                        message_id=UUID(m["message_id"]),
                        session_id=session_id,
                        role=m["role"],
                        content=m["content"],
                        source=m.get("source", "text"),
                        language=m.get("language"),
                        confidence=m.get("confidence"),
                        created_at=datetime.fromisoformat(m["created_at"]) if isinstance(m["created_at"], str) else m["created_at"],
                    ))
                except Exception:
                    pass
            if parsed:
                self.messages[session_id] = parsed
                return parsed
        return []

    def save_document(self, document: DocumentResponse) -> DocumentResponse:
        self.documents[document.document_id] = document
        db.save_document(document.model_dump(mode="json"))
        if self.client:
            try:
                self.client.table('documents').insert({
                    'document_id': str(document.document_id),
                    'session_id': str(document.session_id),
                    'file_name': document.file_name,
                    'file_type': document.file_type,
                    'file_size': document.file_size,
                    'storage_path': document.storage_path,
                    'document_type': document.document_type,
                    'upload_status': document.upload_status,
                    'ocr_status': document.ocr_status,
                }).execute()
            except Exception as exc:
                logger.warning("Supabase save_document fallback: %s", exc)
        return document

    def get_document(self, document_id: UUID) -> DocumentResponse | None:
        if self.client:
            try:
                response = self.client.table('documents').select('*').eq('document_id', str(document_id)).limit(1).execute()
                if response.data:
                    return DocumentResponse.model_validate(response.data[0])
            except Exception as exc:
                logger.warning("Supabase get_document fallback: %s", exc)
        if document_id in self.documents:
            return self.documents[document_id]
        d_row = db.get_document(str(document_id))
        if d_row:
            try:
                val = DocumentResponse(
                    document_id=document_id,
                    session_id=UUID(d_row["session_id"]),
                    file_name=d_row["file_name"],
                    file_type=d_row["file_type"],
                    file_size=d_row["file_size"],
                    storage_path=d_row.get("storage_path", ""),
                    upload_status=d_row.get("upload_status", "received"),
                    ocr_status=d_row.get("ocr_status", "completed"),
                    document_type=d_row.get("document_type"),
                    ocr=d_row.get("ocr_data"),
                    document_classification=d_row.get("document_classification", "historical"),
                    classification_source=d_row.get("classification_source", "patient"),
                    document_date=d_row.get("document_date"),
                    document_date_type=d_row.get("document_date_type", "unknown"),
                    document_date_source=d_row.get("document_date_source", "unknown"),
                    temporal_status=d_row.get("temporal_status", "unknown"),
                    verification_status=d_row.get("verification_status", "pending"),
                    created_at=datetime.fromisoformat(d_row["created_at"]) if isinstance(d_row["created_at"], str) else d_row["created_at"],
                )
                self.documents[document_id] = val
                return val
            except Exception:
                pass
        return None

    def get_documents(self, session_id: UUID) -> list[DocumentResponse]:
        if self.client:
            try:
                response = self.client.table('documents').select('*').eq('session_id', str(session_id)).order('created_at').execute()
                if response.data:
                    return [DocumentResponse.model_validate(item) for item in response.data]
            except Exception as exc:
                logger.warning("Supabase get_documents fallback: %s", exc)
        docs = [document for document in self.documents.values() if document.session_id == session_id]
        if docs:
            return docs
        db_docs = db.list_documents(str(session_id))
        parsed = []
        for d_row in db_docs:
            try:
                val = DocumentResponse(
                    document_id=UUID(d_row["document_id"]),
                    session_id=session_id,
                    file_name=d_row["file_name"],
                    file_type=d_row["file_type"],
                    file_size=d_row["file_size"],
                    storage_path=d_row.get("storage_path", ""),
                    upload_status=d_row.get("upload_status", "received"),
                    ocr_status=d_row.get("ocr_status", "completed"),
                    document_type=d_row.get("document_type"),
                    ocr=d_row.get("ocr_data"),
                    document_classification=d_row.get("document_classification", "historical"),
                    classification_source=d_row.get("classification_source", "patient"),
                    document_date=d_row.get("document_date"),
                    document_date_type=d_row.get("document_date_type", "unknown"),
                    document_date_source=d_row.get("document_date_source", "unknown"),
                    temporal_status=d_row.get("temporal_status", "unknown"),
                    verification_status=d_row.get("verification_status", "pending"),
                    created_at=datetime.fromisoformat(d_row["created_at"]) if isinstance(d_row["created_at"], str) else d_row["created_at"],
                )
                self.documents[val.document_id] = val
                parsed.append(val)
            except Exception:
                pass
        return parsed

    def update_document(self, document: DocumentResponse) -> DocumentResponse:
        self.documents[document.document_id] = document
        db.save_document(document.model_dump(mode="json"))
        if self.client:
            try:
                self.client.table('documents').update({
                    'document_type': document.document_type,
                    'upload_status': document.upload_status,
                    'ocr_status': document.ocr_status,
                }).eq('document_id', str(document.document_id)).execute()
                if document.ocr is not None:
                    self.client.table('ocr_results').insert({
                        'document_id': str(document.document_id),
                        'raw_output': document.ocr,
                        'raw_text': document.ocr.get('raw_text', ''),
                        'normalized_output': document.ocr,
                        'confidence': document.ocr.get('confidence'),
                        'warnings': document.ocr.get('warnings', []),
                    }).execute()
            except Exception as exc:
                logger.warning("Supabase update_document fallback: %s", exc)
        return document

    def delete_temporary_data(self, session_id: UUID) -> None:
        db.delete_temporary_data(str(session_id))
        if self.client:
            try:
                for table in ('conversation_messages', 'medical_history', 'medications', 'allergies', 'family_history', 'lifestyle', 'clinical_observations', 'red_flags', 'consents'):
                    self.client.table(table).delete().eq('session_id', str(session_id)).execute()
                documents = self.client.table('documents').select('document_id').eq('session_id', str(session_id)).execute()
                for document in documents.data:
                    self.client.table('ocr_results').delete().eq('document_id', document['document_id']).execute()
                self.client.table('documents').delete().eq('session_id', str(session_id)).execute()
            except Exception as exc:
                logger.warning("Supabase delete_temporary_data fallback: %s", exc)
        document_ids = [document_id for document_id, document in self.documents.items() if document.session_id == session_id]
        for document_id in document_ids:
            self.documents.pop(document_id, None)
            self.document_contents.pop(document_id, None)
        self.messages.pop(session_id, None)
        self.clinical_data.pop(session_id, None)
        self.red_flags.pop(session_id, None)

    def save_document_content(self, document_id: UUID, content: bytes) -> None:
        self.document_contents[document_id] = content
        try:
            doc_dir = DB_DIR / "documents"
            doc_dir.mkdir(parents=True, exist_ok=True)
            (doc_dir / str(document_id)).write_bytes(content)
        except Exception as exc:
            logger.warning("Could not persist document to disk: %s", exc)

    def get_document_content(self, document_id: UUID) -> bytes | None:
        if document_id in self.document_contents:
            return self.document_contents[document_id]
        try:
            doc_path = DB_DIR / "documents" / str(document_id)
            if doc_path.exists():
                data = doc_path.read_bytes()
                self.document_contents[document_id] = data
                return data
        except Exception:
            pass
        doc_obj = self.documents.get(document_id)
        if doc_obj and doc_obj.storage_path:
            storage_client = getattr(get_runtime_session_store(), '_client', None)
            if storage_client:
                try:
                    data = SupabaseStorageService(storage_client).download(doc_obj.storage_path)
                    self.document_contents[document_id] = data
                    return data
                except Exception:
                    pass
        return None

    @staticmethod
    def _clinical_items(data: dict[str, Any], key: str) -> list[dict[str, Any] | str]:
        value: Any = data.get(key, [])
        if isinstance(value, (dict, str)):
            return [value]
        return value if isinstance(value, list) else []

    @staticmethod
    def _medication_row(item: dict[str, Any] | str) -> dict[str, Any]:
        if isinstance(item, str):
            return {
                'name_as_reported': item,
                'dose_as_reported': None,
                'frequency_as_reported': None,
                'notes': None,
            }
        return {
            'name_as_reported': item.get('name_as_reported') or item.get('name') or item.get('medication') or 'Unknown',
            'dose_as_reported': item.get('dose_as_reported') or item.get('dose') or item.get('dosage'),
            'frequency_as_reported': item.get('frequency_as_reported') or item.get('frequency'),
            'notes': item.get('notes'),
        }

    @staticmethod
    def _allergy_row(item: dict[str, Any] | str) -> dict[str, Any]:
        return {'allergen': item if isinstance(item, str) else item.get('allergen') or item.get('name') or item.get('text') or 'Unknown'}

    def save_clinical_data(self, session_id: UUID, category: str, data: dict[str, Any]) -> dict[str, Any]:
        """Convert application clinical payloads into their persistence shapes."""
        session_key = str(session_id)
        if category == 'medical-history':
            if self.client:
                try:
                    self.client.table('medical_history').upsert(
                        {'session_id': session_key, 'data': data}, on_conflict='session_id'
                    ).execute()
                except Exception as exc:
                    logger.warning("Supabase save medical_history fallback: %s", exc)
        elif category == 'medications':
            items = [item for item in self._clinical_items(data, 'medications') if isinstance(item, (dict, str))]
            rows = [{'session_id': session_key, **self._medication_row(item)} for item in items]
            if self.client:
                try:
                    self.client.table('medications').delete().eq('session_id', session_key).execute()
                    if rows:
                        self.client.table('medications').insert(rows).execute()
                except Exception as exc:
                    logger.warning("Supabase save medications fallback: %s", exc)
            data = {'medications': [self._medication_row(item) for item in items]}
        elif category == 'allergies':
            items = self._clinical_items(data, 'allergies')
            rows = [{'session_id': session_key, **self._allergy_row(item)} for item in items if isinstance(item, (dict, str))]
            if self.client:
                try:
                    self.client.table('allergies').delete().eq('session_id', session_key).execute()
                    if rows:
                        self.client.table('allergies').insert(rows).execute()
                except Exception as exc:
                    logger.warning("Supabase save allergies fallback: %s", exc)
            data = {'allergies': [self._allergy_row(item) for item in items if isinstance(item, (dict, str))]}
        elif category in {'family-history', 'lifestyle'}:
            if self.client:
                try:
                    table = {'family-history': 'family_history', 'lifestyle': 'lifestyle'}[category]
                    self.client.table(table).upsert(
                        {'session_id': session_key, 'data': data}, on_conflict='session_id'
                    ).execute()
                except Exception as exc:
                    logger.warning("Supabase save %s fallback: %s", category, exc)
        else:
            raise ValueError(f'Unsupported clinical category: {category}')
        self.clinical_data.setdefault(session_id, {})[category] = data
        db.save_clinical_data(session_key, category, data)
        return data

    def get_clinical_data(self, session_id: UUID, category: str) -> dict[str, Any]:
        session_key = str(session_id)
        if self.client and category == 'medical-history':
            try:
                response = self.client.table('medical_history').select('data').eq('session_id', session_key).limit(1).execute()
                if response.data:
                    return response.data[0]['data']
            except Exception as exc:
                logger.warning("Supabase get medical-history fallback: %s", exc)
        if self.client and category == 'medications':
            try:
                response = self.client.table('medications').select(
                    'name_as_reported,dose_as_reported,frequency_as_reported,notes'
                ).eq('session_id', session_key).execute()
                if response.data:
                    return {'medications': response.data}
            except Exception as exc:
                logger.warning("Supabase get medications fallback: %s", exc)
        if self.client and category == 'allergies':
            try:
                response = self.client.table('allergies').select('allergen').eq('session_id', session_key).execute()
                if response.data:
                    return {'allergies': response.data}
            except Exception as exc:
                logger.warning("Supabase get allergies fallback: %s", exc)
        if self.client and category in {'family-history', 'lifestyle'}:
            try:
                table = {'family-history': 'family_history', 'lifestyle': 'lifestyle'}[category]
                response = self.client.table(table).select('data').eq('session_id', session_key).limit(1).execute()
                if response.data:
                    return response.data[0]['data']
            except Exception as exc:
                logger.warning("Supabase get %s fallback: %s", category, exc)
        if category not in {'medical-history', 'medications', 'allergies', 'family-history', 'lifestyle'}:
            raise ValueError(f'Unsupported clinical category: {category}')
        
        mem_data = self.clinical_data.get(session_id, {}).get(category)
        if mem_data is not None:
            return mem_data
        db_data = db.get_clinical_data(session_key, category)
        if db_data is not None:
            self.clinical_data.setdefault(session_id, {})[category] = db_data
            return db_data
        return {}

    def save_red_flag(self, flag: RedFlagResponse) -> RedFlagResponse:
        self.red_flags.setdefault(flag.session_id, []).append(flag)
        if self.client:
            try:
                self.client.table("red_flags").insert({
                    "red_flag_id": str(flag.red_flag_id),
                    "session_id": str(flag.session_id),
                    "category": flag.category,
                    "severity": flag.severity,
                    "reason": flag.reason,
                    "source": flag.source,
                    "is_resolved": flag.is_resolved,
                    "created_at": flag.created_at.isoformat(),
                }).execute()
            except Exception as exc:
                logger.warning("Supabase save_red_flag fallback: %s", exc)
        return flag

    def get_red_flags(self, session_id: UUID) -> list[RedFlagResponse]:
        if self.client:
            try:
                response = self.client.table("red_flags").select("*").eq("session_id", str(session_id)).order("created_at").execute()
                if response.data:
                    return [RedFlagResponse.model_validate(item) for item in response.data]
            except Exception as exc:
                logger.warning("Supabase get_red_flags fallback: %s", exc)
        return self.red_flags.get(session_id, [])

    def save_consent(self, consent: ConsentResponse) -> ConsentResponse:
        self.consents.setdefault(consent.session_id, []).append(consent)
        if self.client:
            try:
                self.client.table("consents").insert({
                    "consent_id": str(consent.consent_id),
                    "session_id": str(consent.session_id),
                    "consent_type": consent.consent_type,
                    "granted": consent.granted,
                    "consent_version": consent.consent_version,
                    "recorded_by": consent.recorded_by,
                    "created_at": consent.created_at.isoformat(),
                }).execute()
            except Exception as exc:
                logger.warning("Supabase save_consent fallback: %s", exc)
        return consent

    def get_consents(self, session_id: UUID) -> list[ConsentResponse]:
        if self.client:
            try:
                response = self.client.table("consents").select("*").eq("session_id", str(session_id)).order("created_at").execute()
                if response.data:
                    return [ConsentResponse.model_validate(item) for item in response.data]
            except Exception as exc:
                logger.warning("Supabase get_consents fallback: %s", exc)
        return self.consents.get(session_id, [])

    def save_summary(self, summary: SummaryResponseV1) -> SummaryResponseV1:
        self.summaries[summary.session_id] = summary
        db.save_summary(str(summary.session_id), summary.model_dump(mode="json"))
        if self.client:
            try:
                self.client.table("summaries").upsert({
                    "session_id": str(summary.session_id),
                    "content": summary.content,
                    "clinician_reviewed": summary.clinician_reviewed,
                    "updated_at": summary.updated_at.isoformat(),
                }, on_conflict="session_id").execute()
            except Exception as exc:
                logger.warning("Supabase save_summary fallback: %s", exc)
        return summary

    def get_summary(self, session_id: UUID) -> SummaryResponseV1 | None:
        if self.client:
            try:
                response = self.client.table("summaries").select("*").eq("session_id", str(session_id)).limit(1).execute()
                if response.data:
                    return SummaryResponseV1.model_validate(response.data[0])
            except Exception as exc:
                logger.warning("Supabase get_summary fallback: %s", exc)
        if session_id in self.summaries:
            return self.summaries.get(session_id)
        db_sum = db.get_summary(str(session_id))
        if db_sum:
            try:
                val = SummaryResponseV1.model_validate(db_sum)
                self.summaries[session_id] = val
                return val
            except Exception:
                pass
        return None

    def save_doctor_case(self, session_id: UUID, case_data: dict[str, Any]) -> dict[str, Any]:
        self.doctor_cases[session_id] = case_data
        if self.client:
            try:
                raw_status = case_data.get("status")
                safe_status = raw_status if raw_status in ("draft", "reviewed", "closed") else "draft"
                self.client.table("doctor_cases").upsert({
                    "session_id": str(session_id),
                    "content": case_data.get("summary") or case_data,
                    "status": safe_status,
                    "reviewed_by": case_data.get("reviewed_by"),
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }, on_conflict="session_id").execute()
            except Exception as exc:
                logger.warning("Supabase save_doctor_case fallback: %s", exc)
        return case_data

    def get_doctor_case_record(self, session_id: UUID) -> dict[str, Any] | None:
        if self.client:
            try:
                response = self.client.table("doctor_cases").select("*").eq("session_id", str(session_id)).limit(1).execute()
                if response.data:
                    return response.data[0]
            except Exception as exc:
                logger.warning("Supabase get_doctor_case fallback: %s", exc)
        return self.doctor_cases.get(session_id)


clinical_repository = ClinicalRepository()
runtime_session_store: SessionStore | None = None


@router.get('/health')
def v1_health():
    return {'status': 'ok', 'service': 'cliniqo-api', 'version': '1', 'persistence': get_runtime_session_store().backend}


def configure_repository(client: Any = None) -> None:
    global clinical_repository
    clinical_repository = ClinicalRepository(client)


def configure_session_store(store: SessionStore) -> None:
    global runtime_session_store
    runtime_session_store = store


def get_runtime_session_store() -> SessionStore:
    if runtime_session_store is None:
        raise RuntimeError("Clinical API session store is not configured.")
    return runtime_session_store


@router.post("/patients", response_model=PatientResponse, status_code=201)
def create_patient(request: PatientCreateRequest):
    return clinical_repository.create_patient(request)


@router.get("/patients", response_model=list[PatientResponse])
def list_patients(portal: str | None = None, patient_id: UUID | None = None):
    if portal == "patient" and patient_id:
        p = clinical_repository.get_patient(patient_id)
        return [p] if p else []
    return clinical_repository.list_patients()


@router.get("/patients/search", response_model=list[PatientResponse])
def search_patients(q: str = ""):
    import re
    all_patients = clinical_repository.list_patients()
    if not q or not q.strip():
        return all_patients
    q_clean = q.strip().lower()
    q_digits = re.sub(r"\D", "", q)
    last10 = q_digits[-10:] if len(q_digits) >= 10 else q_digits

    matches = []
    for p in all_patients:
        phone_digits = re.sub(r"\D", "", p.phone or "")
        phone_last10 = phone_digits[-10:] if len(phone_digits) >= 10 else phone_digits
        abha_digits = re.sub(r"\D", "", p.abha_id or "")

        if (
            (last10 and phone_last10 and last10 == phone_last10)
            or (q_digits and abha_digits and q_digits == abha_digits)
            or (p.abha_id and q_clean in p.abha_id.lower())
            or (p.display_name and q_clean in p.display_name.lower())
            or (str(p.patient_id) == q_clean)
        ):
            matches.append(p)
    return matches


@router.get("/patients/{patient_id}", response_model=PatientResponse)
def get_patient(patient_id: UUID):
    patient = clinical_repository.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.get("/patients/by-abha/{abha_id}", response_model=PatientResponse)
def get_patient_by_abha(abha_id: str):
    patient = clinical_repository.find_patient_by_abha(abha_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.put("/patients/{patient_id}", response_model=PatientResponse)
def update_patient(patient_id: UUID, request: PatientUpdateRequest):
    patient = clinical_repository.update_patient(patient_id, request)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return patient


@router.post("/sessions", response_model=SessionResponse, status_code=201)
def create_session(request: SessionCreateRequest):
    if not clinical_repository.get_patient(request.patient_id):
        raise HTTPException(status_code=404, detail="Patient not found")
    session = clinical_repository.create_session(request)
    orchestrator = MedicalOrchestrator(session_id=str(session.session_id))
    get_runtime_session_store().save(APISessionState(session_id=str(session.session_id), orchestrator_state=orchestrator.state.model_dump()))
    return session


@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(session_id: UUID):
    session = clinical_repository.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail="Session not found")
    return session


@router.post("/sessions/{session_id}/complete", response_model=SessionResponse)
def complete_session(session_id: UUID):
    return clinical_repository.complete_session(session_id)


@router.delete('/sessions/{session_id}/temporary-data')
def delete_temporary_data(session_id: UUID):
    require_session(session_id)
    clinical_repository.delete_temporary_data(session_id)
    return {'status': 'deleted', 'session_id': str(session_id)}


@router.post("/sessions/{session_id}/messages", response_model=MessageResponse, status_code=201)
def create_message(session_id: UUID, request: MessageCreateRequest):
    require_session(session_id)
    session_store = get_runtime_session_store()
    state = session_store.get(str(session_id))
    if not state:
        raise HTTPException(status_code=404, detail="Session state not found")

    # Run NLP on incoming text to extract structured clinical entities
    nlp_result = PatientNLPService().process(request.content, source=request.source, language=request.language)
    entities = nlp_result.entities if isinstance(nlp_result.entities, dict) else {}

    # Ingest extracted structured fields into clinical repository
    cdata = clinical_repository.clinical_data.setdefault(session_id, {})
    if entities.get("medications"):
        med_rows = [
            {"name_as_reported": m if isinstance(m, str) else m.get("name_as_reported", m.get("name", "Medication")),
             "dose_as_reported": m.get("dosage") if isinstance(m, dict) else None}
            for m in entities["medications"]
        ]
        curr_meds = cdata.setdefault("medications", [])
        med_list = curr_meds.get("medications") if isinstance(curr_meds, dict) else (curr_meds if isinstance(curr_meds, list) else [])
        if not isinstance(curr_meds, (list, dict)):
            cdata["medications"] = med_list
        for mr in med_rows:
            if not any(isinstance(e, dict) and e.get("name_as_reported") == mr["name_as_reported"] for e in med_list):
                med_list.append(mr)

    if entities.get("allergies"):
        alg_rows = [
            {"allergen": a if isinstance(a, str) else a.get("allergen", a.get("name", "Allergen"))}
            for a in entities["allergies"]
        ]
        curr_alg = cdata.setdefault("allergies", [])
        alg_list = curr_alg.get("allergies") if isinstance(curr_alg, dict) else (curr_alg if isinstance(curr_alg, list) else [])
        if not isinstance(curr_alg, (list, dict)):
            cdata["allergies"] = alg_list
        for ar in alg_rows:
            if not any(isinstance(e, dict) and e.get("allergen") == ar["allergen"] for e in alg_list):
                alg_list.append(ar)

    if entities.get("diseases"):
        curr_hist = cdata.setdefault("medical-history", [])
        hist_list = curr_hist.get("conditions") if isinstance(curr_hist, dict) else (curr_hist if isinstance(curr_hist, list) else [])
        if not isinstance(curr_hist, (list, dict)):
            cdata["medical-history"] = hist_list
        for d in entities["diseases"]:
            if d not in hist_list:
                hist_list.append(d)

    orchestrator = MedicalOrchestrator(session_id=str(session_id))
    orchestrator.state = orchestrator.state.model_validate(state.orchestrator_state)
    result = orchestrator.handle_patient_message(request.content)

    # Evaluate safety triage & persist red flags
    for flag in DeterministicTriageService().evaluate(request.content):
        clinical_repository.save_red_flag(
            RedFlagResponse(
                red_flag_id=uuid4(),
                session_id=session_id,
                created_at=datetime.now(timezone.utc),
                category=flag.category,
                severity=flag.severity,
                reason=flag.reason,
                source=flag.source,
            )
        )

    session_store.save(APISessionState(session_id=str(session_id), orchestrator_state=result.model_dump()))

    assistant_message = ""
    if result.interview_state and result.interview_state.get("conversation_history"):
        assistant_message = result.interview_state["conversation_history"][-1].get("content", "")

    message = MessageResponse(
        message_id=uuid4(),
        session_id=session_id,
        role="patient",
        created_at=datetime.now(timezone.utc),
        assistant_message=assistant_message,
        **request.model_dump()
    )
    clinical_repository.add_message(message)
    return message


@router.post('/sessions/{session_id}/transcript', response_model=MessageResponse, status_code=201)
def create_transcript(session_id: UUID, request: TranscriptRequest):
    result = PatientNLPService().process(request.text, source='voice', language=request.language)
    return create_message(
        session_id,
        MessageCreateRequest(
            content=result.text,
            source='voice',
            language=result.language,
            confidence=request.confidence
        )
    )


@router.post('/sessions/{session_id}/process-language', response_model=LanguageProcessResponse)
def process_language(session_id: UUID, request: MessageCreateRequest):
    require_session(session_id)
    result = PatientNLPService().process(request.content, source=request.source, language=request.language)
    flags = DeterministicTriageService().evaluate(result.text)

    # Ingest structured entities into session clinical data
    cdata = clinical_repository.clinical_data.setdefault(session_id, {})
    entities = result.entities if isinstance(result.entities, dict) else {}
    if entities.get("medications"):
        med_rows = [
            {"name_as_reported": m if isinstance(m, str) else m.get("name_as_reported", m.get("name", "Medication")),
             "dose_as_reported": m.get("dosage") if isinstance(m, dict) else None}
            for m in entities["medications"]
        ]
        curr_meds = cdata.setdefault("medications", [])
        med_list = curr_meds.get("medications") if isinstance(curr_meds, dict) else (curr_meds if isinstance(curr_meds, list) else [])
        if not isinstance(curr_meds, (list, dict)):
            cdata["medications"] = med_list
        for mr in med_rows:
            if not any(isinstance(e, dict) and e.get("name_as_reported") == mr["name_as_reported"] for e in med_list):
                med_list.append(mr)

    if entities.get("allergies"):
        alg_rows = [
            {"allergen": a if isinstance(a, str) else a.get("allergen", a.get("name", "Allergen"))}
            for a in entities["allergies"]
        ]
        curr_alg = cdata.setdefault("allergies", [])
        alg_list = curr_alg.get("allergies") if isinstance(curr_alg, dict) else (curr_alg if isinstance(curr_alg, list) else [])
        if not isinstance(curr_alg, (list, dict)):
            cdata["allergies"] = alg_list
        for ar in alg_rows:
            if not any(isinstance(e, dict) and e.get("allergen") == ar["allergen"] for e in alg_list):
                alg_list.append(ar)

    if entities.get("diseases"):
        curr_hist = cdata.setdefault("medical-history", [])
        hist_list = curr_hist.get("conditions") if isinstance(curr_hist, dict) else (curr_hist if isinstance(curr_hist, list) else [])
        if not isinstance(curr_hist, (list, dict)):
            cdata["medical-history"] = hist_list
        for d in entities["diseases"]:
            if d not in hist_list:
                hist_list.append(d)

    saved_flags = []
    for flag in flags:
        rf = clinical_repository.save_red_flag(
            RedFlagResponse(
                red_flag_id=uuid4(),
                session_id=session_id,
                created_at=datetime.now(timezone.utc),
                category=flag.category,
                severity=flag.severity,
                reason=flag.reason,
                source=flag.source
            )
        )
        saved_flags.append(rf.model_dump(mode='json'))

    return LanguageProcessResponse(
        text=result.text,
        language=result.language,
        confidence=request.confidence or 1.0,
        source=result.source,
        processing_status=result.processing_status,
        entities=entities,
        red_flags=saved_flags
    )


@router.get("/sessions/{session_id}/messages", response_model=list[MessageResponse])
def get_messages(session_id: UUID):
    require_session(session_id)
    return clinical_repository.get_messages(session_id)


def require_session(session_id: UUID) -> SessionResponse:
    session = clinical_repository.get_session(session_id)
    if not session:
        raise HTTPException(status_code=404, detail='Session not found')
    return session


@router.put('/sessions/{session_id}/clinical/{category}', response_model=dict[str, Any])
def save_clinical_data(session_id: UUID, category: str, request: DataPayload):
    require_session(session_id)
    if category not in {'medical-history', 'medications', 'allergies', 'family-history', 'lifestyle'}:
        raise HTTPException(status_code=404, detail='Clinical category not found')
    return clinical_repository.save_clinical_data(session_id, category, request.data)


@router.get('/sessions/{session_id}/clinical/{category}', response_model=dict[str, Any])
def get_clinical_data(session_id: UUID, category: str):
    require_session(session_id)
    if category not in {'medical-history', 'medications', 'allergies', 'family-history', 'lifestyle'}:
        raise HTTPException(status_code=404, detail='Clinical category not found')
    return clinical_repository.get_clinical_data(session_id, category)


def save_named_clinical_data(session_id: UUID, category: str, request: DataPayload):
    require_session(session_id)
    saved = clinical_repository.save_clinical_data(session_id, category, request.data)
    try:
        session_store = get_runtime_session_store()
        sess_key = str(session_id)
        stored = session_store.get(sess_key)
        if stored and stored.orchestrator_state:
            orch_state = stored.orchestrator_state
            if "clinical_history" not in orch_state or not isinstance(orch_state["clinical_history"], dict):
                orch_state["clinical_history"] = {
                    "session_id": sess_key,
                    "chief_complaint": None,
                    "history_of_present_illness": {},
                    "associated_symptoms": [],
                    "past_medical_history": [],
                    "medications": [],
                    "allergies": [],
                    "family_history": [],
                    "personal_history": {},
                    "source_evidence": {}
                }
            ch = orch_state["clinical_history"]
            req_d = request.data
            if "conditions" in req_d or "past_history" in req_d or "medical_history" in req_d or category == 'medical-history':
                conds = req_d.get("conditions") or req_d.get("past_history") or req_d.get("medical_history") or []
                if isinstance(conds, list):
                    for c in conds:
                        c_name = c if isinstance(c, str) else (c.get("condition") or c.get("name") or "")
                        if c_name and c_name not in ch.get("past_medical_history", []):
                            ch.setdefault("past_medical_history", []).append(c_name)
                    clinical_repository.clinical_data.setdefault(session_id, {})['medical-history'] = {'conditions': conds}

            if "medications" in req_d or category == 'medications':
                meds = req_d.get("medications") or []
                if isinstance(meds, list):
                    for m in meds:
                        m_row = m if isinstance(m, dict) else {"name_as_reported": str(m)}
                        if not any(isinstance(existing, dict) and existing.get("name_as_reported") == m_row.get("name_as_reported") for existing in ch.get("medications", [])):
                            ch.setdefault("medications", []).append(m_row)
                    clinical_repository.clinical_data.setdefault(session_id, {})['medications'] = {'medications': meds}

            if "allergies" in req_d or category == 'allergies':
                algs = req_d.get("allergies") or []
                if isinstance(algs, list):
                    for a in algs:
                        a_name = a if isinstance(a, str) else (a.get("allergen") or a.get("name") or "")
                        if a_name and a_name not in ch.get("allergies", []):
                            ch.setdefault("allergies", []).append(a_name)
                    clinical_repository.clinical_data.setdefault(session_id, {})['allergies'] = {'allergies': algs}

            if "family_history" in req_d or category == 'family-history':
                fams = req_d.get("family_history") or req_d.get("conditions") or []
                if isinstance(fams, list):
                    for f in fams:
                        f_name = f if isinstance(f, str) else str(f)
                        if f_name and f_name not in ch.get("family_history", []):
                            ch.setdefault("family_history", []).append(f_name)
                    clinical_repository.clinical_data.setdefault(session_id, {})['family-history'] = {'conditions': fams}

            if "lifestyle" in req_d or "habits" in req_d or category == 'lifestyle':
                habits = req_d.get("habits") or (req_d.get("lifestyle", {}).get("habits") if isinstance(req_d.get("lifestyle"), dict) else req_d.get("lifestyle")) or []
                if isinstance(habits, list):
                    if not isinstance(ch.get("personal_history"), dict):
                        ch["personal_history"] = {}
                    ch["personal_history"]["habits"] = habits
                    clinical_repository.clinical_data.setdefault(session_id, {})['lifestyle'] = {'habits': habits}

            if orch_state.get("risk_assessment"):
                try:
                    from core.orchestrator import MedicalOrchestrator
                    from core.schemas import OrchestrationState
                    orch_inst = MedicalOrchestrator(session_id=sess_key)
                    orch_inst.state = OrchestrationState.model_validate(orch_state)
                    orch_inst._run_summary()
                    if orch_inst.state.physician_summary:
                        orch_state["physician_summary"] = orch_inst.state.physician_summary.model_dump(mode="json")
                except Exception:
                    pass

            stored.orchestrator_state = orch_state
            session_store.save(stored)
    except Exception as exc:
        logger.warning("save_named_clinical_data session store sync notice: %s", exc)
    return saved


def get_named_clinical_data(session_id: UUID, category: str):
    require_session(session_id)
    return clinical_repository.get_clinical_data(session_id, category)


@router.put('/sessions/{session_id}/medical-history', response_model=dict[str, Any])
def save_medical_history(session_id: UUID, request: DataPayload):
    return save_named_clinical_data(session_id, 'medical-history', request)


@router.put('/sessions/{session_id}/medications', response_model=dict[str, Any])
def save_medications(session_id: UUID, request: DataPayload):
    return save_named_clinical_data(session_id, 'medications', request)


@router.put('/sessions/{session_id}/allergies', response_model=dict[str, Any])
def save_allergies(session_id: UUID, request: DataPayload):
    return save_named_clinical_data(session_id, 'allergies', request)


@router.put('/sessions/{session_id}/family-history', response_model=dict[str, Any])
def save_family_history(session_id: UUID, request: DataPayload):
    return save_named_clinical_data(session_id, 'family-history', request)


@router.put('/sessions/{session_id}/lifestyle', response_model=dict[str, Any])
def save_lifestyle(session_id: UUID, request: DataPayload):
    return save_named_clinical_data(session_id, 'lifestyle', request)


@router.get('/sessions/{session_id}/medical-history', response_model=dict[str, Any])
def get_medical_history(session_id: UUID):
    return get_named_clinical_data(session_id, 'medical-history')


@router.get('/sessions/{session_id}/medications', response_model=dict[str, Any])
def get_medications(session_id: UUID):
    return get_named_clinical_data(session_id, 'medications')


@router.get('/sessions/{session_id}/allergies', response_model=dict[str, Any])
def get_allergies(session_id: UUID):
    return get_named_clinical_data(session_id, 'allergies')


@router.get('/sessions/{session_id}/family-history', response_model=dict[str, Any])
def get_family_history(session_id: UUID):
    return get_named_clinical_data(session_id, 'family-history')


@router.get('/sessions/{session_id}/lifestyle', response_model=dict[str, Any])
def get_lifestyle(session_id: UUID):
    return get_named_clinical_data(session_id, 'lifestyle')


@router.post('/sessions/{session_id}/documents', response_model=DocumentResponse, status_code=201)
async def upload_document(
    session_id: UUID,
    file: UploadFile = File(...),
    classification: str = "historical",
    classification_source: str = "patient",
    document_date: str | None = None,
    document_date_type: str = "unknown",
    document_date_source: str = "unknown",
):
    require_session(session_id)
    content = await file.read()
    filename = file.filename or 'document'
    mime_type = file.content_type or 'application/octet-stream'
    document_id = uuid4()
    storage_path = f'{session_id}/{document_id}/{filename}'
    document = DocumentResponse(
        document_id=document_id,
        session_id=session_id,
        file_name=filename,
        file_type=mime_type,
        file_size=len(content),
        storage_path=storage_path,
        upload_status='received',
        ocr_status='pending',
        document_classification=classification if classification in {"current", "historical"} else "historical",
        classification_source=classification_source if classification_source in {"patient", "clinician"} else "patient",
        document_date=document_date,
        document_date_type=document_date_type if document_date_type in {"exact", "approximate", "unknown"} else "unknown",
        document_date_source=document_date_source if document_date_source in {"ocr", "patient", "clinician", "unknown"} else "unknown",
        temporal_status=classification if classification in {"current", "historical"} else "unknown",
        verification_status='pending',
        created_at=datetime.now(timezone.utc),
    )
    session_store = get_runtime_session_store()
    storage_client = getattr(session_store, '_client', None)
    if storage_client:
        try:
            SupabaseStorageService(storage_client).upload(content, storage_path, mime_type)
            document.upload_status = 'uploaded'
        except StorageServiceError as exc:
            logger.warning("Supabase storage upload fallback to local content store: %s", exc)
    clinical_repository.save_document_content(document_id, content)
    clinical_repository.save_document(document)
    return document


@router.get('/sessions/{session_id}/documents', response_model=list[DocumentResponse])
def list_documents(session_id: UUID):
    require_session(session_id)
    return clinical_repository.get_documents(session_id)


@router.get('/documents/{document_id}', response_model=DocumentResponse)
def get_document(document_id: UUID):
    document = clinical_repository.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail='Document not found')
    return document


@router.get('/documents/{document_id}/content')
def get_document_raw_content(document_id: UUID):
    document = clinical_repository.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail='Document not found')
    content = clinical_repository.get_document_content(document_id)
    if not content:
        raise HTTPException(status_code=404, detail='Document content unavailable')
    from fastapi.responses import Response
    return Response(content=content, media_type=document.file_type or "application/octet-stream")


@router.post('/documents/{document_id}/ocr', response_model=DocumentResponse)
def process_document_ocr(document_id: UUID):
    document = clinical_repository.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail='Document not found')
    content = clinical_repository.get_document_content(document_id)
    if content is None:
        raise HTTPException(status_code=404, detail='Document content unavailable')
    try:
        result = LocalOCRService().extract(content, document.file_name, document.file_type)
    except OCRServiceError as exc:
        document.ocr_status = 'failed'
        clinical_repository.update_document(document)
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    document.ocr_status = 'completed'
    document.document_type = result.document_type or document.document_type
    # The patient/clinician classification is authoritative for temporal routing.
    # OCR may supply a date, but never silently changes current vs historical.
    extracted_date = None
    ocr_dict = result.model_dump(mode='json')
    extracted_data = ocr_dict.get("extracted_fields") or {}

    if isinstance(extracted_data, dict):
        ocr_dict["medications"] = extracted_data.get("medications", [])
        ocr_dict["lab_results"] = extracted_data.get("lab_results", [])
        ocr_dict["diagnoses"] = extracted_data.get("diagnoses", [])
        ocr_dict["vitals"] = extracted_data.get("vitals", [])
        ocr_dict["provider"] = extracted_data.get("provider")
        ocr_dict["clinic"] = extracted_data.get("clinic")
        extracted_date = extracted_data.get("date")
        ocr_dict["date"] = extracted_data.get("date") or document.document_date
        ocr_dict["summary"] = extracted_data.get("summary")

    # Temporal metadata is always explicit in the OCR result. If OCR found a date
    # and the patient did not provide one, record that as OCR-derived evidence.
    if extracted_date and not document.document_date:
        document.document_date = str(extracted_date)
        document.document_date_type = "exact"
        document.document_date_source = "ocr"
    ocr_dict["temporal_context"] = {
        "classification": document.document_classification,
        "classification_source": document.classification_source,
        "document_date": document.document_date,
        "document_date_type": document.document_date_type,
        "document_date_source": document.document_date_source,
        "temporal_status": document.temporal_status,
        "verification_status": document.verification_status,
        "uploaded_at": document.created_at.isoformat(),
    }

    # Attach the session's registered patient so the extraction review clearly
    # shows whose record this document belongs to.
    try:
        sess = clinical_repository.get_session(document.session_id)
        if sess is not None and sess.patient_id:
            pat = clinical_repository.get_patient(sess.patient_id)
            if pat is not None:
                patient_age = None
                try:
                    if pat.date_of_birth:
                        patient_age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(str(pat.date_of_birth)).date()).days // 365
                except Exception:
                    patient_age = None
                ocr_dict["registered_patient"] = {
                    "name": pat.display_name,
                    "date_of_birth": pat.date_of_birth or "",
                    "age": patient_age,
                    "gender": pat.gender or "",
                    "abha_id": pat.abha_id or "",
                    "phone": pat.phone or "",
                }
                reg_fields = [
                    {"label": "Patient Identification", "val": f"{pat.display_name} (ABHA: {pat.abha_id or 'Pending'})"},
                ]
                if pat.gender or patient_age is not None:
                    demog = f"{pat.gender or 'Patient'}" + (f", {patient_age} yrs" if patient_age is not None else "")
                    reg_fields.append({"label": "Demographics", "val": demog})

                if isinstance(extracted_data, dict) and isinstance(extracted_data.get("extracted_fields"), list):
                    extracted_data["extracted_fields"] = reg_fields + extracted_data["extracted_fields"]
    except Exception:
        logger.exception("OCR patient-context enrichment failed for %s", document.document_id)

    document.ocr = ocr_dict
    clinical_repository.update_document(document)

    # Ingest clinical findings into active session store & orchestrator state
    try:
        session_store = get_runtime_session_store()
        sess_key = str(document.session_id)
        stored = session_store.get(sess_key)
        if stored and stored.orchestrator_state:
            from core.schemas import DocumentExtraction, DocumentMedication, LabResult, DocumentEvidenceItem
            extracted_data = result.extracted_fields if isinstance(result.extracted_fields, dict) else {}
            meds = extracted_data.get("medications", [])
            labs = extracted_data.get("lab_results", [])
            diags = extracted_data.get("diagnoses", [])

            # Add to orchestrator documents
            doc_ext = DocumentExtraction(
                document_id=str(document.document_id),
                document_type=result.document_type or "Clinical Document",
                document_date=document.document_date,
                document_date_type=document.document_date_type,
                document_date_source=document.document_date_source,
                document_classification=document.document_classification,
                classification_source=document.classification_source,
                temporal_status=document.temporal_status,
                verification_status=document.verification_status,
                source_excerpt=result.raw_text,
                medications=[
                    DocumentMedication(
                        source_text=m.get("source_text") or result.raw_text or "Medication",
                        name_as_reported=m.get("name_as_reported", "Medication"),
                        dose_as_reported=m.get("dose_as_reported"),
                        frequency_as_reported=m.get("frequency_as_reported")
                    ) for m in meds if isinstance(m, dict)
                ],
                lab_results=[
                    LabResult(
                        source_text=l.get("source_text") or result.raw_text or "Lab Result",
                        test_name=l.get("test_name", "Test"),
                        value_as_reported=l.get("value_as_reported"),
                        unit_as_reported=l.get("unit_as_reported"),
                        reference_range_as_reported=l.get("reference_range_as_reported")
                    ) for l in labs if isinstance(l, dict)
                ],
                diagnoses_mentioned=[
                    DocumentEvidenceItem(
                        text=d.get("condition") or d.get("text") or "Documented Condition",
                        source_text=d.get("source") or result.raw_text or "Documented Condition",
                        uncertain=False,
                        source_type="document"
                    ) for d in diags if isinstance(d, dict)
                ],
                missing_or_illegible_sections=[],
            )
            orch_state = stored.orchestrator_state
            if "documents" not in orch_state or not isinstance(orch_state["documents"], list):
                orch_state["documents"] = []
            # Avoid duplicate document IDs
            orch_state["documents"] = [
                d for d in orch_state["documents"]
                if isinstance(d, dict) and d.get("document_id") != str(document.document_id)
            ]
            orch_state["documents"].append(doc_ext.model_dump(mode="json"))
            if "processed_document_keys" not in orch_state or not isinstance(orch_state["processed_document_keys"], list):
                orch_state["processed_document_keys"] = []
            if str(document.document_id) not in orch_state["processed_document_keys"]:
                orch_state["processed_document_keys"].append(str(document.document_id))

            # IMPORTANT: document-derived facts are kept as document/timeline evidence.
            # They are NOT copied into current medications or past medical history until
            # explicitly verified by the patient/clinician.
            patient_id = None
            sess_obj = clinical_repository.get_session(document.session_id)
            if sess_obj:
                patient_id = sess_obj.patient_id
            if patient_id:
                event_date = document.document_date
                db.save_clinical_event({
                    "event_id": f"document:{document.document_id}",
                    "patient_id": str(patient_id),
                    "session_id": str(document.session_id),
                    "event_type": "document",
                    "event_date": event_date,
                    "event_date_type": document.document_date_type,
                    "temporal_status": document.temporal_status,
                    "source_type": "document",
                    "source_id": str(document.document_id),
                    "confidence": (ocr_dict.get("ocr", {}) or {}).get("confidence") if isinstance(ocr_dict.get("ocr"), dict) else None,
                    "verification_status": document.verification_status,
                    "data": {
                        "file_name": document.file_name,
                        "document_type": document.document_type,
                        "classification": document.document_classification,
                        "medications": meds,
                        "diagnoses": diags,
                        "lab_results": labs,
                    },
                })

            # Re-run orchestrator summary stage so physician summary includes document findings
            if orch_state.get("clinical_history") and orch_state.get("risk_assessment"):
                try:
                    from core.orchestrator import MedicalOrchestrator
                    from core.schemas import OrchestrationState
                    orch_inst = MedicalOrchestrator(session_id=sess_key)
                    orch_inst.state = OrchestrationState.model_validate(orch_state)
                    orch_inst._run_summary()
                    if orch_inst.state.physician_summary:
                        orch_state["physician_summary"] = orch_inst.state.physician_summary.model_dump(mode="json")
                        clinical_repository.save_summary(
                            SummaryResponseV1(
                                session_id=document.session_id,
                                content=orch_state["physician_summary"],
                                updated_at=datetime.now(timezone.utc)
                            )
                        )
                except Exception as sum_e:
                    logger.warning("Summary refresh on OCR failed: %s", sum_e)

            stored.orchestrator_state = orch_state
            session_store.save(stored)
    except Exception as sync_exc:
        logger.warning("Session sync on OCR completed warning: %s", sync_exc)

    return document


@router.get('/documents/{document_id}/ocr', response_model=dict[str, Any])
def get_document_ocr(document_id: UUID):
    document = clinical_repository.get_document(document_id)
    if not document:
        raise HTTPException(status_code=404, detail='Document not found')
    if not document.ocr:
        raise HTTPException(status_code=404, detail='OCR result not found')
    return document.ocr


class EncounterContextRequest(BaseModel):
    department: str = "general"
    clinical_mode: str = "general"
    language: str = "en-IN"
    consent_granted: bool = False


@router.put('/sessions/{session_id}/encounter-context', response_model=dict[str, Any])
def save_encounter_context(session_id: UUID, request: EncounterContextRequest):
    require_session(session_id)
    if request.clinical_mode not in {"general", "ayush"}:
        raise HTTPException(status_code=400, detail="clinical_mode must be general or ayush")
    data = {**request.model_dump(), "updated_at": datetime.now(timezone.utc).isoformat()}
    db.save_clinical_data(str(session_id), "encounter-context", data)
    return data


class AyushAssessmentRequest(BaseModel):
    prakriti: str | None = None
    vikriti: str | None = None
    sara: str | None = None
    samhanana: str | None = None
    pramana: str | None = None
    satmya: str | None = None
    sattva: str | None = None
    ahara_shakti: str | None = None
    vyayama_shakti: str | None = None
    vaya: str | None = None
    ahara_vihara: dict[str, Any] = Field(default_factory=dict)
    source: str = "patient"
    verification_status: str = "pending"


@router.put('/sessions/{session_id}/ayush-assessment', response_model=dict[str, Any])
def save_ayush_assessment(session_id: UUID, request: AyushAssessmentRequest):
    require_session(session_id)
    data = request.model_dump()
    data["updated_at"] = datetime.now(timezone.utc).isoformat()
    db.save_clinical_data(str(session_id), "ayush-assessment", data)
    return data


@router.get('/sessions/{session_id}/ayush-assessment', response_model=dict[str, Any])
def get_ayush_assessment(session_id: UUID):
    require_session(session_id)
    return db.get_clinical_data(str(session_id), "ayush-assessment") or {}


@router.get('/sessions/{session_id}/encounter-context', response_model=dict[str, Any])
def get_encounter_context(session_id: UUID):
    require_session(session_id)
    return db.get_clinical_data(str(session_id), "encounter-context") or {
        "department": "general", "clinical_mode": "general", "language": "en-IN", "consent_granted": False
    }


@router.get('/patients/{patient_id}/documents', response_model=list[DocumentResponse])
def list_patient_documents(patient_id: UUID):
    patient = clinical_repository.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    with db._get_connection() as conn:
        rows = conn.execute(
            "SELECT d.* FROM documents d JOIN sessions s ON s.session_id = d.session_id WHERE s.patient_id = ? ORDER BY d.created_at ASC",
            (str(patient_id),)
        ).fetchall()
    result = []
    for row in rows:
        item = dict(row)
        if item.get("ocr_data"):
            try: item["ocr"] = json.loads(item.pop("ocr_data"))
            except Exception: item["ocr"] = None
        else:
            item["ocr"] = None
        result.append(DocumentResponse(
            document_id=UUID(item["document_id"]), session_id=UUID(item["session_id"]),
            file_name=item["file_name"], file_type=item["file_type"], file_size=item["file_size"],
            storage_path=item.get("storage_path") or "", upload_status=item.get("upload_status", "received"),
            ocr_status=item.get("ocr_status", "pending"), document_type=item.get("document_type"),
            ocr=item.get("ocr"), document_classification=item.get("document_classification", "historical"),
            classification_source=item.get("classification_source", "patient"), document_date=item.get("document_date"),
            document_date_type=item.get("document_date_type", "unknown"), document_date_source=item.get("document_date_source", "unknown"),
            temporal_status=item.get("temporal_status", "unknown"), verification_status=item.get("verification_status", "pending"),
            created_at=datetime.fromisoformat(item["created_at"]) if isinstance(item["created_at"], str) else item["created_at"]
        ))
    return result


@router.get('/patients/{patient_id}/timeline', response_model=list[dict[str, Any]])
def patient_timeline(patient_id: UUID):
    patient = clinical_repository.get_patient(patient_id)
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    return db.list_clinical_events(str(patient_id))


@router.post('/sessions/{session_id}/red-flags', response_model=RedFlagResponse, status_code=201)
def create_red_flag(session_id: UUID, request: RedFlagCreateRequest):
    require_session(session_id)
    flag = RedFlagResponse(
        red_flag_id=uuid4(),
        session_id=session_id,
        created_at=datetime.now(timezone.utc),
        **request.model_dump()
    )
    return clinical_repository.save_red_flag(flag)


@router.get('/sessions/{session_id}/red-flags', response_model=list[RedFlagResponse])
def get_red_flags(session_id: UUID):
    require_session(session_id)
    return clinical_repository.get_red_flags(session_id)


@router.post('/sessions/{session_id}/consent', response_model=ConsentResponse, status_code=201)
def create_consent(session_id: UUID, request: ConsentRequest):
    require_session(session_id)
    consent = ConsentResponse(
        consent_id=uuid4(),
        session_id=session_id,
        created_at=datetime.now(timezone.utc),
        **request.model_dump()
    )
    return clinical_repository.save_consent(consent)


@router.get('/sessions/{session_id}/consent', response_model=list[ConsentResponse])
def get_consent(session_id: UUID):
    require_session(session_id)
    return clinical_repository.get_consents(session_id)


@router.post('/sessions/{session_id}/generate-summary', response_model=SummaryResponseV1)
def generate_summary(session_id: UUID):
    session = require_session(session_id)
    sess_key = str(session_id)
    session_store = get_runtime_session_store()
    stored = session_store.get(sess_key)

    from core.orchestrator import MedicalOrchestrator
    from core.schemas import (
        OrchestrationState, ClinicalHistory, HistoryOfPresentIllness,
        RiskAssessment, RiskFlag, RiskSeverity, AttentionLevel, MedicationMention, DocumentExtraction
    )
    orch = MedicalOrchestrator(session_id=sess_key)
    if stored and stored.orchestrator_state:
        orch.state = OrchestrationState.model_validate(stored.orchestrator_state)

    # Load hospital encounter context and AYUSH assessment into the summary state.
    try:
        from core.schemas import AyushAssessment
        ayush_raw = db.get_clinical_data(sess_key, "ayush-assessment")
        if ayush_raw:
            orch.state.ayush_assessment = AyushAssessment.model_validate(ayush_raw)
    except Exception as exc:
        logger.warning("AYUSH summary context unavailable: %s", exc)

    # Pull fresh live clinical facts from clinical_repository
    live_cdata = clinical_repository.clinical_data.get(session_id, {})
    symptoms_raw = live_cdata.get('symptoms', [])
    symptoms_list = symptoms_raw.get('symptoms', []) if isinstance(symptoms_raw, dict) else (symptoms_raw if isinstance(symptoms_raw, list) else [])
    
    meds_raw = live_cdata.get('medications', [])
    meds_list = meds_raw.get('medications', []) if isinstance(meds_raw, dict) else (meds_raw if isinstance(meds_raw, list) else [])
    
    allergies_raw = live_cdata.get('allergies', [])
    allergies_list = allergies_raw.get('allergies', []) if isinstance(allergies_raw, dict) else (allergies_raw if isinstance(allergies_raw, list) else [])
    
    history_raw = live_cdata.get('medical-history') or live_cdata.get('medical_history') or []
    history_list = history_raw.get('conditions', []) if isinstance(history_raw, dict) else (history_raw if isinstance(history_raw, list) else [])
    
    family_raw = live_cdata.get('family-history') or live_cdata.get('family_history') or []
    family_list = family_raw.get('conditions', family_raw.get('family_history', [])) if isinstance(family_raw, dict) else (family_raw if isinstance(family_raw, list) else [])
    
    lifestyle_raw = live_cdata.get('lifestyle', [])
    lifestyle_list = lifestyle_raw.get('habits', lifestyle_raw.get('lifestyle', [])) if isinstance(lifestyle_raw, dict) else (lifestyle_raw if isinstance(lifestyle_raw, list) else [])

    # Extract primary complaint & symptoms
    raw_chief = live_cdata.get('chief_complaint') or (symptoms_list[0].get('name') if symptoms_list else 'Clinical evaluation')
    cleaned_chief = re.sub(r'^(?:I(?:\'ve| have)?(?: been experiencing| got| had| am having| am experiencing| feel| felt| have)?|Patient (?:has|is complaining of|presents with)|Suffering from|Complaining of|Experiencing)\s+', '', str(raw_chief), flags=re.IGNORECASE).strip()
    chief_str = cleaned_chief if cleaned_chief else 'Clinical evaluation'
    duration_str = symptoms_list[0].get('duration') if symptoms_list else 'Recorded on intake'
    location_str = symptoms_list[0].get('location') if symptoms_list else None
    severity_str = symptoms_list[0].get('severity') if symptoms_list else None

    # Construct or update clinical_history with live state
    med_mentions = []
    for m in meds_list:
        if isinstance(m, dict):
            name_val = m.get('name') or m.get('name_as_reported') or 'Medication'
            med_mentions.append(MedicationMention(
                name_as_reported=str(name_val),
                dose_as_reported=m.get('dosage') or m.get('dose_as_reported'),
                frequency_as_reported=m.get('frequency') or m.get('frequency_as_reported')
            ))
        elif isinstance(m, str):
            med_mentions.append(MedicationMention(name_as_reported=m))

    orch.state.clinical_history = ClinicalHistory(
        session_id=sess_key,
        chief_complaint=chief_str,
        chief_concern=chief_str,
        history_of_present_illness=HistoryOfPresentIllness(
            duration=duration_str,
            location=location_str,
            severity=severity_str
        ),
        reported_symptoms=[s.get('name', str(s)) if isinstance(s, dict) else str(s) for s in symptoms_list],
        past_medical_history=history_list,
        reported_medications=med_mentions,
        reported_allergies=[a.get('allergen', str(a)) if isinstance(a, dict) else str(a) for a in allergies_list],
        family_history=family_list,
        personal_history={"habits": lifestyle_list}
    )

    # Attach document extractions for rich multi-source clinical synthesis
    session_docs = clinical_repository.documents.get(session_id, [])
    doc_extractions = []
    for d in session_docs:
        ocr_d = getattr(d, 'ocr', {}) or {}
        ef = (ocr_d.get('extracted_fields') if isinstance(ocr_d.get('extracted_fields'), dict) else ocr_d) or {}
        doc_meds = [DocumentMedication(
            name_as_reported=(m.get('name_as_reported') or m.get('name') or 'Medication'),
            dose_as_reported=m.get('dose_as_reported') or m.get('dosage'),
            frequency_as_reported=m.get('frequency_as_reported') or m.get('frequency'),
            source_text=m.get('source_text') or ocr_d.get('raw_text') or ef.get('raw_text') or 'Medication',
            uncertain=bool(m.get('uncertain', False))
        ) for m in (ocr_d.get('medications') or ef.get('medications') or []) if isinstance(m, dict)]
        raw_date = ocr_d.get('date') or ocr_d.get('document_date') or getattr(d, 'document_date', None)
        raw_diags = ocr_d.get('diagnoses') or ef.get('diagnoses') or []
        from core.schemas import DocumentEvidenceItem, LabResult, DocumentMedication
        doc_extractions.append(DocumentExtraction(
            document_id=str(d.document_id),
            document_type=ocr_d.get('document_type') or ef.get('document_type') or 'Clinical Document',
            document_date=raw_date,
            document_date_type=getattr(d, 'document_date_type', 'unknown'),
            document_date_source=getattr(d, 'document_date_source', 'unknown'),
            document_classification=getattr(d, 'document_classification', 'historical'),
            classification_source=getattr(d, 'classification_source', 'patient'),
            temporal_status=getattr(d, 'temporal_status', 'unknown'),
            verification_status=getattr(d, 'verification_status', 'pending'),
            source_excerpt=ocr_d.get('raw_text') or ef.get('raw_text') or ocr_d.get('ocr_text', ''),
            medications=doc_meds,
            lab_results=[LabResult.model_validate(x) for x in (ocr_d.get('lab_results') or ef.get('lab_results') or []) if isinstance(x, dict) and x.get('test_name')],
            diagnoses_mentioned=[DocumentEvidenceItem(
                text=(x.get('condition') or x.get('name') or x.get('text') or 'Documented condition'),
                source_text=(x.get('source') or x.get('source_text') or ocr_d.get('raw_text') or 'Documented condition')
            ) for x in raw_diags if isinstance(x, dict)]
        ))
    if doc_extractions:
        orch.state.documents = doc_extractions

    # Initialize risk assessment if not present
    red_flags = clinical_repository.get_red_flags(session_id)
    r_flags = [
        RiskFlag(category=rf.flag_type, description=rf.description, severity=RiskSeverity(rf.severity.lower() if rf.severity in ['low','moderate','high'] else 'unknown'))
        for rf in red_flags
    ]
    att_level = AttentionLevel.URGENT if any(rf.severity.lower() == 'high' for rf in red_flags) else (
        AttentionLevel.ELEVATED if any(rf.severity.lower() == 'moderate' for rf in red_flags) else AttentionLevel.ROUTINE
    )
    orch.state.risk_assessment = RiskAssessment(
        session_id=sess_key,
        overall_attention_level=att_level,
        risk_flags=r_flags
    )

    # Run AI summary engine on live session facts
    orch._run_summary()

    # Compose detailed patient-specific summary content
    summary_content = {}
    if orch.state.physician_summary:
        summary_content = orch.state.physician_summary.model_dump(mode="json")
    
    # Ensure rich patient-specific overview
    is_generic = lambda w: not w or str(w).strip().lower() in (
        'clinical evaluation', 'not specified', 'general intake', '', 'intake', 'unknown', 'none', 'nothing', 'no symptoms recorded yet', 'clinical assessment', 'nil', 'n/a', 'no chronic conditions recorded'
    )

    valid_symptoms = [s.get('name', str(s)) if isinstance(s, dict) else str(s) for s in symptoms_list if not is_generic(s.get('name', str(s)) if isinstance(s, dict) else str(s))]
    valid_history = [c for c in history_list if not is_generic(c)]
    valid_meds = [m.get('name', str(m)) if isinstance(m, dict) else str(m) for m in meds_list if not is_generic(m.get('name', str(m)) if isinstance(m, dict) else str(m))]
    valid_allergies = [a.get('allergen', str(a)) if isinstance(a, dict) else str(a) for a in allergies_list if not is_generic(a.get('allergen', str(a)) if isinstance(a, dict) else str(a))]

    has_valid_chief = not is_generic(chief_str)
    has_valid_dur = bool(duration_str and str(duration_str).strip().lower() not in ('recorded on intake', 'unknown', 'none', '', 'recorded today'))

    overview_parts = []
    if has_valid_chief:
        sym_extra = ", ".join(valid_symptoms) if (valid_symptoms and ", ".join(valid_symptoms) != chief_str) else ""
        sym_desc = f"{chief_str}" + (f" ({sym_extra})" if sym_extra else "")
        overview_parts.append(f"Patient presenting with {sym_desc}" + (f" for {duration_str}." if has_valid_dur else "."))
    elif valid_symptoms:
        overview_parts.append(f"Patient presenting with {', '.join(valid_symptoms)}.")
    else:
        overview_parts.append("Patient presenting for routine clinical intake assessment and health profile review.")

    if valid_history:
        overview_parts.append(f"Documented medical history: {', '.join(valid_history)}.")
    if valid_meds:
        overview_parts.append(f"Active medications: {', '.join(valid_meds)}.")
    if valid_allergies:
        overview_parts.append(f"Allergies: {', '.join(valid_allergies)}.")
    overview_parts.append(f"Triage status: {att_level.value.upper()}.")

    dynamic_overview = " ".join(overview_parts)

    current_ov = summary_content.get("overview", "")
    if not current_ov or "No validated" in current_ov or "Summary generated from validated" in current_ov or "evaluation of Clinical evaluation" in current_ov or len(current_ov.strip()) < 15:
        summary_content["overview"] = dynamic_overview

    # Sanitize and deduplicate structured_history_highlights
    raw_highlights = summary_content.get("structured_history_highlights") or []
    cleaned_highlights = []
    for h in raw_highlights:
        if not h or not isinstance(h, str): continue
        h_lower = h.lower()
        if 'clinical evaluation' in h_lower or 'evaluation: general clinical' in h_lower or 'chief concern: none' in h_lower or 'chief concern: nothing' in h_lower:
            continue
        if h not in cleaned_highlights:
            cleaned_highlights.append(h)

    if not cleaned_highlights:
        if has_valid_chief:
            cleaned_highlights.append(f"Chief Concern: {chief_str}" + (f" ({duration_str})" if has_valid_dur else ""))
        if valid_history:
            cleaned_highlights.append(f"Medical History: {', '.join(valid_history)}")
        if valid_meds:
            cleaned_highlights.append(f"Active Medications: {', '.join(valid_meds)}")
        if valid_allergies:
            cleaned_highlights.append(f"Allergy Alert: {', '.join(valid_allergies)}")
        if not cleaned_highlights:
            cleaned_highlights.append("General clinical health intake completed.")

    summary_content["structured_history_highlights"] = cleaned_highlights

    # Sanitize and deduplicate questions_for_clinician
    raw_questions = summary_content.get("questions_for_clinician") or []
    cleaned_questions = []
    for q in raw_questions:
        if not q or not isinstance(q, str): continue
        q_str = q.strip()
        if q_str not in cleaned_questions:
            cleaned_questions.append(q_str)

    if not cleaned_questions:
        if valid_history:
            cleaned_questions.append(f"Review ongoing care and management for {', '.join(valid_history)}.")
        if valid_meds:
            cleaned_questions.append("Reconcile current medication schedule and check for drug-drug interactions.")
        if has_valid_chief:
            cleaned_questions.append("Correlate reported symptom timeline with physical examination findings.")
        else:
            cleaned_questions.append("Conduct baseline physical examination and vital signs review.")

    summary_content["questions_for_clinician"] = cleaned_questions

    summary_content["patient_clinical_snapshot"] = {
        "chief_complaint": chief_str,
        "symptoms": symptoms_list,
        "medical_history": history_list,
        "medications": meds_list,
        "allergies": allergies_list,
        "family_history": family_list,
        "lifestyle": lifestyle_list,
        "triage_level": att_level.value
    }

    if stored:
        stored.orchestrator_state = orch.state.model_dump()
        session_store.save(stored)

    summary = SummaryResponseV1(
        session_id=session_id,
        content=summary_content,
        updated_at=datetime.now(timezone.utc)
    )
    return clinical_repository.save_summary(summary)


@router.get('/sessions/{session_id}/summary', response_model=SummaryResponseV1)
def get_summary(session_id: UUID):
    require_session(session_id)
    summary = clinical_repository.get_summary(session_id)
    if not summary:
        raise HTTPException(status_code=404, detail='Summary not found')
    return summary


@router.get('/doctor/cases/{session_id}', response_model=dict[str, Any])
def get_doctor_case(session_id: UUID):
    session = require_session(session_id)
    patient = clinical_repository.get_patient(session.patient_id) if session.patient_id else None
    messages = clinical_repository.get_messages(session_id)
    documents = clinical_repository.get_documents(session_id)

    # Retrieve orchestrator state from runtime session store
    runtime_store = get_runtime_session_store()
    orch_summary = None
    orch_history = None
    orch_risk = None
    if runtime_store:
        stored_session = runtime_store.get(str(session_id))
        if stored_session and stored_session.orchestrator_state:
            orch_state = stored_session.orchestrator_state
            orch_summary = orch_state.get("physician_summary")
            orch_history = orch_state.get("clinical_history")
            orch_risk = orch_state.get("risk_assessment")

    summary_obj = orch_summary or clinical_repository.get_summary(session_id)
    if isinstance(summary_obj, SummaryResponseV1):
        summary_obj = summary_obj.content

    patient_payload = patient.model_dump(mode="json") if patient else {
        "patient_id": str(session.patient_id),
        "display_name": "Registered Patient",
        "abha_id": "ABHA-Pending",
        "date_of_birth": "Not documented",
        "phone": "Not documented"
    }

    case_data = {
        "session_id": str(session_id),
        "status": session.status,
        "patient": patient_payload,
        "summary": summary_obj or {"overview": "Case assessment ready for clinical review"},
        "messages": [m.model_dump(mode="json") for m in messages],
        "documents": [d.model_dump(mode="json") for d in documents],
        "clinical_history": orch_history or clinical_repository.clinical_data.get(session_id, {}),
        "risk_assessment": orch_risk,
        "created_at": session.started_at.isoformat() if session.started_at else None,
    }

    clinical_repository.save_doctor_case(session_id, case_data)
    return case_data


@router.get('/doctor/cases', response_model=list[dict[str, Any]])
def list_doctor_cases():
    results = []
    for s_id in list(clinical_repository.sessions.keys()):
        try:
            case = get_doctor_case(s_id)
            results.append(case)
        except Exception:
            pass
    return results


@router.put('/doctor/cases/{session_id}', response_model=dict[str, Any])
def update_doctor_case(session_id: UUID, request: DataPayload):
    require_session(session_id)
    case = {
        'session_id': str(session_id),
        'status': 'reviewed',
        'content': request.data,
        'updated_at': datetime.now(timezone.utc).isoformat()
    }
    return clinical_repository.save_doctor_case(session_id, case)


# =========================================================================
# USER AUTHENTICATION & PROFILE SETTINGS ENDPOINTS
# =========================================================================

@router.post('/auth/register', response_model=AuthResponse)
def register_user(request: AuthRegisterRequest):
    user, session = clinical_repository.create_user(request)
    token = f"token_{user.user_id}_{int(datetime.now(timezone.utc).timestamp())}"
    return AuthResponse(
        user=UserProfile.model_validate(user.model_dump()),
        token=token,
        patient_id=user.patient_id,
        session_id=session.session_id,
        message="Account registered successfully"
    )


@router.post('/auth/login', response_model=AuthResponse)
def login_user(request: AuthLoginRequest):
    res = clinical_repository.authenticate_user(request)
    if not res:
        raise HTTPException(status_code=401, detail="Invalid email or password")
    user, session = res
    token = f"token_{user.user_id}_{int(datetime.now(timezone.utc).timestamp())}"
    return AuthResponse(
        user=UserProfile.model_validate(user.model_dump()),
        token=token,
        patient_id=user.patient_id,
        session_id=session.session_id,
        message=f"Welcome back, {user.display_name}!"
    )


@router.post('/auth/logout')
def logout_user():
    return {"status": "ok", "message": "Signed out successfully"}


@router.get('/auth/me', response_model=UserProfile)
def get_current_user(email: str | None = None, user_id: UUID | None = None):
    if user_id:
        user = clinical_repository.get_user_by_id(user_id)
        if user:
            return UserProfile.model_validate(user.model_dump())
    if email:
        user = clinical_repository.get_user_by_email(email)
        if user:
            return UserProfile.model_validate(user.model_dump())
    raise HTTPException(status_code=404, detail="User not found")


@router.put('/auth/profile', response_model=UserProfile)
def update_profile(request: ProfileUpdateRequest, email: str | None = None, user_id: UUID | None = None):
    target_user = None
    if user_id:
        target_user = clinical_repository.get_user_by_id(user_id)
    elif email:
        target_user = clinical_repository.get_user_by_email(email)

    if not target_user:
        raise HTTPException(status_code=404, detail="User profile not found")
        
    updated = clinical_repository.update_user_profile(target_user.user_id, request)
    return UserProfile.model_validate(updated.model_dump())


@router.post('/auth/send-verification-code')
async def send_verification_code(request: SendVerificationCodeRequest):
    user = clinical_repository.get_user_by_email(request.email)
    code = email_verification_service.generate_code(request.email, user.user_id if user else None)
    display_name = user.display_name if user else "Patient"
    res = await email_verification_service.send_verification_email(request.email, code, display_name)
    return res


@router.post('/auth/change-password')
def change_password(request: ChangePasswordRequest, email: str | None = None, user_id: UUID | None = None):
    target_user = None
    if user_id:
        target_user = clinical_repository.get_user_by_id(user_id)
    elif email:
        target_user = clinical_repository.get_user_by_email(email)

    if not target_user and request.user_id:
        target_user = clinical_repository.get_user_by_id(request.user_id)

    if not target_user:
        raise HTTPException(status_code=404, detail="User account not found")
        
    success = clinical_repository.change_user_password(target_user.user_id, request)
    return {"status": "ok", "message": "Password updated successfully. Please use your new password next time you sign in."}


@router.post('/auth/change-email', response_model=UserProfile)
def change_email(request: ChangeEmailRequest, email: str | None = None, user_id: UUID | None = None):
    target_user = None
    if user_id:
        target_user = clinical_repository.get_user_by_id(user_id)
    elif email:
        target_user = clinical_repository.get_user_by_email(email)

    if not target_user and request.user_id:
        target_user = clinical_repository.get_user_by_id(request.user_id)

    if not target_user:
        raise HTTPException(status_code=404, detail="User account not found")

    updated = clinical_repository.change_user_email(target_user.user_id, request)
    return UserProfile.model_validate(updated.model_dump())


@router.get('/users/{user_id}/patient-history', response_model=dict[str, Any])
def get_user_patient_history(user_id: UUID):
    return clinical_repository.get_user_patient_history(user_id)


# =============================================================================
# HOSPITAL WORKFLOW ENDPOINTS
# =============================================================================

class SessionHospitalUpdate(BaseModel):
    department: str | None = None          # general, cardiology, ortho, paediatrics, ayush, etc.
    opd_mode: str | None = None            # general | ayush
    token_number: int | None = None
    triage_level: str | None = None        # routine | urgent | emergency
    consent_given: bool | None = None
    language_preference: str | None = None


class DoctorVerifyRequest(BaseModel):
    doctor_id: str = "Dr. Arvind Kumar, MD"
    doctor_notes: str                      # mandatory — doctor must add clinical notes
    triage_level: str | None = None        # allow doctor to upgrade/downgrade triage
    follow_up_days: int | None = None      # optional days until return consultation
    follow_up_reason: str | None = None    # clinical reason for follow-up


@router.patch('/sessions/{session_id}/hospital')
def update_session_hospital(session_id: UUID, req: SessionHospitalUpdate):
    """Update hospital routing fields on an existing session (department, OPD mode, token, consent)."""
    existing = db.get_session(str(session_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Session not found")
    
    fields: dict[str, Any] = {}
    if req.department is not None:
        fields["department"] = req.department
    if req.opd_mode is not None:
        fields["opd_mode"] = req.opd_mode
    if req.token_number is not None:
        fields["token_number"] = req.token_number
    if req.triage_level is not None:
        fields["triage_level"] = req.triage_level
    if req.consent_given is not None:
        fields["consent_given"] = 1 if req.consent_given else 0
    if req.language_preference is not None:
        fields["language_preference"] = req.language_preference

    if fields:
        db.update_session_hospital_fields(str(session_id), fields)

    updated = db.get_session(str(session_id))
    return updated or {"session_id": str(session_id), **fields, "status": "updated"}


@router.get('/doctor/queue')
def get_doctor_queue(department: str | None = None, limit: int = 100):
    """Return the list of active patient sessions queued for doctor review.
    
    Filters by department if provided. Returns patient demographics, triage level,
    token number, and session metadata needed for the doctor dashboard.
    """
    rows = db.get_doctor_queue(department=department, limit=limit)
    queue = []
    for r in rows:
        queue.append({
            "session_id": r.get("session_id"),
            "patient_id": r.get("patient_id"),
            "display_name": r.get("display_name") or "Anonymous Patient",
            "abha_id": r.get("abha_id"),
            "gender": r.get("gender"),
            "date_of_birth": r.get("date_of_birth"),
            "phone": r.get("phone"),
            "department": r.get("department", "general"),
            "opd_mode": r.get("opd_mode", "general"),
            "token_number": r.get("token_number", 0),
            "triage_level": r.get("triage_level", "routine"),
            "consent_given": bool(r.get("consent_given", 0)),
            "language_preference": r.get("language_preference", "en"),
            "doctor_verified": bool(r.get("doctor_verified", 0)),
            "started_at": r.get("started_at"),
            "status": r.get("status"),
        })
    return {"queue": queue, "total": len(queue)}


@router.post('/doctor/cases/{session_id}/verify')
def doctor_verify_case(session_id: UUID, req: DoctorVerifyRequest):
    """Doctor verification step: marks a session as verified by a clinician.
    
    Per clinical policy, the AI-generated summary is NOT automatically saved as 
    a final medical record. Doctor must provide notes to complete verification.
    This fulfills the mandatory doctor verification step before records are finalized.
    """
    existing = db.get_session(str(session_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Session not found")
    
    if not req.doctor_notes or not req.doctor_notes.strip():
        raise HTTPException(
            status_code=422,
            detail="Doctor notes are mandatory for verification. AI-generated summary is not automatically saved as a final medical record."
        )
    
    now_str = datetime.now(timezone.utc).isoformat()
    fields: dict[str, Any] = {
        "doctor_verified": 1,
        "doctor_notes": req.doctor_notes.strip(),
        "doctor_verified_at": now_str,
        "status": "verified",
    }
    if req.triage_level:
        fields["triage_level"] = req.triage_level

    db.update_session_hospital_fields(str(session_id), fields)

    created_follow_up = None
    if (req.follow_up_days or req.follow_up_reason) and existing.get("patient_id"):
        from datetime import timedelta
        days = req.follow_up_days if req.follow_up_days and req.follow_up_days > 0 else 14
        target_dt = (datetime.now(timezone.utc) + timedelta(days=days)).strftime("%Y-%m-%d")
        f_id = str(uuid4())
        created_follow_up = {
            "follow_up_id": f_id,
            "patient_id": str(existing["patient_id"]),
            "related_visit_id": str(session_id),
            "follow_up_date": target_dt,
            "reason": req.follow_up_reason or "Clinical progress evaluation",
            "department": existing.get("department", "general"),
            "doctor_or_unit": req.doctor_id,
            "status": "scheduled",
            "notes": req.doctor_notes[:200] if req.doctor_notes else None
        }
        try:
            db.save_follow_up(created_follow_up)
        except Exception as f_err:
            logger.warning("Could not save follow-up from doctor verification: %s", f_err)

    return {
        "session_id": str(session_id),
        "doctor_id": req.doctor_id,
        "verified": True,
        "verified_at": now_str,
        "follow_up": created_follow_up,
        "message": "Case verified by clinician. Doctor notes recorded. EMR finalized.",
    }


@router.get('/hospital/stats')
def get_hospital_stats():
    """Returns real-time KPI metrics, department distributions, and system statistics."""
    return db.get_live_hospital_stats()


@router.get('/hospital/documents/recent')
def get_recent_hospital_documents(limit: int = 10):
    """Returns recent documents processed across active sessions with OCR status."""
    return db.get_recent_hospital_documents(limit=limit)


@router.get('/hospital/alerts')
def get_hospital_alerts(limit: int = 10):
    """Returns real-time emergency and urgent red-flag alerts."""
    return db.get_hospital_alerts(limit=limit)


# =============================================================================
# LONGITUDINAL PATIENT RECORD & VISITS
# =============================================================================

class VisitCreateRequest(BaseModel):
    department: str = "general"
    opd_mode: str = "general"
    reason_for_visit: str | None = None
    chief_complaint: str | None = None
    language_preference: str = "en"
    parent_visit_id: str | None = None
    follow_up_id: str | None = None
    consent_given: bool = True


class BaselineProfileUpdateRequest(BaseModel):
    allergies: list[Any] | None = None
    chronic_conditions: list[Any] | None = None
    active_medications: list[Any] | None = None
    medical_history: list[Any] | None = None
    ayush_profile: dict[str, Any] | None = None


class FollowUpCreateRequest(BaseModel):
    patient_id: UUID
    related_visit_id: UUID
    follow_up_date: str  # YYYY-MM-DD
    reason: str | None = None
    department: str = "general"
    doctor_or_unit: str | None = None
    notes: str | None = None


class FollowUpUpdateRequest(BaseModel):
    status: str | None = None
    notes: str | None = None


class AYUSHAssessmentRequest(BaseModel):
    patient_id: UUID
    session_id: UUID
    assessment_date: str | None = None
    prakriti: str | None = None
    vikriti: str | None = None
    sara: str | None = None
    samhanana: str | None = None
    pramana: str | None = None
    satmya: str | None = None
    sattva: str | None = None
    ahara_shakti: str | None = None
    vyayama_shakti: str | None = None
    vaya: str | None = None
    ahara_vihara: dict[str, Any] | None = None


@router.get('/patients/{patient_id}/full-profile')
def get_patient_full_profile(patient_id: UUID):
    """Retrieve complete longitudinal medical profile: demographics, baseline, all visits, docs, timeline, followups."""
    profile = db.get_longitudinal_patient_profile(str(patient_id))
    if not profile:
        raise HTTPException(status_code=404, detail="Patient profile not found")
    return profile


@router.post('/patients/{patient_id}/profile/baseline')
def update_patient_baseline(patient_id: UUID, req: BaselineProfileUpdateRequest):
    """Safely append and merge baseline medical data without overwriting previous visit records."""
    patient = db.get_patient(str(patient_id))
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")
    data = req.model_dump(exclude_unset=True)
    updated = db.update_patient_baseline_profile(str(patient_id), data)
    return {"status": "ok", "baseline": updated}


@router.post('/patients/{patient_id}/visits')
def create_patient_visit(patient_id: UUID, req: VisitCreateRequest):
    """Create a new discrete visit for returning or new patient, preserving all historical visits."""
    patient = db.get_patient(str(patient_id))
    if not patient:
        raise HTTPException(status_code=404, detail="Patient not found")

    new_session_id = str(uuid4())
    token_number = db.get_next_token_number()
    now_str = datetime.now(timezone.utc).isoformat()

    sess_dict = {
        "session_id": new_session_id,
        "patient_id": str(patient_id),
        "status": "active",
        "source": "web",
        "started_at": now_str,
        "department": req.department,
        "opd_mode": req.opd_mode,
        "token_number": token_number,
        "triage_level": "routine",
        "doctor_verified": 0,
        "consent_given": 1 if req.consent_given else 0,
        "language_preference": req.language_preference,
        "parent_visit_id": req.parent_visit_id,
        "reason_for_visit": req.reason_for_visit or req.chief_complaint,
        "chief_complaint": req.chief_complaint,
        "follow_up_id": req.follow_up_id,
    }
    db.save_session(sess_dict)

    if req.follow_up_id:
        db.update_follow_up_status(
            req.follow_up_id,
            status="completed",
            notes=f"Patient returned for follow-up visit on {now_str[:10]} (Token #{token_number})"
        )

    # Initialize orchestrator state so AI adaptive questioning is active immediately
    try:
        from core.orchestrator import MedicalOrchestrator
        orchestrator = MedicalOrchestrator(session_id=UUID(new_session_id), patient_id=patient_id)
        if req.chief_complaint:
            orchestrator.state.clinical_history.chief_complaint = req.chief_complaint
        # Prepopulate baseline chronic conditions & allergies from patient longitudinal profile
        if patient.get("allergies_json"):
            try:
                algs = json.loads(patient["allergies_json"])
                for a in algs:
                    a_name = a if isinstance(a, str) else (a.get("allergen") or a.get("name") or "")
                    if a_name and a_name not in orchestrator.state.clinical_history.allergies:
                        orchestrator.state.clinical_history.allergies.append(a_name)
            except Exception:
                pass
        if patient.get("chronic_conditions_json"):
            try:
                conds = json.loads(patient["chronic_conditions_json"])
                for c in conds:
                    c_name = c if isinstance(c, str) else (c.get("condition") or c.get("name") or "")
                    if c_name and c_name not in orchestrator.state.clinical_history.past_medical_history:
                        orchestrator.state.clinical_history.past_medical_history.append(c_name)
            except Exception:
                pass

        session_store = get_runtime_session_store()
        session_store.set(new_session_id, orchestrator.to_session_state())
        db.save_orchestrator_state(new_session_id, orchestrator.state.model_dump(mode="json"))
    except Exception as exc:
        logger.warning("Failed to initialize orchestrator session state: %s", exc)

    return {
        "session_id": new_session_id,
        "patient_id": str(patient_id),
        "token_number": token_number,
        "department": req.department,
        "opd_mode": req.opd_mode,
        "status": "active",
        "started_at": now_str,
        "parent_visit_id": req.parent_visit_id,
        "follow_up_id": req.follow_up_id,
        "chief_complaint": req.chief_complaint,
    }


@router.get('/patients/{patient_id}/follow-ups')
def list_patient_follow_ups(patient_id: UUID):
    return db.list_follow_ups_for_patient(str(patient_id))


@router.post('/follow-ups')
def create_follow_up(req: FollowUpCreateRequest):
    follow_up_id = str(uuid4())
    f_dict = {
        "follow_up_id": follow_up_id,
        "patient_id": str(req.patient_id),
        "related_visit_id": str(req.related_visit_id),
        "follow_up_date": req.follow_up_date,
        "reason": req.reason,
        "department": req.department,
        "doctor_or_unit": req.doctor_or_unit,
        "status": "scheduled",
        "notes": req.notes,
    }
    db.save_follow_up(f_dict)
    return f_dict


@router.patch('/follow-ups/{follow_up_id}')
def update_follow_up(follow_up_id: UUID, req: FollowUpUpdateRequest):
    existing = db.get_follow_up(str(follow_up_id))
    if not existing:
        raise HTTPException(status_code=404, detail="Follow up not found")
    status = req.status or existing.get("status", "scheduled")
    db.update_follow_up_status(str(follow_up_id), status=status, notes=req.notes)
    return db.get_follow_up(str(follow_up_id))


@router.post('/follow-ups/{follow_up_id}/return-visit')
def convert_follow_up_to_return_visit(follow_up_id: UUID):
    follow_up = db.get_follow_up(str(follow_up_id))
    if not follow_up:
        raise HTTPException(status_code=404, detail="Follow up record not found")

    patient_id = UUID(follow_up["patient_id"])
    parent_visit_id = follow_up.get("related_visit_id")
    dept = follow_up.get("department") or "general"
    reason = follow_up.get("reason") or "Follow-up consultation"

    visit_req = VisitCreateRequest(
        department=dept,
        reason_for_visit=reason,
        chief_complaint=reason,
        parent_visit_id=parent_visit_id,
        follow_up_id=str(follow_up_id),
    )
    return create_patient_visit(patient_id, visit_req)


@router.get('/patients/{patient_id}/ayush')
def get_patient_ayush_assessments(patient_id: UUID):
    return db.list_ayush_assessments_for_patient(str(patient_id))


@router.post('/patients/{patient_id}/ayush')
def create_patient_ayush_assessment(patient_id: UUID, req: AYUSHAssessmentRequest):
    assessment_id = str(uuid4())
    a_dict = {
        "assessment_id": assessment_id,
        "patient_id": str(patient_id),
        "session_id": str(req.session_id),
        "assessment_date": req.assessment_date or datetime.now(timezone.utc).isoformat(),
        "prakriti": req.prakriti,
        "vikriti": req.vikriti,
        "sara": req.sara,
        "samhanana": req.samhanana,
        "pramana": req.pramana,
        "satmya": req.satmya,
        "sattva": req.sattva,
        "ahara_shakti": req.ahara_shakti,
        "vyayama_shakti": req.vyayama_shakti,
        "vaya": req.vaya,
        "ahara_vihara": req.ahara_vihara or {},
    }
    db.save_ayush_assessment(a_dict)
    return a_dict

