from api.schemas import APISessionState
from api.session_store import SessionStore
import pytest


def test_memory_session_store_round_trip():
    store = SessionStore()
    session = APISessionState(session_id="session-test", orchestrator_state={"workflow_status": "idle"})

    store.save(session)

    assert store.get("session-test").session_id == "session-test"
    assert store.delete("session-test") is True
    assert store.get("session-test") is None


def test_supabase_required_rejects_missing_configuration():
    with pytest.raises(RuntimeError, match="SUPABASE_URL"):
        SessionStore(allow_memory_fallback=False)