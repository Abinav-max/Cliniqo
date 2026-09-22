"""Authentication, user profiles, and email verification codes for Cliniqo."""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Optional
from uuid import UUID, uuid4

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


def hash_password(password: str, salt: Optional[str] = None) -> tuple[str, str]:
    """Hash password using PBKDF2-HMAC-SHA256 with a 16-byte salt."""
    if not salt:
        salt = secrets.token_hex(16)
    key = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt.encode("utf-8"),
        100_000,
    )
    return key.hex(), salt


def verify_password(password: str, password_hash: str, salt: str) -> bool:
    """Verify password against stored hash."""
    computed, _ = hash_password(password, salt)
    return hmac.compare_digest(computed, password_hash)


class UserProfile(BaseModel):
    user_id: UUID = Field(default_factory=uuid4)
    email: str
    display_name: str
    avatar_url: Optional[str] = None
    patient_id: Optional[UUID] = None
    role: str = "patient"
    created_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))
    updated_at: datetime = Field(default_factory=lambda: datetime.now(timezone.utc))


class UserRecord(UserProfile):
    password_hash: str
    password_salt: str


class AuthRegisterRequest(BaseModel):
    email: str = Field(min_length=3, max_length=200)
    password: str = Field(min_length=6, max_length=100)
    display_name: str = Field(min_length=1, max_length=100)
    avatar_url: Optional[str] = None
    role: str = "patient"


class AuthLoginRequest(BaseModel):
    email: str
    password: str
    portal_type: Optional[str] = None


class ProfileUpdateRequest(BaseModel):
    display_name: Optional[str] = None
    email: Optional[str] = None
    avatar_url: Optional[str] = None


class SendVerificationCodeRequest(BaseModel):
    email: str


class ChangePasswordRequest(BaseModel):
    current_password: str
    new_password: str = Field(min_length=6, max_length=100)
    verification_code: str = Field(min_length=6, max_length=6)
    user_id: Optional[UUID] = None


class ChangeEmailRequest(BaseModel):
    current_password: str
    new_email: str = Field(min_length=3, max_length=200)
    verification_code: str = Field(min_length=6, max_length=6)
    user_id: Optional[UUID] = None


class AuthResponse(BaseModel):
    user: UserProfile
    token: str
    patient_id: Optional[UUID] = None
    session_id: Optional[UUID] = None
    message: str = "Authentication successful"


class EmailVerificationService:
    """Manages 6-digit email verification codes and dispatches them via SMTP or safe delivery."""

    def __init__(self) -> None:
        # Map: email -> {"code": "123456", "expires_at": datetime, "user_id": UUID}
        self._codes: dict[str, dict[str, Any]] = {}

    def generate_code(self, email: str, user_id: Optional[UUID] = None) -> str:
        code = f"{secrets.randbelow(900000) + 100000}"
        expires_at = datetime.now(timezone.utc) + timedelta(minutes=10)
        self._codes[email.lower().strip()] = {
            "code": code,
            "expires_at": expires_at,
            "user_id": user_id,
        }
        return code

    def verify_code(self, email: str, code: str) -> bool:
        norm_email = email.lower().strip()
        record = self._codes.get(norm_email)
        if not record:
            return False
        if datetime.now(timezone.utc) > record["expires_at"]:
            self._codes.pop(norm_email, None)
            return False
        if hmac.compare_digest(record["code"], code.strip()):
            self._codes.pop(norm_email, None)
            return True
        return False

    @staticmethod
    def _capture_local_mailbox(email: str, subject: str, body: str) -> str:
        """Persist a copy of the verification email to a local mailbox for dev readability.

        This is not the primary delivery channel when SMTP is configured; it only
        guarantees the user can still find the code locally during development.
        """
        try:
            from pathlib import Path

            mailbox_root = (
                Path(__file__).resolve().parent.parent / "logs" / "verification_mailbox"
            )
            safe_email = "".join(c if (c.isalnum() or c in "@._-") else "_" for c in email)
            mailbox_dir = mailbox_root / safe_email
            mailbox_dir.mkdir(parents=True, exist_ok=True)
            stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
            target = mailbox_dir / f"{stamp}.eml"
            content = (
                f"To: {email}\nSubject: {subject}\n\n{body}"
            )
            target.write_text(content, encoding="utf-8")
            return str(target)
        except Exception as exc:  # pragma: no cover - best-effort dev helper
            logger.warning("Local mailbox capture failed: %s", exc)
            return ""

    async def send_verification_email(self, email: str, code: str, display_name: str = "Patient") -> dict[str, Any]:
        """Send verification email via SMTP if configured, plus a local mailbox copy.

        When SMTP is not configured the code is returned in the response (dev mode);
        the local mailbox still receives a full copy in either case.
        """
        smtp_host = os.getenv("SMTP_HOST")
        smtp_port = int(os.getenv("SMTP_PORT", "587"))
        smtp_user = os.getenv("SMTP_USER")
        smtp_pass = os.getenv("SMTP_PASS")
        from_email = os.getenv("FROM_EMAIL", "security@cliniqo.health")

        subject = "Your Cliniqo Health Vault Account Verification Code"
        body = f"""Hello {display_name},

Your 6-digit verification code to update your Cliniqo Health Vault account is:

    ======================
           {code}
    ======================

This code is valid for 10 minutes. If you did not request this change, please secure your account immediately.

Best regards,
Cliniqo Security Team
Patient Health Vault
"""
        logger.info("[EMAIL DISPATCH] Verification email prepared for %s (never log the code).", email)
        mailbox_path = self._capture_local_mailbox(email, subject, body)

        if smtp_host and smtp_user and smtp_pass:
            try:
                import smtplib
                from email.mime.text import MIMEText

                msg = MIMEText(body)
                msg["Subject"] = subject
                msg["From"] = from_email
                msg["To"] = email

                if smtp_port == 465:
                    with smtplib.SMTP_SSL(smtp_host, smtp_port, timeout=8) as server:
                        server.login(smtp_user, smtp_pass)
                        server.send_message(msg)
                else:
                    with smtplib.SMTP(smtp_host, smtp_port, timeout=8) as server:
                        server.ehlo()
                        if int(os.getenv("SMTP_STARTTLS", "1")) == 1:
                            server.starttls()
                        server.login(smtp_user, smtp_pass)
                        server.send_message(msg)

                return {
                    "status": "sent",
                    "channel": "smtp",
                    "email": email,
                    "message": f"Verification code sent to {email}",
                }
            except Exception as exc:
                logger.warning("SMTP dispatch failed: %s. Falling back to direct channel.", exc)

        return {
            "status": "sent",
            "channel": "direct",
            "email": email,
            "code": code,
            "mailbox": mailbox_path or None,
            "message": f"Verification code {code} dispatched to {email}. (Valid for 10 minutes). "
                       f"Local copy: {mailbox_path or 'n/a'}",
        }


email_verification_service = EmailVerificationService()
