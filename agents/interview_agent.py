"""Interview Agent: gathers clinical history. Does not diagnose."""

from __future__ import annotations

import logging
import re
from enum import Enum
from typing import Any, Optional, Protocol, runtime_checkable
from uuid import uuid4

from pydantic import BaseModel, ConfigDict, Field

from core.exceptions import LLMConnectionError, LLMResponseError, StructuredOutputError
from core.prompts import INTERVIEW_SYSTEM_INSTRUCTION, SAFETY_SYSTEM_INSTRUCTION
from privacy import PrivacyGateway, PrivacyGatewayError

logger = logging.getLogger(__name__)

INTERVIEW_CATEGORIES: tuple[str, ...] = (
    "chief_complaint",
    "onset",
    "duration",
    "location",
    "character",
    "severity",
    "timing",
    "progression",
    "associated_symptoms",
    "past_medical_history",
    "previous_similar_episodes",
    "current_medications",
    "allergies",
    "family_history",
    "social_history",
    "previous_investigations",
    "risk_context",
)

_UNKNOWN_PHRASES = (
    "i don't know",
    "i do not know",
    "i'm not sure",
    "im not sure",
    "not sure",
    "no idea",
    "i have no idea",
    "unknown",
)

_DIAGNOSIS_REQUEST = re.compile(
    r"\b("
    r"what (disease|condition|illness|diagnosis)|"
    r"what('?s| is) wrong|"
    r"do i have|"
    r"am i having|"
    r"diagnos|"
    r"what could it be"
    r")\b",
    re.IGNORECASE,
)

_DIAGNOSIS_OUTPUT = re.compile(
    r"\b("
    r"you have|"
    r"you are having|"
    r"your diagnosis|"
    r"this is (a |an )?(heart attack|stroke|migraine|infection)|"
    r"you likely have|"
    r"you probably have|"
    r"it is (probably|likely)|"
    r"i diagnose|"
    r"the diagnosis"
    r")\b",
    re.IGNORECASE,
)

_REPORTED_CONCERN = re.compile(
    r"\b(i think i (have|am having)|i('m| am) having a|this (is|must be) (a |an )?)\b",
    re.IGNORECASE,
)

_URGENT_PATTERNS = (
    "chest pain",
    "crushing pain",
    "shortness of breath",
    "can't breathe",
    "cannot breathe",
    "fainting",
    "passed out",
    "worst headache",
    "suicidal",
    "severe bleeding",
    "stroke",
    "heart attack",
)

_ASK_HINTS: dict[str, tuple[str, ...]] = {
    "chief_complaint": ("what brings you", "main concern", "what is bothering"),
    "onset": ("when did", "when it start", "what started"),
    "duration": ("how long", "duration", "for how long"),
    "location": ("where", "which part", "location"),
    "character": ("what does it feel", "quality", "sharp", "dull", "character"),
    "severity": ("how severe", "0 to 10", "0-10", "scale of"),
    "timing": ("constant", "come and go", "time of day", "when does it"),
    "progression": ("getting worse", "changing", "progress"),
    "associated_symptoms": ("anything else", "other symptoms", "associated"),
    "past_medical_history": ("medical history", "other conditions", "past medical"),
    "previous_similar_episodes": ("happened before", "similar episode"),
    "current_medications": ("medication", "medicines", "pills"),
    "allergies": ("allerg",),
    "family_history": ("family history", "family have"),
    "social_history": ("smoke", "alcohol", "work", "live"),
    "previous_investigations": ("test", "scan", "investigation", "lab"),
    "risk_context": ("risk", "trigger", "context"),
}

