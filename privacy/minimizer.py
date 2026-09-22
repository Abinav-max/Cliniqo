"""Conservative data minimization after identifier redaction."""

from __future__ import annotations

import re


class PayloadMinimizer:
    """Remove identity-only fragments while retaining clinically useful facts."""

    _IDENTITY_LINE = re.compile(
        r"^\s*(?:patient\s+name|name|mrn|medical\s+record(?:\s+number)?|"
        r"hospital(?:\s+id)?|patient(?:\s+id)?|insurance(?:\s+id)?|"
        r"document(?:\s+id)?|phone|mobile|telephone|e-?mail|address|"
        r"account(?:\s+number)?|date\s+of\s+birth|dob)\s*:\s*\[[A-Z_]+\]\s*$",
        re.I,
    )
    _NAME_CLAUSE = re.compile(r"\bmy\s+name\s+is\s+\[PERSON\]\s*[,.;-]*\s*", re.I)

    def minimize(self, text: str, *, source_type: str) -> str:
        """Drop standalone identifiers and normalize whitespace.

        The gateway deliberately does not remove symptoms, duration, medication,
        allergy, laboratory, contradiction, or uncertainty content.
        """
        lines = [line for line in text.splitlines() if not self._IDENTITY_LINE.match(line)]
        minimized = "\n".join(lines)
        minimized = self._NAME_CLAUSE.sub("", minimized)
        # Repeated whitespace is not clinically meaningful and only increases the
        # outbound payload. Newlines are retained for JSON/OCR readability.
        minimized = re.sub(r"[ \t]+", " ", minimized)
        minimized = re.sub(r"\n{3,}", "\n\n", minimized).strip()
        return minimized
