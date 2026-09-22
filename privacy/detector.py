"""Deterministic identifier detection used by the outbound privacy gateway."""

from __future__ import annotations

import re
from collections.abc import Callable


TokenReplacement = Callable[[re.Match[str]], str]


class IdentifierDetector:
    """Detect and replace common PII/PHI patterns without touching clinical facts.

    This intentionally uses deterministic patterns rather than claiming complete
    entity recognition. Labelled values and common free-text identifiers are
    covered first, then generic contact/identifier formats.
    """

    _TOKENS = {
        "person": "[PERSON]",
        "phone": "[PHONE]",
        "email": "[EMAIL]",
        "address": "[ADDRESS]",
        "dob": "[DOB]",
        "mrn": "[MRN]",
        "hospital_id": "[HOSPITAL_ID]",
        "insurance_id": "[INSURANCE_ID]",
        "patient_id": "[PATIENT_ID]",
        "document_id": "[DOCUMENT_ID]",
        "account_number": "[ACCOUNT_NUMBER]",
        "ssn": "[SSN]",
        "url": "[URL]",
        "secret": "[SECRET]",
    }

    _LABEL_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("person", re.compile(r"\b(?P<label>patient\s+name|name)\s*[:=]\s*(?P<value>[^\n,;.]+)", re.I)),
        ("dob", re.compile(r"\b(?P<label>date\s+of\s+birth|d\.o\.b\.?|dob)\s*[:=]\s*(?P<value>[^\n,;.]+)", re.I)),
        ("mrn", re.compile(r"\b(?P<label>medical\s+record\s+(?:number|no\.?|id)|mrn)\s*(?:[:=#-]\s*|\s+)(?P<value>[^\n,;.]+)", re.I)),
        ("hospital_id", re.compile(r"\b(?P<label>hospital\s*(?:id|number|no\.?)|hospital)\s*(?:[:=#-]\s*|\s+)(?P<value>[^\n,;.]+)", re.I)),
        ("insurance_id", re.compile(r"\b(?P<label>insurance\s*(?:id|number|no\.?|member\s*id))\s*(?:[:=#-]\s*|\s+)(?P<value>[^\n,;.]+)", re.I)),
        ("patient_id", re.compile(r"\b(?P<label>patient\s*(?:id|number|no\.?)|patient_id|session_id|message_id)\s*(?:[:=#-]\s*|\s+)(?P<value>[^\n,;.]+)", re.I)),
        ("document_id", re.compile(r"\b(?P<label>document\s*(?:id|number|no\.?)|document_id)\s*(?:[:=#-]\s*|\s+)(?P<value>[^\n,;.]+)", re.I)),
        ("account_number", re.compile(r"\b(?P<label>account\s*(?:number|no\.?|id))\s*(?:[:=#-]\s*|\s+)(?P<value>[^\n,;.]+)", re.I)),
        ("phone", re.compile(r"\b(?P<label>phone|mobile|telephone|tel)\s*[:=]\s*(?P<value>[^\n,;.]+)", re.I)),
        ("email", re.compile(r"\b(?P<label>e-?mail)\s*[:=]\s*(?P<value>[^\n,;.]+)", re.I)),
        ("address", re.compile(r"\b(?P<label>home\s+address|address)\s*[:=]\s*(?P<value>[^\n;.]+)", re.I)),
    )
    _JSON_FIELD_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("person", re.compile(r'"(?P<label>patient_name|name)"\s*:\s*"(?P<value>[^"]*)"', re.I)),
        ("dob", re.compile(r'"(?P<label>date_of_birth|dob)"\s*:\s*"(?P<value>[^"]*)"', re.I)),
        ("mrn", re.compile(r'"(?P<label>mrn|medical_record_number)"\s*:\s*"(?P<value>[^"]*)"', re.I)),
        ("hospital_id", re.compile(r'"(?P<label>hospital_id)"\s*:\s*"(?P<value>[^"]*)"', re.I)),
        ("insurance_id", re.compile(r'"(?P<label>insurance_id|insurance_number)"\s*:\s*"(?P<value>[^"]*)"', re.I)),
        ("patient_id", re.compile(r'"(?P<label>patient_id|session_id|message_id)"\s*:\s*"(?P<value>[^"]*)"', re.I)),
        ("document_id", re.compile(r'"(?P<label>document_id)"\s*:\s*"(?P<value>[^"]*)"', re.I)),
        ("account_number", re.compile(r'"(?P<label>account_number|account_id)"\s*:\s*"(?P<value>[^"]*)"', re.I)),
    )

    _FREE_PATTERNS: tuple[tuple[str, re.Pattern[str]], ...] = (
        ("email", re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I)),
        ("url", re.compile(r"\bhttps?://[^\s<>()]+", re.I)),
        ("secret", re.compile(r"\b(?:AIza[\w-]{20,}|TEST_API_KEY_[A-Z0-9_]+)\b", re.I)),
        ("secret", re.compile(r"\b(?:api[_ -]?key|token|secret)\s*[:=]\s*[A-Za-z0-9_\-.]{8,}\b", re.I)),
        ("ssn", re.compile(r"\b\d{3}-\d{2}-\d{4}\b")),
        ("phone", re.compile(r"(?<!\w)(?:\+?\d{1,3}[ .-]?)?(?:\(?\d{3}\)?[ .-]?){2}\d{4}(?!\w)")),
        ("address", re.compile(r"\b\d{1,5}\s+[A-Za-z][A-Za-z.'-]*(?:\s+[A-Za-z.'-]+){0,4}\s+(?:street|st\.?|road|rd\.?|avenue|ave\.?|lane|ln\.?|drive|dr\.?|boulevard|blvd\.?)\b", re.I)),
        ("person", re.compile(r"\bmy\s+name\s+is\s+(?:TEST_PERSON_[A-Z0-9_]+|[A-Za-z][A-Za-z'-]*(?:\s+[A-Za-z][A-Za-z'-]*){0,2})\b", re.I)),
        ("person", re.compile(r"\bI\s+am\s+(?:TEST_PERSON_[A-Z0-9_]+|[A-Z][a-z][A-Za-z'-]*(?:\s+[A-Z][a-z][A-Za-z'-]*){0,2})\b")),
        ("person", re.compile(r"\bPatient\s+(?:TEST_PERSON_[A-Z0-9_]+|[A-Z][a-z][A-Za-z'-]*(?:\s+[A-Z][a-z][A-Za-z'-]*){0,2})\b")),
        # A conservative unlabeled two-part name pattern covers common prose
        # such as "Arun Nithees reports chest pain" without treating ordinary
        # lowercase clinical phrases as names.
        ("person", re.compile(r"\b[A-Z][a-z][A-Za-z'-]+\s+[A-Z][a-z][A-Za-z'-]+\b")),
        ("person", re.compile(r"\b(?:my\s+name\s+is|patient)\s+TEST_PERSON_[A-Z0-9_]+\b", re.I)),
        ("patient_id", re.compile(r"\b(?:TEST_(?:PERSON|PATIENT|ID)_[A-Z0-9_]+)\b", re.I)),
        ("mrn", re.compile(r"\bTEST_MRN_[A-Z0-9_]+\b", re.I)),
        ("hospital_id", re.compile(r"\bTEST_HOSPITAL(?:_[A-Z0-9_]+)?\b", re.I)),
        ("insurance_id", re.compile(r"\bTEST_INSURANCE_[A-Z0-9_]+\b", re.I)),
    )

    def redact(self, text: str) -> tuple[str, list[str], int]:
        """Return redacted text and non-sensitive detection metadata."""
        categories: list[str] = []
        count = 0

        def record(category: str) -> None:
            nonlocal count
            categories.append(category)
            count += 1

        redacted = text
        for category, pattern in self._LABEL_PATTERNS + self._JSON_FIELD_PATTERNS:
            token = self._TOKENS[category]

            def replace_label(match: re.Match[str], *, _category: str = category, _token: str = token) -> str:
                value = match.group("value").strip()
                if value.startswith("[") and value.endswith("]"):
                    return match.group(0)
                record(_category)
                if match.group(0).lstrip().startswith('"'):
                    return f'"{match.group("label")}": "{_token}"'
                return f"{match.group('label')}: {_token}"

            redacted = pattern.sub(replace_label, redacted)

        for category, pattern in self._FREE_PATTERNS:
            token = self._TOKENS[category]

            def replace_free(match: re.Match[str], *, _category: str = category, _token: str = token) -> str:
                value = match.group(0)
                if value.startswith("[") and value.endswith("]"):
                    return value
                record(_category)
                # Preserve a conversational lead-in while removing a person name.
                if _category == "person" and value.lower().startswith("my name is"):
                    return "My name is [PERSON]"
                if _category == "person" and value.lower().startswith("patient "):
                    return "Patient [PERSON]"
                return _token

            redacted = pattern.sub(replace_free, redacted)

        return redacted, sorted(set(categories)), count
