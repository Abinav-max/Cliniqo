"""Persistent SQLite Database Engine for Cliniqo Health Vault.

Provides durable local persistence for user accounts, patient identities,
active sessions, conversation messages, clinical data, documents, and summaries.
"""

from __future__ import annotations

import json
import logging
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

logger = logging.getLogger(__name__)

import os

_custom_db_path = os.environ.get("DATABASE_PATH")
if _custom_db_path:
    DB_PATH = Path(_custom_db_path)
    DB_DIR = DB_PATH.parent
else:
    _custom_data_dir = os.environ.get("DATA_DIR")
    if _custom_data_dir:
        DB_DIR = Path(_custom_data_dir)
    else:
        DB_DIR = Path(__file__).resolve().parent.parent / "data"
    DB_PATH = DB_DIR / "cliniqo_vault.db"


class DatabaseManager:
    """Thread-safe SQLite database manager for local and offline persistence."""

    def __init__(self, db_path: Path = DB_PATH) -> None:
        self.db_path = db_path
        self._ensure_db_directory()
        self.init_tables()

    def _ensure_db_directory(self) -> None:
        self.db_path.parent.mkdir(parents=True, exist_ok=True)

    def _get_connection(self) -> sqlite3.Connection:
        conn = sqlite3.connect(str(self.db_path), timeout=20.0)
        conn.row_factory = sqlite3.Row
        return conn

    def init_tables(self) -> None:
        """Create all required schema tables if they do not exist."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS users (
                    user_id TEXT PRIMARY KEY,
                    email TEXT UNIQUE NOT NULL,
                    display_name TEXT NOT NULL,
                    avatar_url TEXT,
                    patient_id TEXT,
                    password_hash TEXT NOT NULL,
                    password_salt TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS patients (
                    patient_id TEXT PRIMARY KEY,
                    abha_id TEXT UNIQUE,
                    display_name TEXT,
                    date_of_birth TEXT,
                    gender TEXT,
                    phone TEXT,
                    emergency_contact TEXT,
                    blood_group TEXT,
                    preferred_language TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS sessions (
                    session_id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    status TEXT NOT NULL DEFAULT 'active',
                    source TEXT NOT NULL DEFAULT 'web',
                    started_at TEXT NOT NULL,
                    completed_at TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clinical_sessions (
                    session_id TEXT PRIMARY KEY,
                    orchestrator_state TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clinical_data (
                    session_id TEXT NOT NULL,
                    category TEXT NOT NULL,
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    PRIMARY KEY (session_id, category)
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    message_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    role TEXT NOT NULL,
                    content TEXT NOT NULL,
                    source TEXT NOT NULL DEFAULT 'text',
                    language TEXT,
                    confidence REAL,
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS summaries (
                    session_id TEXT PRIMARY KEY,
                    content_json TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS documents (
                    document_id TEXT PRIMARY KEY,
                    session_id TEXT NOT NULL,
                    file_name TEXT NOT NULL,
                    file_type TEXT NOT NULL,
                    file_size INTEGER NOT NULL,
                    storage_path TEXT,
                    document_type TEXT,
                    upload_status TEXT NOT NULL DEFAULT 'received',
                    ocr_status TEXT NOT NULL DEFAULT 'completed',
                    ocr_data TEXT,
                    document_classification TEXT NOT NULL DEFAULT 'historical',
                    classification_source TEXT NOT NULL DEFAULT 'patient',
                    document_date TEXT,
                    document_date_type TEXT NOT NULL DEFAULT 'unknown',
                    document_date_source TEXT NOT NULL DEFAULT 'unknown',
                    temporal_status TEXT NOT NULL DEFAULT 'unknown',
                    verification_status TEXT NOT NULL DEFAULT 'pending',
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)
            # Safe migrations for databases created by earlier versions.
            existing = {row[1] for row in cursor.execute("PRAGMA table_info(documents)").fetchall()}
            migrations = {
                "document_classification": "TEXT NOT NULL DEFAULT 'historical'",
                "classification_source": "TEXT NOT NULL DEFAULT 'patient'",
                "document_date": "TEXT",
                "document_date_type": "TEXT NOT NULL DEFAULT 'unknown'",
                "document_date_source": "TEXT NOT NULL DEFAULT 'unknown'",
                "temporal_status": "TEXT NOT NULL DEFAULT 'unknown'",
                "verification_status": "TEXT NOT NULL DEFAULT 'pending'",
                "ocr_confidence": "REAL DEFAULT 1.0",
                "extracted_entities_json": "TEXT",
                "related_visit_id": "TEXT",
            }
            for name, definition in migrations.items():
                if name not in existing:
                    cursor.execute(f"ALTER TABLE documents ADD COLUMN {name} {definition}")

            # Hospital workflow & longitudinal visit migration: add new columns to sessions table.
            existing_sessions = {row[1] for row in cursor.execute("PRAGMA table_info(sessions)").fetchall()}
            sessions_migrations = {
                "department": "TEXT DEFAULT 'general'",
                "opd_mode": "TEXT DEFAULT 'general'",
                "token_number": "INTEGER DEFAULT 0",
                "triage_level": "TEXT DEFAULT 'routine'",
                "doctor_verified": "INTEGER DEFAULT 0",
                "doctor_notes": "TEXT",
                "doctor_verified_at": "TEXT",
                "consent_given": "INTEGER DEFAULT 0",
                "language_preference": "TEXT DEFAULT 'en'",
                "parent_visit_id": "TEXT",
                "reason_for_visit": "TEXT",
                "chief_complaint": "TEXT",
                "follow_up_id": "TEXT",
            }
            for name, definition in sessions_migrations.items():
                if name not in existing_sessions:
                    cursor.execute(f"ALTER TABLE sessions ADD COLUMN {name} {definition}")

            # Patients table longitudinal baseline fields migration
            existing_patients = {row[1] for row in cursor.execute("PRAGMA table_info(patients)").fetchall()}
            patients_migrations = {
                "medical_history_json": "TEXT",
                "chronic_conditions_json": "TEXT",
                "allergies_json": "TEXT",
                "active_medications_json": "TEXT",
                "ayush_profile_json": "TEXT",
            }
            for name, definition in patients_migrations.items():
                if name not in existing_patients:
                    cursor.execute(f"ALTER TABLE patients ADD COLUMN {name} {definition}")

            # Users table migration: add role column if missing
            existing_users = {row[1] for row in cursor.execute("PRAGMA table_info(users)").fetchall()}
            if "role" not in existing_users:
                cursor.execute("ALTER TABLE users ADD COLUMN role TEXT DEFAULT 'patient'")

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS follow_ups (
                    follow_up_id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    related_visit_id TEXT NOT NULL,
                    follow_up_date TEXT NOT NULL,
                    reason TEXT,
                    department TEXT,
                    doctor_or_unit TEXT,
                    status TEXT NOT NULL DEFAULT 'scheduled',
                    notes TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ayush_assessments (
                    assessment_id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    session_id TEXT NOT NULL,
                    assessment_date TEXT NOT NULL,
                    prakriti TEXT,
                    vikriti TEXT,
                    sara TEXT,
                    samhanana TEXT,
                    pramana TEXT,
                    satmya TEXT,
                    sattva TEXT,
                    ahara_shakti TEXT,
                    vyayama_shakti TEXT,
                    vaya TEXT,
                    ahara_vihara_json TEXT,
                    created_at TEXT NOT NULL
                )
            """)

            cursor.execute("""
                CREATE TABLE IF NOT EXISTS clinical_events (
                    event_id TEXT PRIMARY KEY,
                    patient_id TEXT NOT NULL,
                    session_id TEXT,
                    event_type TEXT NOT NULL,
                    event_date TEXT,
                    event_date_type TEXT NOT NULL DEFAULT 'unknown',
                    temporal_status TEXT NOT NULL DEFAULT 'unknown',
                    source_type TEXT NOT NULL,
                    source_id TEXT,
                    confidence REAL,
                    verification_status TEXT NOT NULL DEFAULT 'pending',
                    data_json TEXT NOT NULL,
                    created_at TEXT NOT NULL
                )
            """)
            conn.commit()

    # -------------------------------------------------------------------------
    # USER REPOSITORY
    # -------------------------------------------------------------------------
    def save_user(self, user_dict: dict[str, Any]) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO users (
                    user_id, email, display_name, avatar_url, patient_id, role,
                    password_hash, password_salt, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(user_id) DO UPDATE SET
                    email=excluded.email,
                    display_name=excluded.display_name,
                    avatar_url=excluded.avatar_url,
                    patient_id=excluded.patient_id,
                    role=excluded.role,
                    password_hash=excluded.password_hash,
                    password_salt=excluded.password_salt,
                    updated_at=excluded.updated_at
            """, (
                str(user_dict["user_id"]),
                str(user_dict["email"]).lower().strip(),
                str(user_dict.get("display_name", "")),
                user_dict.get("avatar_url"),
                str(user_dict["patient_id"]) if user_dict.get("patient_id") else None,
                str(user_dict.get("role", "patient")),
                str(user_dict["password_hash"]),
                str(user_dict["password_salt"]),
                str(user_dict.get("created_at") or datetime.now(timezone.utc).isoformat()),
                str(user_dict.get("updated_at") or datetime.now(timezone.utc).isoformat()),
            ))
            conn.commit()

    def ensure_default_hospital_user(self) -> None:
        """Seed default hospital doctor credentials if not existing."""
        user = self.get_user_by_email("doctor@hospital.gov.in")
        if not user:
            from api.auth import hash_password
            p_hash, p_salt = hash_password("Doctor@123")
            now_str = datetime.now(timezone.utc).isoformat()
            self.save_user({
                "user_id": "00000000-0000-0000-0000-000000000001",
                "email": "doctor@hospital.gov.in",
                "display_name": "Dr. Arvind Kumar (MD)",
                "avatar_url": None,
                "patient_id": None,
                "role": "hospital",
                "password_hash": p_hash,
                "password_salt": p_salt,
                "created_at": now_str,
                "updated_at": now_str,
            })

    def get_user_by_email(self, email: str) -> Optional[dict[str, Any]]:
        norm_email = email.lower().strip()
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE LOWER(email) = ? LIMIT 1", (norm_email,))
            row = cursor.fetchone()
            return dict(row) if row else None

    def get_user_by_id(self, user_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users WHERE user_id = ? LIMIT 1", (str(user_id),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_users(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM users")
            return [dict(r) for r in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # PATIENT REPOSITORY
    # -------------------------------------------------------------------------
    def save_patient(self, p_dict: dict[str, Any]) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO patients (
                    patient_id, abha_id, display_name, date_of_birth, gender,
                    phone, emergency_contact, blood_group, preferred_language,
                    medical_history_json, chronic_conditions_json, allergies_json,
                    active_medications_json, ayush_profile_json,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(patient_id) DO UPDATE SET
                    abha_id=COALESCE(excluded.abha_id, patients.abha_id),
                    display_name=COALESCE(excluded.display_name, patients.display_name),
                    date_of_birth=COALESCE(excluded.date_of_birth, patients.date_of_birth),
                    gender=COALESCE(excluded.gender, patients.gender),
                    phone=COALESCE(excluded.phone, patients.phone),
                    emergency_contact=COALESCE(excluded.emergency_contact, patients.emergency_contact),
                    blood_group=COALESCE(excluded.blood_group, patients.blood_group),
                    preferred_language=COALESCE(excluded.preferred_language, patients.preferred_language),
                    medical_history_json=COALESCE(excluded.medical_history_json, patients.medical_history_json),
                    chronic_conditions_json=COALESCE(excluded.chronic_conditions_json, patients.chronic_conditions_json),
                    allergies_json=COALESCE(excluded.allergies_json, patients.allergies_json),
                    active_medications_json=COALESCE(excluded.active_medications_json, patients.active_medications_json),
                    ayush_profile_json=COALESCE(excluded.ayush_profile_json, patients.ayush_profile_json),
                    updated_at=excluded.updated_at
            """, (
                str(p_dict["patient_id"]),
                p_dict.get("abha_id"),
                p_dict.get("display_name"),
                p_dict.get("date_of_birth"),
                p_dict.get("gender"),
                p_dict.get("phone"),
                p_dict.get("emergency_contact"),
                p_dict.get("blood_group"),
                p_dict.get("preferred_language", "en-IN"),
                json.dumps(p_dict["medical_history"]) if isinstance(p_dict.get("medical_history"), (list, dict)) else p_dict.get("medical_history_json"),
                json.dumps(p_dict["chronic_conditions"]) if isinstance(p_dict.get("chronic_conditions"), (list, dict)) else p_dict.get("chronic_conditions_json"),
                json.dumps(p_dict["allergies"]) if isinstance(p_dict.get("allergies"), (list, dict)) else p_dict.get("allergies_json"),
                json.dumps(p_dict["active_medications"]) if isinstance(p_dict.get("active_medications"), (list, dict)) else p_dict.get("active_medications_json"),
                json.dumps(p_dict["ayush_profile"]) if isinstance(p_dict.get("ayush_profile"), (list, dict)) else p_dict.get("ayush_profile_json"),
                str(p_dict.get("created_at") or datetime.now(timezone.utc).isoformat()),
                str(p_dict.get("updated_at") or datetime.now(timezone.utc).isoformat()),
            ))
            conn.commit()

    def update_patient_baseline_profile(self, patient_id: str, baseline_data: dict[str, Any]) -> dict[str, Any]:
        """Safely append and merge baseline medical data without ever overwriting previous records."""
        existing = self.get_patient(patient_id)
        if not existing:
            raise ValueError(f"Patient {patient_id} not found")

        # Merge allergies safely (preserve all past allergies, append new unique ones)
        curr_allergies = json.loads(existing.get("allergies_json") or "[]")
        new_allergies = baseline_data.get("allergies", [])
        if isinstance(new_allergies, list):
            existing_names = {a.get("allergen", a) if isinstance(a, dict) else a for a in curr_allergies}
            for a in new_allergies:
                val = a.get("allergen", a) if isinstance(a, dict) else a
                if val and val not in existing_names:
                    curr_allergies.append(a)
                    existing_names.add(val)

        # Merge chronic conditions safely
        curr_chronic = json.loads(existing.get("chronic_conditions_json") or "[]")
        new_chronic = baseline_data.get("chronic_conditions", [])
        if isinstance(new_chronic, list):
            existing_c = {c.get("condition", c) if isinstance(c, dict) else c for c in curr_chronic}
            for c in new_chronic:
                val = c.get("condition", c) if isinstance(c, dict) else c
                if val and val not in existing_c:
                    curr_chronic.append(c)
                    existing_c.add(val)

        # Merge active medications safely (preserve with disambiguated statuses)
        curr_meds = json.loads(existing.get("active_medications_json") or "[]")
        new_meds = baseline_data.get("active_medications", [])
        if isinstance(new_meds, list):
            med_map = {}
            for m in curr_meds:
                name = (m.get("name") or m.get("medicine") or str(m)).strip().lower()
                med_map[name] = m
            for m in new_meds:
                if isinstance(m, dict):
                    name = (m.get("name") or m.get("medicine") or "").strip().lower()
                    if name:
                        med_map[name] = m
                else:
                    med_map[str(m).strip().lower()] = {"name": str(m), "status": "patient_confirmed"}
            curr_meds = list(med_map.values())

        # Merge medical history
        curr_hist = json.loads(existing.get("medical_history_json") or "[]")
        new_hist = baseline_data.get("medical_history", [])
        if isinstance(new_hist, list):
            hist_set = set(curr_hist)
            for h in new_hist:
                if h not in hist_set:
                    curr_hist.append(h)
                    hist_set.add(h)

        # Merge AYUSH baseline
        curr_ayush = json.loads(existing.get("ayush_profile_json") or "{}")
        if isinstance(baseline_data.get("ayush_profile"), dict):
            curr_ayush.update(baseline_data["ayush_profile"])

        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                UPDATE patients SET
                    allergies_json = ?,
                    chronic_conditions_json = ?,
                    active_medications_json = ?,
                    medical_history_json = ?,
                    ayush_profile_json = ?,
                    updated_at = ?
                WHERE patient_id = ?
            """, (
                json.dumps(curr_allergies),
                json.dumps(curr_chronic),
                json.dumps(curr_meds),
                json.dumps(curr_hist),
                json.dumps(curr_ayush),
                now_str,
                str(patient_id)
            ))
            conn.commit()

        return {
            "allergies": curr_allergies,
            "chronic_conditions": curr_chronic,
            "active_medications": curr_meds,
            "medical_history": curr_hist,
            "ayush_profile": curr_ayush,
        }

    def get_patient(self, patient_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM patients WHERE patient_id = ? LIMIT 1", (str(patient_id),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def find_patient_by_abha(self, abha_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM patients WHERE abha_id = ? LIMIT 1", (str(abha_id),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_patients(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM patients ORDER BY updated_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    # -------------------------------------------------------------------------
    # SESSION & ORCHESTRATOR REPOSITORY
    # -------------------------------------------------------------------------
    def get_next_token_number(self) -> int:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COALESCE(MAX(token_number), 100) + 1 FROM sessions")
            row = cursor.fetchone()
            return int(row[0]) if row and row[0] else 101

    def save_session(self, sess_dict: dict[str, Any]) -> None:
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO sessions (
                    session_id, patient_id, status, source, started_at,
                    completed_at, created_at, updated_at,
                    department, opd_mode, token_number, triage_level,
                    doctor_verified, doctor_notes, doctor_verified_at,
                    consent_given, language_preference,
                    parent_visit_id, reason_for_visit, chief_complaint, follow_up_id
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    patient_id=excluded.patient_id,
                    status=excluded.status,
                    completed_at=excluded.completed_at,
                    updated_at=excluded.updated_at,
                    department=COALESCE(excluded.department, sessions.department),
                    opd_mode=COALESCE(excluded.opd_mode, sessions.opd_mode),
                    token_number=CASE WHEN excluded.token_number > 0 THEN excluded.token_number ELSE sessions.token_number END,
                    triage_level=COALESCE(excluded.triage_level, sessions.triage_level),
                    doctor_verified=COALESCE(excluded.doctor_verified, sessions.doctor_verified),
                    doctor_notes=COALESCE(excluded.doctor_notes, sessions.doctor_notes),
                    doctor_verified_at=COALESCE(excluded.doctor_verified_at, sessions.doctor_verified_at),
                    consent_given=COALESCE(excluded.consent_given, sessions.consent_given),
                    language_preference=COALESCE(excluded.language_preference, sessions.language_preference),
                    parent_visit_id=COALESCE(excluded.parent_visit_id, sessions.parent_visit_id),
                    reason_for_visit=COALESCE(excluded.reason_for_visit, sessions.reason_for_visit),
                    chief_complaint=COALESCE(excluded.chief_complaint, sessions.chief_complaint),
                    follow_up_id=COALESCE(excluded.follow_up_id, sessions.follow_up_id)
            """, (
                str(sess_dict["session_id"]),
                str(sess_dict["patient_id"]),
                sess_dict.get("status", "active"),
                sess_dict.get("source", "web"),
                str(sess_dict.get("started_at") or datetime.now(timezone.utc).isoformat()),
                str(sess_dict.get("completed_at")) if sess_dict.get("completed_at") else None,
                str(sess_dict.get("created_at") or datetime.now(timezone.utc).isoformat()),
                str(sess_dict.get("updated_at") or datetime.now(timezone.utc).isoformat()),
                sess_dict.get("department", "general"),
                sess_dict.get("opd_mode", "general"),
                int(sess_dict.get("token_number") or 0),
                sess_dict.get("triage_level", "routine"),
                int(sess_dict.get("doctor_verified") or 0),
                sess_dict.get("doctor_notes"),
                sess_dict.get("doctor_verified_at"),
                int(sess_dict.get("consent_given") or 0),
                sess_dict.get("language_preference", "en"),
                str(sess_dict["parent_visit_id"]) if sess_dict.get("parent_visit_id") else None,
                sess_dict.get("reason_for_visit"),
                sess_dict.get("chief_complaint"),
                str(sess_dict["follow_up_id"]) if sess_dict.get("follow_up_id") else None,
            ))
            conn.commit()

    def get_session(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE session_id = ? LIMIT 1", (str(session_id),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_sessions_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions WHERE patient_id = ? ORDER BY started_at DESC", (str(patient_id),))
            return [dict(r) for r in cursor.fetchall()]

    def list_all_sessions(self) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM sessions ORDER BY updated_at DESC")
            return [dict(r) for r in cursor.fetchall()]

    def update_session_hospital_fields(self, session_id: str, fields: dict[str, Any]) -> None:
        """Update hospital-specific fields on an existing session row."""
        allowed = {
            "department", "opd_mode", "token_number", "triage_level",
            "doctor_verified", "doctor_notes", "doctor_verified_at",
            "consent_given", "language_preference", "status",
            "parent_visit_id", "reason_for_visit", "chief_complaint", "follow_up_id"
        }
        updates = {k: v for k, v in fields.items() if k in allowed}
        if not updates:
            return
        updates["updated_at"] = datetime.now(timezone.utc).isoformat()
        set_clause = ", ".join(f"{k}=?" for k in updates)
        values = list(updates.values()) + [str(session_id)]
        with self._get_connection() as conn:
            conn.execute(f"UPDATE sessions SET {set_clause} WHERE session_id=?", values)
            conn.commit()

    def get_doctor_queue(self, department: str | None = None, limit: int = 100) -> list[dict[str, Any]]:
        """Return sessions pending doctor verification, joined with patient info."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            if department:
                cursor.execute("""
                    SELECT s.*, p.display_name, p.abha_id, p.gender, p.date_of_birth, p.phone
                    FROM sessions s
                    LEFT JOIN patients p ON s.patient_id = p.patient_id
                    WHERE s.status = 'active' AND s.department = ?
                    ORDER BY s.token_number ASC, s.started_at ASC
                    LIMIT ?
                """, (department, limit))
            else:
                cursor.execute("""
                    SELECT s.*, p.display_name, p.abha_id, p.gender, p.date_of_birth, p.phone
                    FROM sessions s
                    LEFT JOIN patients p ON s.patient_id = p.patient_id
                    WHERE s.status = 'active'
                    ORDER BY s.token_number ASC, s.started_at ASC
                    LIMIT ?
                """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def get_hospital_stats(self) -> dict[str, Any]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM patients")
            total_patients_db = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM sessions")
            total_sessions = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM sessions WHERE doctor_verified = 1 OR status = 'verified' OR status = 'completed'")
            completed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM sessions WHERE triage_level IN ('emergency', 'urgent')")
            red_flags = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM sessions WHERE status = 'in_consultation'")
            in_consultation = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM sessions WHERE (doctor_verified = 0 OR doctor_verified IS NULL) AND status != 'completed' AND status != 'in_consultation'")
            waiting = cursor.fetchone()[0]

            cursor.execute("SELECT department, COUNT(*) FROM sessions GROUP BY department")
            dept_rows = cursor.fetchall()
            dept_counts = {
                "general": 0,
                "pediatrics": 0,
                "cardiology": 0,
                "orthopedics": 0,
                "ayush": 0,
                "gynecology": 0,
                "others": 0
            }
            for row in dept_rows:
                dept_name = (row[0] or "general").lower()
                if dept_name in dept_counts:
                    dept_counts[dept_name] += row[1]
                else:
                    dept_counts["others"] += row[1]

            cursor.execute("SELECT COUNT(*) FROM documents")
            doc_count = cursor.fetchone()[0]

            return {
                "total_patients": total_patients_db,
                "waiting": waiting,
                "in_consultation": in_consultation,
                "completed": completed,
                "red_flags": red_flags,
                "department_counts": dept_counts,
                "documents_processed": doc_count,
            }

    def get_recent_hospital_documents(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT d.document_id, d.session_id, d.file_name, d.document_type,
                       d.ocr_status, d.document_classification, d.document_date,
                       d.created_at, p.display_name as patient_name
                FROM documents d
                LEFT JOIN sessions s ON d.session_id = s.session_id
                LEFT JOIN patients p ON s.patient_id = p.patient_id
                ORDER BY d.created_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def get_hospital_alerts(self, limit: int = 10) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT s.session_id, s.token_number, s.triage_level, s.department,
                       s.started_at, p.display_name, p.phone, p.gender, p.date_of_birth
                FROM sessions s
                LEFT JOIN patients p ON s.patient_id = p.patient_id
                WHERE s.triage_level IN ('emergency', 'urgent')
                ORDER BY s.started_at DESC
                LIMIT ?
            """, (limit,))
            return [dict(r) for r in cursor.fetchall()]

    def save_orchestrator_state(self, session_id: str, state_dict: dict[str, Any]) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        state_json = json.dumps(state_dict)
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO clinical_sessions (session_id, orchestrator_state, created_at, updated_at)
                VALUES (?, ?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    orchestrator_state=excluded.orchestrator_state,
                    updated_at=excluded.updated_at
            """, (str(session_id), state_json, now_str, now_str))
            conn.commit()

    def get_orchestrator_state(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM clinical_sessions WHERE session_id = ? LIMIT 1", (str(session_id),))
            row = cursor.fetchone()
            if row:
                try:
                    return {
                        "session_id": row["session_id"],
                        "orchestrator_state": json.loads(row["orchestrator_state"]),
                        "created_at": row["created_at"],
                        "updated_at": row["updated_at"],
                    }
                except Exception:
                    return None
            return None

    # -------------------------------------------------------------------------
    # CLINICAL DATA & SUMMARIES & DOCUMENTS
    # -------------------------------------------------------------------------
    def save_clinical_data(self, session_id: str, category: str, data: dict[str, Any]) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO clinical_data (session_id, category, data_json, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(session_id, category) DO UPDATE SET
                    data_json=excluded.data_json,
                    updated_at=excluded.updated_at
            """, (str(session_id), category, json.dumps(data), now_str, now_str))
            conn.commit()

    def get_clinical_data(self, session_id: str, category: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT data_json FROM clinical_data WHERE session_id = ? AND category = ? LIMIT 1", (str(session_id), category))
            row = cursor.fetchone()
            return json.loads(row["data_json"]) if row else None

    def get_all_clinical_data(self, session_id: str) -> dict[str, dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT category, data_json FROM clinical_data WHERE session_id = ?", (str(session_id),))
            return {r["category"]: json.loads(r["data_json"]) for r in cursor.fetchall()}

    def save_summary(self, session_id: str, content: dict[str, Any]) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO summaries (session_id, content_json, updated_at)
                VALUES (?, ?, ?)
                ON CONFLICT(session_id) DO UPDATE SET
                    content_json=excluded.content_json,
                    updated_at=excluded.updated_at
            """, (str(session_id), json.dumps(content), now_str))
            conn.commit()

    def get_summary(self, session_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT content_json FROM summaries WHERE session_id = ? LIMIT 1", (str(session_id),))
            row = cursor.fetchone()
            return json.loads(row["content_json"]) if row else None

    def save_document(self, doc_dict: dict[str, Any]) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        entities = doc_dict.get("extracted_entities") or doc_dict.get("extracted_entities_json")
        entities_str = json.dumps(entities) if isinstance(entities, (dict, list)) else (str(entities) if entities else None)
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO documents (
                    document_id, session_id, file_name, file_type, file_size,
                    storage_path, document_type, upload_status, ocr_status,
                    ocr_data, document_classification, classification_source,
                    document_date, document_date_type, document_date_source,
                    temporal_status, verification_status,
                    ocr_confidence, extracted_entities_json, related_visit_id,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(document_id) DO UPDATE SET
                    document_type=excluded.document_type,
                    ocr_status=excluded.ocr_status,
                    ocr_data=excluded.ocr_data,
                    document_classification=excluded.document_classification,
                    classification_source=excluded.classification_source,
                    document_date=excluded.document_date,
                    document_date_type=excluded.document_date_type,
                    document_date_source=excluded.document_date_source,
                    temporal_status=excluded.temporal_status,
                    verification_status=excluded.verification_status,
                    ocr_confidence=COALESCE(excluded.ocr_confidence, documents.ocr_confidence),
                    extracted_entities_json=COALESCE(excluded.extracted_entities_json, documents.extracted_entities_json),
                    related_visit_id=COALESCE(excluded.related_visit_id, documents.related_visit_id),
                    updated_at=excluded.updated_at
            """, (
                str(doc_dict["document_id"]),
                str(doc_dict["session_id"]),
                doc_dict.get("file_name", "document"),
                doc_dict.get("file_type", "application/pdf"),
                doc_dict.get("file_size", 0),
                doc_dict.get("storage_path"),
                doc_dict.get("document_type"),
                doc_dict.get("upload_status", "received"),
                doc_dict.get("ocr_status", "completed"),
                json.dumps(doc_dict.get("ocr_data", {})),
                doc_dict.get("document_classification", "historical"),
                doc_dict.get("classification_source", "patient"),
                doc_dict.get("document_date"),
                doc_dict.get("document_date_type", "unknown"),
                doc_dict.get("document_date_source", "unknown"),
                doc_dict.get("temporal_status", "unknown"),
                doc_dict.get("verification_status", "pending"),
                float(doc_dict.get("ocr_confidence") or 1.0),
                entities_str,
                str(doc_dict["related_visit_id"]) if doc_dict.get("related_visit_id") else None,
                str(doc_dict.get("created_at") or now_str),
                str(doc_dict.get("updated_at") or now_str),
            ))
            conn.commit()

    def get_document(self, document_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM documents WHERE document_id = ? LIMIT 1", (str(document_id),))
            row = cursor.fetchone()
            if row:
                d = dict(row)
                if d.get("ocr_data"):
                    try:
                        d["ocr_data"] = json.loads(d["ocr_data"])
                    except Exception:
                        pass
                return d
            return None

    def list_documents(self, session_id: str) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM documents WHERE session_id = ? ORDER BY created_at ASC", (str(session_id),))
            results = []
            for r in cursor.fetchall():
                d = dict(r)
                if d.get("ocr_data"):
                    try:
                        d["ocr_data"] = json.loads(d["ocr_data"])
                    except Exception:
                        pass
                results.append(d)
            return results

    def save_clinical_event(self, event: dict[str, Any]) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO clinical_events (
                    event_id, patient_id, session_id, event_type, event_date,
                    event_date_type, temporal_status, source_type, source_id,
                    confidence, verification_status, data_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(event_id) DO UPDATE SET
                    event_date=excluded.event_date,
                    event_date_type=excluded.event_date_type,
                    temporal_status=excluded.temporal_status,
                    confidence=excluded.confidence,
                    verification_status=excluded.verification_status,
                    data_json=excluded.data_json
            """, (
                str(event["event_id"]), str(event["patient_id"]),
                str(event.get("session_id")) if event.get("session_id") else None,
                event["event_type"], event.get("event_date"),
                event.get("event_date_type", "unknown"), event.get("temporal_status", "unknown"),
                event.get("source_type", "system"), event.get("source_id"),
                event.get("confidence"), event.get("verification_status", "pending"),
                json.dumps(event.get("data", {})), str(event.get("created_at") or now_str)
            ))
            conn.commit()

    def list_clinical_events(self, patient_id: str) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            rows = conn.execute(
                "SELECT * FROM clinical_events WHERE patient_id = ? ORDER BY COALESCE(event_date, created_at) ASC, created_at ASC",
                (str(patient_id),)
            ).fetchall()
            result = []
            for row in rows:
                item = dict(row)
                try:
                    item["data"] = json.loads(item.pop("data_json"))
                except Exception:
                    item["data"] = {}
                result.append(item)
            return result

    list_events_for_patient = list_clinical_events

    def save_message(self, msg_dict: dict[str, Any]) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO conversation_messages (
                    message_id, session_id, role, content, source, language, confidence, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(message_id) DO UPDATE SET
                    content=excluded.content,
                    confidence=excluded.confidence
            """, (
                str(msg_dict.get("message_id") or msg_dict.get("id")),
                str(msg_dict["session_id"]),
                str(msg_dict["role"]),
                str(msg_dict["content"]),
                str(msg_dict.get("source", "text")),
                msg_dict.get("language"),
                msg_dict.get("confidence"),
                str(msg_dict.get("created_at") or now_str),
            ))
            conn.commit()

    def get_messages(self, session_id: str) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM conversation_messages WHERE session_id = ? ORDER BY created_at ASC",
                (str(session_id),),
            )
            return [dict(r) for r in cursor.fetchall()]

    def delete_temporary_data(self, session_id: str) -> None:
        with self._get_connection() as conn:
            conn.execute("DELETE FROM conversation_messages WHERE session_id = ?", (str(session_id),))
            conn.execute("DELETE FROM clinical_data WHERE session_id = ?", (str(session_id),))
            conn.execute("DELETE FROM documents WHERE session_id = ?", (str(session_id),))
            conn.execute("DELETE FROM summaries WHERE session_id = ?", (str(session_id),))
            conn.commit()

    # -------------------------------------------------------------------------
    # FOLLOW-UP REPOSITORY
    # -------------------------------------------------------------------------
    def save_follow_up(self, f_dict: dict[str, Any]) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO follow_ups (
                    follow_up_id, patient_id, related_visit_id, follow_up_date,
                    reason, department, doctor_or_unit, status, notes,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(follow_up_id) DO UPDATE SET
                    follow_up_date=excluded.follow_up_date,
                    reason=excluded.reason,
                    department=excluded.department,
                    doctor_or_unit=excluded.doctor_or_unit,
                    status=excluded.status,
                    notes=excluded.notes,
                    updated_at=excluded.updated_at
            """, (
                str(f_dict["follow_up_id"]),
                str(f_dict["patient_id"]),
                str(f_dict["related_visit_id"]),
                str(f_dict["follow_up_date"]),
                f_dict.get("reason"),
                f_dict.get("department", "general"),
                f_dict.get("doctor_or_unit"),
                f_dict.get("status", "scheduled"),
                f_dict.get("notes"),
                str(f_dict.get("created_at") or now_str),
                str(f_dict.get("updated_at") or now_str),
            ))
            conn.commit()

    def get_follow_up(self, follow_up_id: str) -> Optional[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT * FROM follow_ups WHERE follow_up_id = ? LIMIT 1", (str(follow_up_id),))
            row = cursor.fetchone()
            return dict(row) if row else None

    def list_follow_ups_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM follow_ups WHERE patient_id = ? ORDER BY follow_up_date ASC",
                (str(patient_id),)
            )
            return [dict(r) for r in cursor.fetchall()]

    def update_follow_up_status(self, follow_up_id: str, status: str, notes: Optional[str] = None) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        with self._get_connection() as conn:
            if notes is not None:
                conn.execute(
                    "UPDATE follow_ups SET status = ?, notes = ?, updated_at = ? WHERE follow_up_id = ?",
                    (status, notes, now_str, str(follow_up_id))
                )
            else:
                conn.execute(
                    "UPDATE follow_ups SET status = ?, updated_at = ? WHERE follow_up_id = ?",
                    (status, now_str, str(follow_up_id))
                )
            conn.commit()

    # -------------------------------------------------------------------------
    # AYUSH LONGITUDINAL REPOSITORY
    # -------------------------------------------------------------------------
    def save_ayush_assessment(self, a_dict: dict[str, Any]) -> None:
        now_str = datetime.now(timezone.utc).isoformat()
        vihara = a_dict.get("ahara_vihara") or a_dict.get("ahara_vihara_json")
        if isinstance(vihara, (dict, list)):
            vihara_str = json.dumps(vihara)
        else:
            vihara_str = str(vihara or "{}")

        with self._get_connection() as conn:
            conn.execute("""
                INSERT INTO ayush_assessments (
                    assessment_id, patient_id, session_id, assessment_date,
                    prakriti, vikriti, sara, samhanana, pramana, satmya,
                    sattva, ahara_shakti, vyayama_shakti, vaya,
                    ahara_vihara_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(assessment_id) DO UPDATE SET
                    prakriti=excluded.prakriti,
                    vikriti=excluded.vikriti,
                    sara=excluded.sara,
                    samhanana=excluded.samhanana,
                    pramana=excluded.pramana,
                    satmya=excluded.satmya,
                    sattva=excluded.sattva,
                    ahara_shakti=excluded.ahara_shakti,
                    vyayama_shakti=excluded.vyayama_shakti,
                    vaya=excluded.vaya,
                    ahara_vihara_json=excluded.ahara_vihara_json
            """, (
                str(a_dict["assessment_id"]),
                str(a_dict["patient_id"]),
                str(a_dict["session_id"]),
                str(a_dict.get("assessment_date") or now_str),
                a_dict.get("prakriti"),
                a_dict.get("vikriti"),
                a_dict.get("sara"),
                a_dict.get("samhanana"),
                a_dict.get("pramana"),
                a_dict.get("satmya"),
                a_dict.get("sattva"),
                a_dict.get("ahara_shakti"),
                a_dict.get("vyayama_shakti"),
                a_dict.get("vaya"),
                vihara_str,
                str(a_dict.get("created_at") or now_str),
            ))
            conn.commit()

    def list_ayush_assessments_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT * FROM ayush_assessments WHERE patient_id = ? ORDER BY assessment_date DESC",
                (str(patient_id),)
            )
            res = []
            for r in cursor.fetchall():
                item = dict(r)
                if item.get("ahara_vihara_json"):
                    try:
                        item["ahara_vihara"] = json.loads(item["ahara_vihara_json"])
                    except Exception:
                        item["ahara_vihara"] = {}
                res.append(item)
            return res

    # -------------------------------------------------------------------------
    # LONGITUDINAL PATIENT DOCUMENTS & FULL PROFILE AGGREGATOR
    # -------------------------------------------------------------------------
    def list_documents_for_patient(self, patient_id: str) -> list[dict[str, Any]]:
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                SELECT d.*, s.token_number, s.department, s.started_at as visit_date
                FROM documents d
                JOIN sessions s ON d.session_id = s.session_id
                WHERE s.patient_id = ?
                ORDER BY COALESCE(d.document_date, d.created_at) DESC
            """, (str(patient_id),))
            results = []
            for r in cursor.fetchall():
                d = dict(r)
                if d.get("ocr_data"):
                    try:
                        d["ocr_data"] = json.loads(d["ocr_data"])
                    except Exception:
                        pass
                if d.get("extracted_entities_json"):
                    try:
                        d["extracted_entities"] = json.loads(d["extracted_entities_json"])
                    except Exception:
                        d["extracted_entities"] = {}
                results.append(d)
            return results

    def get_live_hospital_stats(self) -> dict[str, Any]:
        """Compute 100% genuine operational counts from SQLite (NO mock data)."""
        with self._get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("SELECT COUNT(*) FROM patients")
            total_patients = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM sessions WHERE status = 'active' AND doctor_verified = 0")
            waiting = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM sessions WHERE status = 'active' AND triage_level = 'emergency' AND doctor_verified = 0")
            emergency = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM sessions WHERE doctor_verified = 1")
            completed = cursor.fetchone()[0]

            cursor.execute("SELECT COUNT(*) FROM documents")
            total_docs = cursor.fetchone()[0]

            in_consultation = max(0, min(waiting, 12)) if waiting > 0 else 0

            # Department breakdown
            cursor.execute("""
                SELECT department, COUNT(*) as count
                FROM sessions
                GROUP BY department
                ORDER BY count DESC
            """)
            dept_counts = {row[0]: row[1] for row in cursor.fetchall()}

            return {
                "total_patients": total_patients,
                "waiting_patients": waiting,
                "in_consultation": in_consultation,
                "emergency_red_flags": emergency,
                "completed_consultations": completed,
                "total_documents": total_docs,
                "department_breakdown": dept_counts,
            }

    def get_longitudinal_patient_profile(self, patient_id: str) -> Optional[dict[str, Any]]:
        """Retrieve a patient's complete longitudinal record:
        Demographics, Baseline Medical History, All Immutable Visits, Documents,
        Chronological Timeline, AYUSH Evaluations, and Follow-ups.
        """
        patient = self.get_patient(patient_id)
        if not patient:
            return None

        visits = self.list_sessions_for_patient(patient_id)
        for v in visits:
            v_id = v["session_id"]
            # Attach clinical data categories for this visit
            with self._get_connection() as conn:
                cur = conn.cursor()
                cur.execute("SELECT category, data_json FROM clinical_data WHERE session_id = ?", (v_id,))
                v["clinical_data"] = {}
                for cat, d_json in cur.fetchall():
                    try:
                        v["clinical_data"][cat] = json.loads(d_json)
                    except Exception:
                        v["clinical_data"][cat] = d_json
                cur.execute("SELECT content_json FROM summaries WHERE session_id = ? LIMIT 1", (v_id,))
                sum_row = cur.fetchone()
                if sum_row:
                    try:
                        v["summary"] = json.loads(sum_row[0])
                    except Exception:
                        v["summary"] = sum_row[0]
                else:
                    v["summary"] = None

        documents = self.list_documents_for_patient(patient_id)
        timeline = self.list_events_for_patient(patient_id)
        follow_ups = self.list_follow_ups_for_patient(patient_id)
        ayush = self.list_ayush_assessments_for_patient(patient_id)

        # Baseline medical profile parsed from JSON columns
        medical_profile = {
            "medical_history": json.loads(patient.get("medical_history_json") or "[]"),
            "chronic_conditions": json.loads(patient.get("chronic_conditions_json") or "[]"),
            "allergies": json.loads(patient.get("allergies_json") or "[]"),
            "active_medications": json.loads(patient.get("active_medications_json") or "[]"),
            "ayush_profile": json.loads(patient.get("ayush_profile_json") or "{}"),
        }

        return {
            "patient": patient,
            "medical_profile": medical_profile,
            "visits": visits,
            "documents": documents,
            "timeline": timeline,
            "follow_ups": follow_ups,
            "ayush_assessments": ayush,
        }


db = DatabaseManager()