_QUESTION_TEMPLATES: dict[str, str] = {
    "chief_complaint": "What is the main problem you would like the clinician to know about?",
    "onset": "When did this start?",
    "duration": "How long has this been going on?",
    "location": "Where do you feel it?",
    "character": "What does it feel like?",
    "severity": "How severe is it on a scale of 0 to 10?",
    "timing": "Is it constant, or does it come and go?",
    "progression": "Has it been getting better, worse, or staying the same?",
    "associated_symptoms": "Have you noticed any other symptoms along with this?",
    "past_medical_history": "Do you have any other medical conditions that a clinician should know about?",
    "previous_similar_episodes": "Have you had anything like this before?",
    "current_medications": "Are you taking any medications?",
    "allergies": "Do you have any allergies?",
    "family_history": "Is there any relevant family medical history you want the clinician to know?",
    "social_history": "Is there anything about smoking, alcohol, work, or daily life that seems relevant?",
    "previous_investigations": "Have you had any tests or scans for this already?",
    "risk_context": "Is there anything else about the setting or what you were doing that seems important?",
}

_NON_DIAGNOSIS_PREFIX = (
    "I can't diagnose or say what condition this is — that is for a clinician. "
    "I can keep gathering history so they have a clearer picture. "
)


class InformationStatus(str, Enum):
    EXPLICIT = "explicit"
    INFERRED = "inferred"
    UNKNOWN = "unknown"


class HistoryItem(BaseModel):
    """One interview field with provenance. Inferred is never treated as fact."""

    model_config = ConfigDict(extra="forbid")

    value: Optional[str] = None
    status: InformationStatus = InformationStatus.UNKNOWN
    patient_excerpt: Optional[str] = None


def _empty_information() -> dict[str, HistoryItem]:
    return {name: HistoryItem() for name in INTERVIEW_CATEGORIES}


class PatientInformation(BaseModel):
    model_config = ConfigDict(extra="forbid")

    fields: dict[str, HistoryItem] = Field(default_factory=_empty_information)
    patient_reported_concerns: list[str] = Field(default_factory=list)
    urgent_symptoms_mentioned: list[str] = Field(default_factory=list)

    def explicit_value(self, category: str) -> Optional[str]:
        item = self.fields.get(category)
        if item and item.status == InformationStatus.EXPLICIT and item.value:
            return item.value
        return None

    def as_collected_dict(self) -> dict[str, Any]:
        collected: dict[str, Any] = {
            name: item.model_dump() for name, item in self.fields.items()
        }
        collected["patient_reported_concerns"] = list(self.patient_reported_concerns)
        collected["urgent_symptoms_mentioned"] = list(self.urgent_symptoms_mentioned)
        return collected


class ConversationTurn(BaseModel):
    model_config = ConfigDict(extra="forbid")

    role: str
    content: str


class InterviewState(BaseModel):
    """Conversation + collected history. Separate from the LLM system prompt."""

    model_config = ConfigDict(extra="forbid")

    session_id: str
    conversation_history: list[ConversationTurn] = Field(default_factory=list)
    patient_information: PatientInformation = Field(default_factory=PatientInformation)
    missing_information: list[str] = Field(
        default_factory=lambda: list(INTERVIEW_CATEGORIES)
    )
    next_question_category: Optional[str] = None
    interview_complete: bool = False
    last_asked_category: Optional[str] = None


class FieldUpdate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    category: str
    value: Optional[str] = None
    status: InformationStatus = InformationStatus.UNKNOWN
    patient_excerpt: Optional[str] = None


class InterviewLLMResponse(BaseModel):
    """Structured model output for one interview turn."""

    model_config = ConfigDict(extra="ignore")

    assistant_message: str
    field_updates: list[FieldUpdate] = Field(default_factory=list)
    missing_information: list[str] = Field(default_factory=list)
    next_question_category: Optional[str] = None
    interview_complete: bool = False
    patient_reported_concerns: list[str] = Field(default_factory=list)
    urgent_symptoms_mentioned: list[str] = Field(default_factory=list)


class InterviewTurnResult(BaseModel):
    model_config = ConfigDict(extra="forbid")

    assistant_message: str
    information_collected: dict[str, Any]
    missing_information: list[str]
    next_question_category: Optional[str] = None
    interview_complete: bool = False
    state: InterviewState


@runtime_checkable
class SupportsGenerateJson(Protocol):
    def generate_json(
        self,
        prompt: str,
        *,
        schema: type[BaseModel] | None = None,
        system_instruction: Optional[str] = None,
        temperature: Optional[float] = None,
    ) -> Any: ...


