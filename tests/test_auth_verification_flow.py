import pytest
from fastapi.testclient import TestClient

from api.main import app

client = TestClient(app)


@pytest.fixture(autouse=True)
def _no_live_smtp_in_tests(monkeypatch):
    """Keep the offline suite deterministic: never dispatch real SMTP during pytest."""
    monkeypatch.setenv("SMTP_HOST", "")
    monkeypatch.setenv("SMTP_USER", "")
    monkeypatch.setenv("SMTP_PASS", "")


def _random_email(prefix: str = "verify") -> str:
    import uuid

    return f"{prefix}-{uuid.uuid4().hex[:10]}@example.com"


def _register_user(email: str, password: str = "TestPass@123") -> dict:
    resp = client.post("/api/v1/auth/register", json={
        "display_name": "Verify Test",
        "email": email,
        "password": password,
    })
    assert resp.status_code in (200, 201), resp.text
    return resp.json()


def test_change_password_requires_valid_verification_code():
    email = _random_email("pw")
    user = _register_user(email)

    code_resp = client.post("/api/v1/auth/send-verification-code", json={"email": email})
    assert code_resp.status_code == 200, code_resp.text
    payload = code_resp.json()
    assert payload["channel"] == "direct" or payload["status"] == "sent"
    code = payload.get("code")
    assert code and len(code) == 6

    bad = client.post("/api/v1/auth/change-password", json={
        "current_password": "TestPass@123",
        "new_password": "NewPass@456",
        "verification_code": "000000",
    }, params={"email": email})
    assert bad.status_code == 400, bad.text

    ok = client.post("/api/v1/auth/change-password", json={
        "current_password": "TestPass@123",
        "new_password": "NewPass@456",
        "verification_code": code,
    }, params={"email": email})
    assert ok.status_code == 200, ok.text

    login_old = client.post("/api/v1/auth/login", json={"email": email, "password": "TestPass@123"})
    assert login_old.status_code == 401
    login_new = client.post("/api/v1/auth/login", json={"email": email, "password": "NewPass@456"})
    assert login_new.status_code == 200
    assert login_new.json()["user"]["email"] == email


def test_change_email_requires_code_sent_to_new_address():
    email = _random_email("em")
    user = _register_user(email, "TestPass@123")

    new_email = _random_email("new")

    code_resp = client.post("/api/v1/auth/send-verification-code", json={"email": new_email})
    assert code_resp.status_code == 200, code_resp.text
    code = code_resp.json().get("code")
    assert code and len(code) == 6

    bad_pass = client.post("/api/v1/auth/change-email", json={
        "current_password": "wrong-password",
        "new_email": new_email,
        "verification_code": code,
    }, params={"email": email})
    assert bad_pass.status_code == 400, bad_pass.text

    bad_code = client.post("/api/v1/auth/change-email", json={
        "current_password": "TestPass@123",
        "new_email": new_email,
        "verification_code": "111111",
    }, params={"email": email})
    assert bad_code.status_code == 400, bad_code.text

    ok = client.post("/api/v1/auth/change-email", json={
        "current_password": "TestPass@123",
        "new_email": new_email,
        "verification_code": code,
    }, params={"email": email})
    assert ok.status_code == 200, ok.text
    assert ok.json()["email"] == new_email

    me = client.get("/api/v1/auth/me", params={"email": new_email})
    assert me.status_code == 200
    assert me.json()["user_id"] == user["user"]["user_id"]


def test_change_email_rejects_in_use_address():
    email = _random_email("dup1")
    _register_user(email, "TestPass@123")
    other_email = _random_email("dup2")
    _register_user(other_email, "TestPass@123")

    code_resp = client.post("/api/v1/auth/send-verification-code", json={"email": other_email})
    code = code_resp.json().get("code")

    conflict = client.post("/api/v1/auth/change-email", json={
        "current_password": "TestPass@123",
        "new_email": other_email,
        "verification_code": code,
    }, params={"email": email})
    assert conflict.status_code == 400, conflict.text
    assert "already in use" in conflict.json().get("error", "")


def test_send_verification_code_never_exposes_real_smtp_path_when_unconfigured():
    email = _random_email("smtp")
    _register_user(email)
    resp = client.post("/api/v1/auth/send-verification-code", json={"email": email})
    assert resp.status_code == 200, resp.text
    body = resp.json()
    assert body.get("status") == "sent"
    # Without SMTP creds the code is returned for dev/demo flows only.
    if body.get("channel") == "direct":
        assert len(body.get("code", "")) == 6


def test_change_password_accepts_user_id_from_body_like_the_ui_sends():
    email = _random_email("bodyid")
    user = _register_user(email)

    code_resp = client.post("/api/v1/auth/send-verification-code", json={"email": email})
    assert code_resp.status_code == 200, code_resp.text
    code = code_resp.json().get("code")

    # The browser sends user_id in the request body (no query params).
    ok = client.post("/api/v1/auth/change-password", json={
        "current_password": "TestPass@123",
        "new_password": "BodyId@456",
        "verification_code": code,
        "user_id": user["user"]["user_id"],
    })
    assert ok.status_code == 200, ok.text

    login_new = client.post("/api/v1/auth/login", json={"email": email, "password": "BodyId@456"})
    assert login_new.status_code == 200


def test_resending_code_dispatches_to_local_mailbox_and_keeps_old_code_invalid():
    email = _random_email("resend")
    user = _register_user(email)

    first = client.post("/api/v1/auth/send-verification-code", json={"email": email}).json()
    second = client.post("/api/v1/auth/send-verification-code", json={"email": email}).json()

    mailbox = second.get("mailbox") or ""
    assert "logs" in mailbox or mailbox.endswith(".eml")

    ok_with_latest = client.post("/api/v1/auth/change-password", json={
        "current_password": "TestPass@123",
        "new_password": "Resend@456",
        "verification_code": second["code"],
        "user_id": user["user"]["user_id"],
    })
    assert ok_with_latest.status_code == 200, ok_with_latest.text

    stale = client.post("/api/v1/auth/change-password", json={
        "current_password": "Resend@456",
        "new_password": "Stale@000",
        "verification_code": first["code"],
        "user_id": user["user"]["user_id"],
    })
    assert stale.status_code == 400, stale.text