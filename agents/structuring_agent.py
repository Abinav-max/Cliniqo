"""Clinical Structuring Agent: grounded conversation-to-history extraction."""

from __future__ import annotations

import json
import re
from collections.abc import Iterable
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from core.exceptions import LLMConnectionError, LLMResponseError, StructuredOutputError
from core.prompts import SAFETY_SYSTEM_INSTRUCTION, STRUCTURING_SYSTEM_INSTRUCTION
from core.schemas import ClinicalHistory, HistoryOfPresentIllness, MedicationMention
from privacy import PrivacyGateway, PrivacyGatewayError


@runtime_checkable
class SupportsGenerateJson(Protocol):
    """The JSON interface shared by the existing LLM client and test doubles."""

    def generate_json(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any: ...


_SPECULATION = re.compile(
    r"\b(i think|i believe|i'?m worried|i am worried|maybe|might be|could be|"
    r"do i have|am i having)\b",
    re.IGNORECASE,
)
_NO_MEDICATION = re.compile(
    r"\b(no|not|don'?t|do not)\s+(take|taking|on)\s+(any\s+)?"
    r"(medication|medications|medicine|medicines|meds|pills)\b",
    re.IGNORECASE,
)
_TAKING_MEDICATION = re.compile(
    r"\b(i\s+(?:am\s+)?taking|i\s+take|my\s+medication|on)\b",
    re.IGNORECASE,
)
_NONFACTUAL_INSTRUCTION = re.compile(
    r"\b(?:assume|pretend|invent|add)\b", re.IGNORECASE
)
_THIRD_PARTY_DIAGNOSIS_CLAIM = re.compile(
    r"\b(?:doctor|clinician|someone|they)\s+(?:already\s+)?said\s+i\s+"
    r"(?:have|am having)\b",
    re.IGNORECASE,
)

_UNKNOWN_FIELDS = (
    "chief_complaint",
    "onset",
    "duration",
    "location",
    "quality",
    "severity",
    "timing",
    "progression",
    "associated_symptoms",
    "past_medical_history",
    "previous_similar_episodes",
    "medications",
    "allergies",
    "family_history",
    "personal_history",
    "previous_investigations",
)

# Maps interview-agent category names to HistoryOfPresentIllness field names.
# The mapping is generic; no symptom-specific rules.
_INTERVIEW_TO_HPI: dict[str, str] = {
    "onset": "onset",
    "duration": "duration",
    "location": "location",
    "character": "quality",
    "severity": "severity",
    "timing": "timing",
    "progression": "progression",
}

# Maps interview-agent category names to ClinicalHistory list-valued fields.
_INTERVIEW_TO_HISTORY_LIST: dict[str, str] = {
    "associated_symptoms": "associated_symptoms",
    "past_medical_history": "past_medical_history",
    "allergies": "allergies",
    "family_history": "family_history",
    "previous_similar_episodes": "previous_similar_episodes",
    "previous_investigations": "previous_investigations",
}


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _normalise_numbers(text: str) -> str:
    """Treat simple reported number words and digits as equivalent for grounding."""
    numbers = {
        "zero": "0",
        "one": "1",
        "two": "2",
        "three": "3",
        "four": "4",
        "five": "5",
        "six": "6",
        "seven": "7",
        "eight": "8",
        "nine": "9",
        "ten": "10",
    }
    return re.sub(r"\b(?:" + "|".join(numbers) + r")\b", lambda m: numbers[m.group(0)], _normalise(text))


def _unique(values: Iterable[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        key = _normalise(value)
        if value and key not in seen:
            seen.add(key)
            output.append(value)
    return output


class StructuringAgent:
    """Extract only patient-reported facts into a validated ``ClinicalHistory``.

    LLM output is treated as untrusted: it is Pydantic-validated and then
    grounded against patient turns before being returned.
    """

    def __init__(
        self,
        llm: Optional[SupportsGenerateJson] = None,
        *,
        temperature: float = 0.0,
        privacy_gateway: Optional[PrivacyGateway] = None,
    ) -> None:
        if llm is None:
            from core.llm_client import LLMClient

            llm = LLMClient()
        self._llm = llm
        self._temperature = temperature
        self._privacy_gateway = privacy_gateway or PrivacyGateway()
        self._system_prompt = (
            f"{SAFETY_SYSTEM_INSTRUCTION}\n\n{STRUCTURING_SYSTEM_INSTRUCTION}"
        )

    def structure(
        self, conversation: Any, *, session_id: Optional[str] = None
    ) -> ClinicalHistory:
        """Return a grounded structured history from Phase 1 or raw turns."""
        turns, inferred_session_id, interview_fields = self._coerce_conversation(
            conversation
        )
        effective_session = session_id or inferred_session_id
        if not turns:
            return self._empty_history(effective_session)

        history: Optional[ClinicalHistory] = None
        is_provider_failure = False
        try:
            raw = self._generate(self._build_prompt(turns, interview_fields))
        except StructuredOutputError as first:
            if str(first) == "PRIVACY_GATEWAY_BLOCKED":
                raise
            # The shared client may reject malformed provider JSON before this
            # agent receives it. Repair from the de-identified source alone;
            # never reconstruct or resend a raw failed provider response.
            try:
                history = self._validate(
                    self._generate(self._build_repair_prompt(turns, {}, first))
                )
            except (LLMConnectionError, LLMResponseError):
                is_provider_failure = True
            except Exception:
                pass  # Validation repair failed
        except (LLMConnectionError, LLMResponseError):
            # Rate limit, timeout, or provider connection failure.
            is_provider_failure = True
        else:
            try:
                history = self._validate_or_repair(raw, turns)
            except StructuredOutputError:
                pass  # Validation repair also failed

        if history is None:
            if not interview_fields and not is_provider_failure:
                raise StructuredOutputError(
                    "Clinical structuring output could not be repaired and validated."
                )
            history = self._build_from_interview(interview_fields, effective_session)

        history.session_id = effective_session or history.session_id
        history = self._ground_and_normalise(history, turns)
        return self._apply_interview_fields(history, interview_fields, turns)

    # Friendly aliases make the boundary easy to use in a pipeline.
    structure_conversation = structure
    extract = structure

    def _generate(self, prompt: str) -> Any:
        try:
            safe_prompt = self._privacy_gateway.prepare(
                prompt, source_type="structuring"
            ).safe_text
        except PrivacyGatewayError as exc:
            raise StructuredOutputError("PRIVACY_GATEWAY_BLOCKED") from exc
        return self._llm.generate_json(
            safe_prompt,
            schema=ClinicalHistory,
            system_instruction=self._system_prompt,
            temperature=self._temperature,
        )

    def _validate_or_repair(
        self, raw: Any, turns: list[tuple[str, str]]
    ) -> ClinicalHistory:
        try:
            return self._validate(raw)
        except (ValidationError, StructuredOutputError, TypeError, ValueError) as first:
            repair_prompt = self._build_repair_prompt(turns, raw, first)
            try:
                return self._validate(self._generate(repair_prompt))
            except Exception as second:  # controlled, typed application error
                raise StructuredOutputError(
                    "Clinical structuring output could not be repaired and validated."
                ) from second

    @staticmethod
    def _validate(raw: Any) -> ClinicalHistory:
        if isinstance(raw, ClinicalHistory):
            return raw
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise TypeError("Clinical structuring output must be a JSON object.")
        return ClinicalHistory.model_validate(raw)

    def _build_prompt(
        self,
        turns: list[tuple[str, str]],
        interview_fields: Optional[dict[str, Any]] = None,
    ) -> str:
        rendered = "\n".join(f"{role.title()}: {content}" for role, content in turns)
        hint = ""
        if interview_fields:
            clean = {k: v for k, v in interview_fields.items() if not k.startswith("_")}
            if clean:
                hint = (
                    "\n\nThe interview agent has already deterministically extracted "
                    "these explicit patient-stated facts. Map them to the appropriate "
                    "ClinicalHistory fields (e.g. 'character' maps to "
                    "history_of_present_illness.quality, 'chief_complaint' maps to "
                    "chief_complaint). Include matching patient excerpts in "
                    "source_evidence.\n"
                    + json.dumps(clean, indent=2)
                )
        return (
            "Extract a ClinicalHistory JSON object from this conversation.\n\n"
            "Conversation:\n"
            f"{rendered}{hint}\n\n"
            "Return only fields supported by the ClinicalHistory schema. Populate a "
            "field only when the patient explicitly said it. Use exact patient "
            "excerpts in source_evidence. Do not include a diagnosis field."
        )

    def _build_repair_prompt(
        self,
        turns: list[tuple[str, str]],
        raw: Any,
        error: Exception,
    ) -> str:
        # The failed payload is included only for formatting repair; the source
        # conversation remains the sole authority for patient facts.
        try:
            failed = json.dumps(raw, default=str)
        except TypeError:
            failed = repr(raw)
        return (
            "Repair the previous attempted ClinicalHistory JSON. Return a complete "
            "valid ClinicalHistory object. Discard every unsupported field/value and "
            "use only the conversation below as factual source.\n\n"
            f"Validation problem: {error}\nAttempted output: {failed}\n\n"
            + self._build_prompt(turns)
        )

    @staticmethod
    def _coerce_conversation(
        value: Any,
    ) -> tuple[list[tuple[str, str]], Optional[str], dict[str, Any]]:
        """Accept raw turns plus the actual Phase 1 state/result interfaces.

        Returns ``(turns, session_id, interview_fields)`` where
        *interview_fields* maps interview-agent category names to their
        deterministically extracted explicit values.
        """
        session_id = getattr(value, "session_id", None)
        interview_fields: dict[str, Any] = {}
        if hasattr(value, "state"):
            state = value.state
            session_id = session_id or getattr(state, "session_id", None)
            # Capture deterministic interview-extracted explicit fields so the
            # structuring pipeline can use them as a seed/fallback.
            patient_info = getattr(state, "patient_information", None)
            if patient_info is not None:
                for name, item in getattr(patient_info, "fields", {}).items():
                    status_val = getattr(getattr(item, "status", None), "value", getattr(item, "status", None))
                    if (
                        status_val == "explicit"
                        and getattr(item, "value", None)
                    ):
                        interview_fields[name] = item.value
                concerns = getattr(patient_info, "patient_reported_concerns", [])
                if concerns:
                    interview_fields["_concerns"] = list(concerns)
                urgent = getattr(patient_info, "urgent_symptoms_mentioned", [])
                if urgent:
                    interview_fields["_urgent"] = list(urgent)
            value = state
        if hasattr(value, "conversation_history"):
            value = value.conversation_history

        if isinstance(value, str):
            turns: list[tuple[str, str]] = []
            for line in value.splitlines():
                match = re.match(r"\s*(patient|assistant|clinician)\s*:\s*(.+)", line, re.I)
                if match:
                    turns.append((match.group(1).lower(), match.group(2).strip()))
            return (
                (turns or [("patient", value.strip())] if value.strip() else []),
                session_id,
                interview_fields,
            )

        if not isinstance(value, Iterable):
            raise TypeError("Conversation must be text, turns, or a Phase 1 interview state.")
        turns = []
        for turn in value:
            if isinstance(turn, dict):
                role, content = turn.get("role"), turn.get("content")
            else:
                role, content = getattr(turn, "role", None), getattr(turn, "content", None)
            if isinstance(role, str) and isinstance(content, str) and content.strip():
                turns.append((role.lower(), content.strip()))
        return turns, session_id, interview_fields

    @staticmethod
    def _empty_history(session_id: Optional[str]) -> ClinicalHistory:
        return ClinicalHistory(
            session_id=session_id,
            missing_information=list(_UNKNOWN_FIELDS),
            unknown_information=list(_UNKNOWN_FIELDS),
        )

    def _ground_and_normalise(
        self, history: ClinicalHistory, turns: list[tuple[str, str]]) -> ClinicalHistory:
        patient_texts = [content for role, content in turns if role == "patient"]
        patient_blob = " ".join(patient_texts)

        def deidentified(text: str) -> str:
            try:
                res = self._privacy_gateway.prepare(
                    text or " ", source_type="structuring_grounding"
                ).safe_text
                return res if res.strip() else (text or "")
            except Exception:
                # Local grounding comparison, never an egress path.
                return text or ""

        safe_patient_blob = deidentified(patient_blob)

        def evidence(key: str) -> Optional[str]:
            item = history.source_evidence.get(key)
            if item and _normalise(deidentified(item)) in _normalise(safe_patient_blob):
                return item
            return None

        def supported(value: object, key: str) -> bool:
            if value is None:
                return False
            value_text = str(value)
            source = evidence(key) or patient_blob
            normal_value = _normalise_numbers(value_text)
            normal_source = _normalise_numbers(source)
            if normal_value and normal_value in normal_source:
                return True
            tokens = re.findall(r"[a-z0-9]+", normal_value)
            return bool(tokens) and all(token in normal_source for token in tokens)

        def fact(value: Optional[str], key: str) -> Optional[str]:
            return value if value and supported(value, key) else None

        # Canonical/legacy aliases are kept in sync without losing old callers.
        complaint = fact(history.chief_complaint or history.chief_concern, "chief_complaint")
        if complaint and evidence("chief_complaint") and _SPECULATION.search(
            evidence("chief_complaint") or ""
        ):
            complaint = None
        if complaint is None:
            complaint = fact(history.chief_concern, "chief_concern")
            if complaint and evidence("chief_concern") and _SPECULATION.search(
                evidence("chief_concern") or ""
            ):
                complaint = None
        history.chief_complaint = history.chief_concern = complaint

        hpi = history.history_of_present_illness
        # A legacy string is schema-compatible for existing callers, but is
        # not detailed enough to be safely mapped to a particular HPI field.
        if not isinstance(hpi, HistoryOfPresentIllness):
            hpi = HistoryOfPresentIllness()
            history.history_of_present_illness = hpi
        for name in ("onset", "duration", "location", "quality", "timing", "progression"):
            setattr(hpi, name, fact(getattr(hpi, name), f"history_of_present_illness.{name}"))
        if hpi.severity is not None and not supported(
            hpi.severity, "history_of_present_illness.severity"
        ):
            hpi.severity = None

        def grounded_list(values: list[str], key: str, *, reject_speculation: bool = False) -> list[str]:
            result: list[str] = []
            for value in values:
                source = evidence(key) or patient_blob
                if reject_speculation and _SPECULATION.search(source):
                    continue
                if supported(value, key):
                    result.append(value)
            return _unique(result)

        symptoms = grounded_list(
            history.associated_symptoms or history.reported_symptoms, "associated_symptoms"
        )
        if not symptoms:
            symptoms = grounded_list(history.reported_symptoms, "reported_symptoms")
        history.associated_symptoms = history.reported_symptoms = symptoms
        allergies = grounded_list(history.allergies or history.reported_allergies, "allergies")
        if not allergies:
            allergies = grounded_list(history.reported_allergies, "reported_allergies")
        history.allergies = history.reported_allergies = allergies
        history.past_medical_history = grounded_list(
            history.past_medical_history, "past_medical_history", reject_speculation=True
        )
        past_source = evidence("past_medical_history") or patient_blob
        if _THIRD_PARTY_DIAGNOSIS_CLAIM.search(past_source):
            history.past_medical_history = []
        history.family_history = grounded_list(history.family_history, "family_history")
        history.previous_similar_episodes = grounded_list(
            history.previous_similar_episodes, "previous_similar_episodes"
        )
        history.previous_investigations = grounded_list(
            history.previous_investigations, "previous_investigations"
        )
        history.social_history = fact(history.social_history, "social_history")

        valid_personal: dict[str, Any] = {}
        for key, value in history.personal_history.items():
            source = evidence(f"personal_history.{key}") or patient_blob
            if (
                isinstance(value, str)
                and not _NONFACTUAL_INSTRUCTION.search(source)
                and supported(value, f"personal_history.{key}")
            ):
                valid_personal[key] = value
        history.personal_history = valid_personal

        medications: list[MedicationMention] = []
        for medication in history.medications or history.reported_medications:
            key = "medications"
            medication_source = evidence(key) or patient_blob
            if _NONFACTUAL_INSTRUCTION.search(medication_source):
                continue
            parts = [medication.name_as_reported]
            if medication.dose_as_reported:
                parts.append(medication.dose_as_reported)
            if medication.frequency_as_reported:
                parts.append(medication.frequency_as_reported)
            if supported(" ".join(parts), key) or supported(medication.name_as_reported, key):
                # Unsupported dose/frequency must not be retained merely because
                # the medication name was reported.
                medication.dose_as_reported = fact(medication.dose_as_reported, key)
                medication.frequency_as_reported = fact(medication.frequency_as_reported, key)
                medication.notes = fact(medication.notes, key)
                medications.append(medication)
        history.medications = history.reported_medications = medications

        history.patient_reported_concerns = self._ground_concerns(
            history.patient_reported_concerns, patient_texts
        )
        history.contradictions = self._contradictions(patient_texts)

        missing = self._missing_fields(history)
        history.unknown_information = missing
        history.missing_information = list(missing)
        history.source_evidence = {
            key: source
            for key, source in history.source_evidence.items()
            if _normalise(deidentified(source)) in _normalise(safe_patient_blob)
        }
        return history

    @staticmethod
    def _ground_concerns(concerns: list[str], patient_texts: list[str]) -> list[str]:
        result = [c for c in concerns if any(_normalise(c) in _normalise(t) for t in patient_texts)]
        for text in patient_texts:
            if _SPECULATION.search(text) or _THIRD_PARTY_DIAGNOSIS_CLAIM.search(text):
                match = re.search(r"\b(?:have|having|about)\s+([^?.!]+)", text, re.I)
                if match:
                    if _THIRD_PARTY_DIAGNOSIS_CLAIM.search(text):
                        concern = f"Patient reports that a clinician said they have {match.group(1).strip()}."
                    else:
                        concern = f"Patient reports believing they may have {match.group(1).strip()}."
                    result.append(concern)
                else:
                    result.append(text.strip())
        return _unique(result)

    @staticmethod
    def _contradictions(patient_texts: list[str]) -> list[str]:
        has_denial = any(_NO_MEDICATION.search(text) for text in patient_texts)
        has_use = any(_TAKING_MEDICATION.search(text) for text in patient_texts)
        if has_denial and has_use:
            return ["Medication history contains conflicting statements."]
        return []

    @staticmethod
    def _missing_fields(history: ClinicalHistory) -> list[str]:
        hpi = history.history_of_present_illness
        if not isinstance(hpi, HistoryOfPresentIllness):
            hpi = HistoryOfPresentIllness()
        populated = {
            "chief_complaint": history.chief_complaint,
            "onset": hpi.onset,
            "duration": hpi.duration,
            "location": hpi.location,
            "quality": hpi.quality,
            "severity": hpi.severity,
            "timing": hpi.timing,
            "progression": hpi.progression,
            "associated_symptoms": history.associated_symptoms,
            "past_medical_history": history.past_medical_history,
            "previous_similar_episodes": history.previous_similar_episodes,
            "medications": history.medications,
            "allergies": history.allergies,
            "family_history": history.family_history,
            "personal_history": history.personal_history,
            "previous_investigations": history.previous_investigations,
        }
        return [field for field in _UNKNOWN_FIELDS if not populated[field]]

    def _build_from_interview(
        self,
        interview_fields: dict[str, Any],
        session_id: Optional[str],
    ) -> ClinicalHistory:
        """Build a ``ClinicalHistory`` from interview-extracted explicit fields.

        Used as a graceful fallback when the LLM is unavailable (rate limit,
        connection failure).  Only deterministically extracted EXPLICIT values
        are used; nothing is invented.
        """
        history = ClinicalHistory(session_id=session_id)
        if "chief_complaint" in interview_fields:
            history.chief_complaint = history.chief_concern = interview_fields[
                "chief_complaint"
            ]
        hpi = HistoryOfPresentIllness()
        for interview_name, hpi_name in _INTERVIEW_TO_HPI.items():
            if interview_name in interview_fields:
                setattr(hpi, hpi_name, interview_fields[interview_name])
        history.history_of_present_illness = hpi
        for interview_name, history_name in _INTERVIEW_TO_HISTORY_LIST.items():
            if interview_name in interview_fields:
                value = interview_fields[interview_name]
                if isinstance(value, str):
                    new_list = [value]
                    setattr(history, history_name, new_list)
                    if history_name == "associated_symptoms":
                        history.reported_symptoms = new_list
                    elif history_name == "allergies":
                        history.reported_allergies = new_list
        if "social_history" in interview_fields:
            history.social_history = interview_fields["social_history"]
        if "_concerns" in interview_fields:
            history.patient_reported_concerns = list(interview_fields["_concerns"])
        missing = self._missing_fields(history)
        history.missing_information = list(missing)
        history.unknown_information = list(missing)
        return history

    def _apply_interview_fields(
        self,
        history: ClinicalHistory,
        interview_fields: dict[str, Any],
        turns: list[tuple[str, str]],
    ) -> ClinicalHistory:
        """Re-apply interview-extracted explicit fields that grounding may have
        stripped.

        The interview agent already validated these values against patient text
        using deterministic extraction.  This pass fills only ``None``/empty
        fields — it never overwrites a value that survived grounding.
        """
        if not interview_fields:
            return history
        if not history.chief_complaint and "chief_complaint" in interview_fields:
            history.chief_complaint = history.chief_concern = interview_fields[
                "chief_complaint"
            ]
        hpi = history.history_of_present_illness
        if not isinstance(hpi, HistoryOfPresentIllness):
            hpi = HistoryOfPresentIllness()
            history.history_of_present_illness = hpi
        for interview_name, hpi_name in _INTERVIEW_TO_HPI.items():
            if interview_name in interview_fields and getattr(hpi, hpi_name) is None:
                setattr(hpi, hpi_name, interview_fields[interview_name])
        for interview_name, history_name in _INTERVIEW_TO_HISTORY_LIST.items():
            if interview_name in interview_fields:
                current = getattr(history, history_name, None) or []
                if not current:
                    value = interview_fields[interview_name]
                    if isinstance(value, str):
                        new_list = [value]
                        setattr(history, history_name, new_list)
                        if history_name == "associated_symptoms":
                            history.reported_symptoms = new_list
                        elif history_name == "allergies":
                            history.reported_allergies = new_list
        if "social_history" in interview_fields and not history.social_history:
            history.social_history = interview_fields["social_history"]
        if "_concerns" in interview_fields:
            existing = {_normalise(c) for c in history.patient_reported_concerns}
            for concern in interview_fields["_concerns"]:
                if _normalise(concern) not in existing:
                    history.patient_reported_concerns.append(concern)
        # Recalculate missing fields with restored interview data.
        missing = self._missing_fields(history)
        history.missing_information = list(missing)
        history.unknown_information = list(missing)
        return history