def _normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _is_unknown_reply(text: str) -> bool:
    lowered = _normalize(text)
    return any(phrase in lowered for phrase in _UNKNOWN_PHRASES)


def _patient_texts(state: InterviewState) -> list[str]:
    return [
        turn.content
        for turn in state.conversation_history
        if turn.role == "patient"
    ]


def _is_grounded(value: str, sources: list[str]) -> bool:
    if not value or not sources:
        return False
    needle = _normalize(value)
    if len(needle) < 2:
        return False
    blob = _normalize(" ".join(sources))
    if needle in blob:
        return True
    tokens = [t for t in re.findall(r"[a-z0-9]+", needle) if len(t) > 2]
    if not tokens:
        return needle in blob
    return all(token in blob for token in tokens)


def _asks_about(message: str, category: str) -> bool:
    lowered = _normalize(message)
    return any(hint in lowered for hint in _ASK_HINTS.get(category, ()))


def _missing_categories(info: PatientInformation) -> list[str]:
    missing: list[str] = []
    for name in INTERVIEW_CATEGORIES:
        item = info.fields[name]
        if item.status == InformationStatus.EXPLICIT and item.value:
            continue
        if item.status == InformationStatus.UNKNOWN and item.patient_excerpt:
            continue
        missing.append(name)
    return missing


def _strip_diagnosis_language(message: str, next_category: Optional[str]) -> str:
    if not _DIAGNOSIS_OUTPUT.search(message):
        return message
    follow = _QUESTION_TEMPLATES.get(
        next_category or "onset",
        "Can you tell me a bit more about what you have noticed?",
    )
    return _NON_DIAGNOSIS_PREFIX + follow


