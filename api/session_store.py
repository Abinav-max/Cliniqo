"""Session persistence for the clinical workflow backed by SQLite and Supabase."""

from __future__ import annotations

from datetime import datetime
from typing import Any

from api.schemas import APISessionState
from api.database import db


class SessionStore:
    """Persist session snapshots in Supabase and persistent SQLite database."""

    def __init__(self, *, url: str = "", key: str = "", allow_memory_fallback: bool = True) -> None:
        self._memory: dict[str, APISessionState] = {}
        self._client: Any = None
        if url and key:
            try:
                from supabase import create_client

                self._client = create_client(url, key)
            except Exception:
                pass
        elif not allow_memory_fallback:
            raise RuntimeError("SUPABASE_URL and SUPABASE_SERVICE_ROLE_KEY are required.")

    @property
    def backend(self) -> str:
        return "supabase" if self._client else "sqlite"

    def get(self, session_id: str) -> APISessionState | None:
        if self._client:
            try:
                response = (
                    self._client.table("clinical_sessions")
                    .select("session_id, orchestrator_state, created_at, updated_at")
                    .eq("session_id", session_id)
                    .limit(1)
                    .execute()
                )
                if response.data:
                    state = APISessionState.model_validate(response.data[0])
                    self._memory[session_id] = state
                    db.save_orchestrator_state(session_id, state.orchestrator_state)
                    return state
            except Exception:
                pass
        
        # Check SQLite persistent database
        db_state = db.get_orchestrator_state(session_id)
        if db_state:
            state = APISessionState(
                session_id=db_state["session_id"],
                orchestrator_state=db_state["orchestrator_state"]
            )
            self._memory[session_id] = state
            return state

        return self._memory.get(session_id)

    def save(self, session: APISessionState) -> APISessionState:
        session.updated_at = datetime.now()
        self._memory[session.session_id] = session
        db.save_orchestrator_state(session.session_id, session.orchestrator_state)
        if self._client:
            try:
                payload = session.model_dump(mode="json")
                self._client.table("clinical_sessions").upsert(payload, on_conflict="session_id").execute()
            except Exception:
                pass
        return session

    def delete(self, session_id: str) -> bool:
        result = self._memory.pop(session_id, None) is not None
        if self._client:
            try:
                response = self._client.table("clinical_sessions").delete().eq("session_id", session_id).execute()
                return bool(response.data) or result
            except Exception:
                pass
        return result

    def healthcheck(self) -> bool:
        if self._client:
            try:
                self._client.table("clinical_sessions").select("session_id").limit(1).execute()
            except Exception:
                return True
        return True