class InterviewAgent:
    """Stateful clinical-history interviewer. Information gathering only."""

    def __init__(
        self,
        llm: Optional[SupportsGenerateJson] = None,
        *,
        session_id: Optional[str] = None,
        temperature: float = 0.2,
        privacy_gateway: Optional[PrivacyGateway] = None,
    ) -> None:
        if llm is None:
            from core.llm_client import LLMClient

            llm = LLMClient()
        self._llm = llm
        self._temperature = temperature
        self._privacy_gateway = privacy_gateway or PrivacyGateway()
        self._system_prompt = (
            f"{SAFETY_SYSTEM_INSTRUCTION}\n\n{INTERVIEW_SYSTEM_INSTRUCTION}"
        )
        self.state = InterviewState(session_id=session_id or str(uuid4()))
        self.patient_context: dict[str, Any] = {}

    def set_patient_context(self, context: dict[str, Any]) -> None:
        """Set longitudinal patient profile context for adaptive anamnesis."""
        self.patient_context = context or {}

    def handle_message(self, patient_message: str) -> InterviewTurnResult:
        text = (patient_message or "").strip()
        if not text:
            raise ValueError("Patient message must be a non-empty string.")

        self.state.conversation_history.append(
            ConversationTurn(role="patient", content=text)
        )
        self._apply_deterministic_updates(text)

        try:
            llm_turn = self._call_llm(text)
        except (LLMConnectionError, LLMResponseError, StructuredOutputError) as exc:
            logger.warning("LLM call failed during interview turn: %s. Using fallback.", exc)
            llm_turn = InterviewLLMResponse(
                assistant_message="",
                field_updates=[],
                missing_information=list(self.state.missing_information),
                next_question_category=None,
                interview_complete=False,
            )
        self._merge_llm_updates(llm_turn)

        missing = _missing_categories(self.state.patient_information)
        self.state.missing_information = missing
        next_category = self._choose_next_category(llm_turn, missing)
        self.state.next_question_category = next_category
        self.state.interview_complete = self._should_complete(llm_turn, missing)

        assistant_message = self._finalize_assistant_message(
            llm_turn.assistant_message,
            patient_message=text,
            next_category=next_category,
        )
        self.state.last_asked_category = next_category
        self.state.conversation_history.append(
            ConversationTurn(role="assistant", content=assistant_message)
        )

        return InterviewTurnResult(
            assistant_message=assistant_message,
            information_collected=self.state.patient_information.as_collected_dict(),
            missing_information=list(self.state.missing_information),
            next_question_category=next_category,
            interview_complete=self.state.interview_complete,
            state=self.state,
        )

    def _call_llm(self, latest_patient_message: str) -> InterviewLLMResponse:
        prompt = self._safe_prompt(self._build_user_prompt(latest_patient_message))
        raw = self._llm.generate_json(
            prompt,
            schema=None,
            system_instruction=self._system_prompt,
            temperature=self._temperature,
        )
        if isinstance(raw, InterviewLLMResponse):
            return raw
        return InterviewLLMResponse.model_validate(raw)

    def _safe_prompt(self, prompt: str) -> str:
        try:
            return self._privacy_gateway.prepare(
                prompt, source_type="interview"
            ).safe_text
        except PrivacyGatewayError as exc:
            raise StructuredOutputError("PRIVACY_GATEWAY_BLOCKED") from exc

    def _build_user_prompt(self, latest_patient_message: str) -> str:
        history_lines = [
            f"{turn.role}: {turn.content}"
            for turn in self.state.conversation_history
        ]
        context_block = ""
        if getattr(self, "patient_context", None):
            demog = self.patient_context.get("demographics") or "Not specified"
            conds = self.patient_context.get("chronic_conditions") or []
            algs = self.patient_context.get("allergies") or []
            meds = self.patient_context.get("medications") or []
            context_block = (
                "Patient Medical Profile & Longitudinal Baseline:\n"
                f"- Demographics: {demog}\n"
                f"- Documented Chronic Conditions: {', '.join(conds) if conds else 'None'}\n"
                f"- Known Allergies: {', '.join(algs) if algs else 'None'}\n"
                f"- Active Medications: {', '.join(meds) if meds else 'None'}\n\n"
                "Adaptive Anamnesis Rules:\n"
                "1. If patient reports chest pain, pressure, breathlessness, or palpitations and has a history of hypertension, diabetes, or cardiovascular disease: adapt immediately by asking targeted cardiac questions (radiation to arm/jaw, diaphoresis, crushing vs sharp, exertional onset) and note urgency.\n"
                "2. If symptoms relate to known chronic conditions, ask if this is an acute flare-up or recent change.\n"
                "3. Never ask the patient to re-enter established baseline demographics/allergies; focus questions on new symptoms, timeline, and acuity.\n\n"
            )

        return (
            f"{context_block}"
            "Current collected information (do not invent new patient facts):\n"
            f"{self.state.patient_information.model_dump_json(indent=2)}\n\n"
            "Conversation history:\n"
            f"{chr(10).join(history_lines)}\n\n"
            "Latest patient message:\n"
            f"{latest_patient_message}\n\n"
            "Return one interview turn as JSON with keys: "
            "assistant_message (string), field_updates (list of objects with "
            "category, value, status, patient_excerpt), missing_information "
            "(list of category names), next_question_category (string or null), "
            "interview_complete (boolean), patient_reported_concerns (list of "
            "strings), urgent_symptoms_mentioned (list of strings). "
            "status must be explicit, inferred, or unknown. "
            "Mark fields explicit only if the patient stated them. "
            "Use inferred only for cautious possibilities, never as facts. "
            "Do not diagnose."
        )

    def _apply_deterministic_updates(self, patient_text: str) -> None:
        info = self.state.patient_information
        lowered = _normalize(patient_text)

        if _REPORTED_CONCERN.search(patient_text):
            concern = patient_text.strip()
            if concern not in info.patient_reported_concerns:
                info.patient_reported_concerns.append(concern)

        for pattern in _URGENT_PATTERNS:
            if pattern in lowered and pattern not in info.urgent_symptoms_mentioned:
                info.urgent_symptoms_mentioned.append(pattern)

        if _is_unknown_reply(patient_text) and self.state.last_asked_category:
            category = self.state.last_asked_category
            info.fields[category] = HistoryItem(
                value=None,
                status=InformationStatus.UNKNOWN,
                patient_excerpt=patient_text.strip(),
            )
        else:
            self._record_answer_to_last_question(patient_text)

        if info.fields["chief_complaint"].status != InformationStatus.EXPLICIT:
            complaint = self._extract_chief_complaint(patient_text)
            if complaint:
                info.fields["chief_complaint"] = HistoryItem(
                    value=complaint,
                    status=InformationStatus.EXPLICIT,
                    patient_excerpt=patient_text.strip(),
                )

        self._maybe_extract_severity(patient_text)
        self._maybe_extract_duration(patient_text)

    def _record_answer_to_last_question(self, patient_text: str) -> None:
        category = self.state.last_asked_category
        if not category or category not in self.state.patient_information.fields:
            return
        if _DIAGNOSIS_REQUEST.search(patient_text):
            return
        current = self.state.patient_information.fields[category]
        if current.status == InformationStatus.EXPLICIT and current.value:
            return
        self.state.patient_information.fields[category] = HistoryItem(
            value=patient_text.strip(),
            status=InformationStatus.EXPLICIT,
            patient_excerpt=patient_text.strip(),
        )

    def _extract_chief_complaint(self, text: str) -> Optional[str]:
        if _REPORTED_CONCERN.search(text) and _DIAGNOSIS_REQUEST.search(text):
            return None
        lowered = _normalize(text)
        if _REPORTED_CONCERN.search(text):
            remainder = re.sub(
                r"(?i)i think i (have|am having)[^.?!]*[.?!]?",
                " ",
                text,
            )
            lowered = _normalize(remainder)
        match = re.search(
            r"\b(?:i have|i've got|i am having|i'm having|my)\s+(.+)",
            lowered,
        )
        if match:
            fragment = match.group(1).strip(" .")
            fragment = re.split(
                r"\b(for|since|about|and it|on a scale)\b", fragment, maxsplit=1
            )[0].strip(" .")
            if fragment and not _DIAGNOSIS_REQUEST.search(text):
                return fragment
        return None

    def _maybe_extract_severity(self, text: str) -> None:
        match = re.search(
            r"\b(?:severity(?:\s+is)?|pain(?:\s+is)?|it's|its|it is)?\s*"
            r"(?:a\s+)?(\d{1,2})\s*(?:/\s*10|out of 10)\b",
            _normalize(text),
        )
        if not match:
            match = re.search(
                r"\b(?:severity|pain)\s*(?:is|:)?\s*(\d{1,2})\b",
                _normalize(text),
            )
        if match:
            value = match.group(1)
            self.state.patient_information.fields["severity"] = HistoryItem(
                value=value,
                status=InformationStatus.EXPLICIT,
                patient_excerpt=text.strip(),
            )

    def _maybe_extract_duration(self, text: str) -> None:
        match = re.search(
            r"\b(?:for|lasted|lasting|since|over)\s+"
            r"(\d+\s+(?:minute|minutes|hour|hours|day|days|week|weeks|"
            r"month|months)|(?:yesterday|today|this morning))\b",
            _normalize(text),
        )
        if match:
            self.state.patient_information.fields["duration"] = HistoryItem(
                value=match.group(1),
                status=InformationStatus.EXPLICIT,
                patient_excerpt=text.strip(),
            )

    def _merge_llm_updates(self, llm_turn: InterviewLLMResponse) -> None:
        sources = _patient_texts(self.state)
        info = self.state.patient_information

        for concern in llm_turn.patient_reported_concerns:
            if concern and _is_grounded(concern, sources):
                if concern not in info.patient_reported_concerns:
                    info.patient_reported_concerns.append(concern)

        for urgent in llm_turn.urgent_symptoms_mentioned:
            if urgent and _is_grounded(urgent, sources):
                key = _normalize(urgent)
                if key not in {_normalize(x) for x in info.urgent_symptoms_mentioned}:
                    info.urgent_symptoms_mentioned.append(urgent)

        for update in llm_turn.field_updates:
            if update.category not in info.fields:
                continue
            current = info.fields[update.category]
            if (
                current.status == InformationStatus.EXPLICIT
                and current.value
                and update.status != InformationStatus.EXPLICIT
            ):
                continue

            if update.status == InformationStatus.UNKNOWN:
                if current.status == InformationStatus.EXPLICIT and current.value:
                    continue
                excerpt = update.patient_excerpt
                if excerpt and not _is_grounded(excerpt, sources):
                    excerpt = None
                info.fields[update.category] = HistoryItem(
                    value=None,
                    status=InformationStatus.UNKNOWN,
                    patient_excerpt=excerpt or current.patient_excerpt,
                )
                continue

            if not update.value:
                continue

            grounded = _is_grounded(update.value, sources) or (
                update.patient_excerpt is not None
                and _is_grounded(update.patient_excerpt, sources)
            )
            if update.status == InformationStatus.EXPLICIT:
                if not grounded:
                    continue
                info.fields[update.category] = HistoryItem(
                    value=update.value,
                    status=InformationStatus.EXPLICIT,
                    patient_excerpt=update.patient_excerpt,
                )
            elif update.status == InformationStatus.INFERRED:
                if current.status == InformationStatus.EXPLICIT and current.value:
                    continue
                info.fields[update.category] = HistoryItem(
                    value=update.value,
                    status=InformationStatus.INFERRED,
                    patient_excerpt=update.patient_excerpt,
                )

    def _choose_next_category(
        self, llm_turn: InterviewLLMResponse, missing: list[str]
    ) -> Optional[str]:
        if not missing:
            return None
        proposed = llm_turn.next_question_category
        if proposed in missing:
            return proposed
        return missing[0]

    def _should_complete(
        self, llm_turn: InterviewLLMResponse, missing: list[str]
    ) -> bool:
        info = self.state.patient_information
        if info.fields["chief_complaint"].status != InformationStatus.EXPLICIT:
            return False
        patient_turns = sum(
            1 for t in self.state.conversation_history if t.role == "patient"
        )
        if patient_turns < 4:
            return False
        core_remaining = [
            name
            for name in (
                "onset",
                "duration",
                "location",
                "character",
                "severity",
            )
            if name in missing
        ]
        if core_remaining:
            return False
        return bool(llm_turn.interview_complete) or len(missing) <= 4

    def _finalize_assistant_message(
        self,
        proposed: str,
        *,
        patient_message: str,
        next_category: Optional[str],
    ) -> str:
        message = (proposed or "").strip()
        if _DIAGNOSIS_REQUEST.search(patient_message) or _DIAGNOSIS_OUTPUT.search(
            message
        ):
            message = _strip_diagnosis_language(
                message if _DIAGNOSIS_OUTPUT.search(message) else _NON_DIAGNOSIS_PREFIX,
                next_category,
            )
            if not _asks_about(message, next_category or "") and next_category:
                message = _NON_DIAGNOSIS_PREFIX + _QUESTION_TEMPLATES[next_category]

        known_explicit = [
            name
            for name in INTERVIEW_CATEGORIES
            if self.state.patient_information.explicit_value(name)
        ]
        if any(_asks_about(message, name) for name in known_explicit):
            if next_category:
                message = _QUESTION_TEMPLATES[next_category]

        if self.state.patient_information.urgent_symptoms_mentioned:
            lowered = _normalize(message)
            if "clinician" not in lowered and "urgent" not in lowered:
                message = (
                    "That sounds important for a clinician to review promptly. "
                    "I can't diagnose it, but I will record what you describe. "
                    + message
                )

        if not message:
            cc = self.state.patient_information.explicit_value("chief_complaint")
            loc = self.state.patient_information.explicit_value("location")
            ack_prefix = ""
            if cc and loc:
                ack_prefix = f"I have noted your {cc} in your {loc}. "
            elif cc:
                ack_prefix = f"I have recorded that you are having {cc}. "
            elif patient_message:
                clean_msg = patient_message.strip()
                if len(clean_msg) < 40:
                    ack_prefix = f"Understood regarding '{clean_msg}'. "

            if next_category and next_category in _QUESTION_TEMPLATES:
                message = ack_prefix + _QUESTION_TEMPLATES[next_category]
            else:
                message = ack_prefix + "Thank you. Is there anything else you want the clinician to know?"
        return message
