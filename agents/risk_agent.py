"""Hybrid, non-diagnostic safety review for a validated clinical history."""

from __future__ import annotations

import json
import re
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ValidationError

from core.exceptions import LLMConnectionError, LLMResponseError, StructuredOutputError
from core.prompts import RISK_SYSTEM_INSTRUCTION, SAFETY_SYSTEM_INSTRUCTION
from core.schemas import (
    AttentionLevel,
    ClinicalHistory,
    HistoryOfPresentIllness,
    RiskAssessment,
    RiskFlag,
    RiskSeverity,
)
from privacy import PrivacyGateway, PrivacyGatewayError


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


_ALLOWED_CATEGORIES = {
    "urgent_symptom",
    "safety_symptom",
    "missing_information",
    "contradiction",
    "uncertainty",
}

# LLMs sometimes return category names that are semantically equivalent but
# not exactly the controlled strings above. This alias map is the *only*
# normalisation applied before flag validation; it does not widen what the
# downstream validation allows.
_CATEGORY_ALIASES: dict[str, str] = {
    # urgent / red-flag symptom variants
    "urgent": "urgent_symptom",
    "red_flag": "urgent_symptom",
    "red_flag_symptom": "urgent_symptom",
    # safety / general symptom variants
    "symptom": "safety_symptom",
    "symptom_mention": "safety_symptom",
    "safety": "safety_symptom",
    "safety_concern": "safety_symptom",
    "allergy_mention": "safety_symptom",
    "concern": "safety_symptom",
    # missing information variants
    "missing": "missing_information",
    "missing_info": "missing_information",
}
_ATTENTION_ORDER = {
    AttentionLevel.ROUTINE: 0,
    AttentionLevel.ATTENTION: 1,
    AttentionLevel.URGENT: 2,
}
_STOP_WORDS = {
    "and", "the", "with", "were", "was", "reported", "report", "patient",
    "information", "history", "that", "this", "for", "from", "have", "has",
    "been", "are", "not", "may", "could", "should", "review", "clinical",
}
_DIAGNOSTIC_ASSERTION = re.compile(
    r"\b(?:diagnos(?:is|ed)|confirmed|definitely|likely|probably|"
    r"(?:patient|they)\s+(?:has|have|is having)\s+(?:a |an )?"
    r"(?:heart attack|pneumonia|appendicitis|stroke))\b",
    re.IGNORECASE,
)
_MEDICATION_ADVICE = re.compile(
    r"\b(?:stop|start|increase|decrease|change|adjust|switch)\s+"
    r"(?:taking\s+)?(?:your\s+)?(?:medication|medicine|meds|dose|dosage|"
    r"[a-z][a-z-]{2,})\b",
    re.IGNORECASE,
)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        value = value.strip()
        key = _normalise(value)
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


class RiskAgent:
    """Flag reported safety signals; never diagnose or direct treatment.

    Deterministic rules run before contextual LLM analysis. Their flags are
    always retained, so an LLM cannot downgrade a recognizable urgent pattern.
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
        self._system_prompt = f"{SAFETY_SYSTEM_INSTRUCTION}\n\n{RISK_SYSTEM_INSTRUCTION}"

    def assess(self, history: ClinicalHistory | dict[str, Any]) -> RiskAssessment:
        """Return a validated, evidence-grounded clinician-review assessment."""
        if not isinstance(history, ClinicalHistory):
            history = ClinicalHistory.model_validate(history)

        deterministic_flags, indicators = self._deterministic_flags(history)
        relevant_missing = self._relevant_missing(history)
        if self._is_empty(history):
            return RiskAssessment(
                session_id=history.session_id,
                missing_information=relevant_missing,
                uncertainties=["No reported clinical history was available for review."],
            )

        contextual: Optional[RiskAssessment] = None
        try:
            raw = self._generate(self._build_prompt(history))
            contextual = self._validate_or_repair(raw, history)
        except (LLMConnectionError, LLMResponseError):
            # Transient provider outage: fall back to deterministic-only flags so
            # an unreachable LLM never blocks the interview. StructuredOutputError
            # is deliberately NOT caught here - unsafe or unrepairable outputs
            # surface to the orchestrator as a structured-stage failure instead of
            # being silently downgraded to a routine assessment.
            contextual = RiskAssessment(
                session_id=history.session_id,
                risk_flags=[],
                emergency_indicators=[],
                missing_information=[],
                contradictions=[],
                uncertainties=[],
                overall_attention_level=AttentionLevel.ROUTINE,
            )
        final_flags = deterministic_flags + contextual.risk_flags
        final_flags = self._deduplicate_flags(final_flags)
        level = self._attention_level(deterministic_flags, contextual, final_flags)
        return RiskAssessment(
            session_id=history.session_id,
            risk_flags=final_flags,
            emergency_indicators=_unique(indicators + contextual.emergency_indicators),
            missing_information=_unique(relevant_missing + contextual.missing_information),
            contradictions=_unique(list(history.contradictions) + contextual.contradictions),
            uncertainties=_unique(self._base_uncertainties(history) + contextual.uncertainties),
            overall_attention_level=level,
            diagnosis=None,
        )

    analyze = assess
    assess_risk = assess

    def _generate(self, prompt: str) -> Any:
        try:
            safe_prompt = self._privacy_gateway.prepare(
                prompt, source_type="risk"
            ).safe_text
        except PrivacyGatewayError as exc:
            raise StructuredOutputError("PRIVACY_GATEWAY_BLOCKED") from exc
        return self._llm.generate_json(
            safe_prompt,
            schema=RiskAssessment,
            system_instruction=self._system_prompt,
            temperature=self._temperature,
        )

    def _validate_or_repair(self, raw: Any, history: ClinicalHistory) -> RiskAssessment:
        try:
            return self._validate_context(raw, history)
        except (ValidationError, StructuredOutputError, TypeError, ValueError) as first:
            repair = self._repair_prompt(history, raw, first)
            try:
                return self._validate_context(self._generate(repair), history)
            except Exception as second:
                raise StructuredOutputError(
                    "Risk analysis output could not be repaired and safely validated."
                ) from second

    def _validate_context(self, raw: Any, history: ClinicalHistory) -> RiskAssessment:
        # A diagnosis-bearing dictionary is neutralized before model validation;
        # no diagnosis-bearing value can ever reach the final assessment.
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict):
            raw = dict(raw)
            if raw.get("diagnosis") is not None:
                raw["diagnosis"] = None
            # Normalise flag list before Pydantic coercion so that alias
            # category strings and alternative key names (e.g. "type" instead
            # of "category") are resolved to controlled values.
            if isinstance(raw.get("risk_flags"), list):
                normalised: list[dict[str, Any]] = []
                for item in raw["risk_flags"]:
                    if isinstance(item, dict):
                        item = dict(item)
                        # Some models emit "type" instead of "category".
                        if "category" not in item and "type" in item:
                            item["category"] = item.pop("type")
                        cat = str(item.get("category", "")).strip().lower()
                        if cat in _CATEGORY_ALIASES:
                            item["category"] = _CATEGORY_ALIASES[cat]
                    normalised.append(item)
                raw["risk_flags"] = normalised
        if not isinstance(raw, RiskAssessment):
            if not isinstance(raw, dict):
                raise TypeError("Risk analysis output must be a JSON object.")
            raw = RiskAssessment.model_validate(raw)
        if raw.diagnosis is not None:
            raise StructuredOutputError("Risk assessment must not contain a diagnosis.")

        source_terms = self._source_terms(history)
        # The LLM is permitted to echo back the full upstream missing-information
        # list. _relevant_missing is a filtered subset used for display, not an
        # exclusive whitelist for the LLM output.
        allowed_missing = (
            set(self._relevant_missing(history))
            | set(history.missing_information)
            | set(history.unknown_information)
        )
        for flag in raw.risk_flags:
            # Apply alias normalisation to already-validated RiskFlag objects
            # (needed when raw was already a RiskAssessment coming in).
            cat_key = str(flag.category).strip().lower()
            if cat_key in _CATEGORY_ALIASES:
                flag.category = _CATEGORY_ALIASES[cat_key]
            self._validate_flag(flag, source_terms)
            flag.for_clinician_review_only = True
        if any(item not in allowed_missing for item in raw.missing_information):
            raise StructuredOutputError("Risk output included unsupported missing information.")
        if any(item not in history.contradictions for item in raw.contradictions):
            raise StructuredOutputError("Risk output included an unsupported contradiction.")
        for text in raw.uncertainties + raw.emergency_indicators:
            self._validate_safe_text(text)
            if not self._text_has_source_term(text, source_terms):
                raise StructuredOutputError("Risk output included unsupported contextual text.")
        raw.for_clinician_review_only = True
        return raw

    def _validate_flag(self, flag: RiskFlag, source_terms: set[str]) -> None:
        if flag.category not in _ALLOWED_CATEGORIES:
            raise StructuredOutputError("Risk flag category is not controlled.")
        if not flag.evidence or not flag.evidence.strip():
            raise StructuredOutputError("Every risk flag requires evidence.")
        for text in (flag.description, flag.reason or "", flag.evidence, flag.recommended_clinician_check or ""):
            self._validate_safe_text(text)
        if not self._text_has_source_term(flag.evidence, source_terms):
            raise StructuredOutputError("Risk flag evidence is not grounded in the supplied history.")

    @staticmethod
    def _validate_safe_text(text: str) -> None:
        if _DIAGNOSTIC_ASSERTION.search(text):
            raise StructuredOutputError("Risk output contains prohibited diagnostic wording.")
        if _MEDICATION_ADVICE.search(text):
            raise StructuredOutputError("Risk output contains prohibited medication advice.")

    @staticmethod
    def _text_has_source_term(text: str, source_terms: set[str]) -> bool:
        terms = {
            term for term in re.findall(r"[a-z0-9]+", _normalise(text))
            if len(term) > 2 and term not in _STOP_WORDS
        }
        return bool(terms & source_terms)

    def _build_prompt(self, history: ClinicalHistory) -> str:
        # Session linkage is application-side metadata and has no role in a
        # contextual safety review.
        minimized_history = history.model_dump(exclude={"session_id"})
        return (
            "Review this validated structured history and return a RiskAssessment JSON "
            "object. The deterministic rule layer has separate authority, so do not "
            "assume you may remove its flags. Every proposed flag requires evidence "
            "from the history.\n\nStructured history:\n"
            f"{json.dumps(minimized_history, indent=2, default=str)}"
        )

    def _repair_prompt(self, history: ClinicalHistory, raw: Any, error: Exception) -> str:
        return (
            "Repair the prior RiskAssessment JSON. Remove diagnosis, medication "
            "advice, unsupported flags, and flags without evidence. Use only the "
            "structured history as source.\n"
            f"Validation error: {error}\nAttempted output: {json.dumps(raw, default=str)}\n\n"
            + self._build_prompt(history)
        )

    def _deterministic_flags(self, history: ClinicalHistory) -> tuple[list[RiskFlag], list[str]]:
        texts = self._reported_texts(history)
        blob = _normalise(" ".join(texts))
        flags: list[RiskFlag] = []
        indicators: list[str] = []

        def add(indicator: str, terms: tuple[str, ...], description: str) -> None:
            evidence = self._evidence_for(texts, terms)
            if not evidence:
                return
            flags.append(RiskFlag(
                category="urgent_symptom",
                description=description,
                severity=RiskSeverity.HIGH,
                evidence=evidence,
                reason="The reported symptom pattern warrants prompt clinical assessment.",
                requires_clinician_review=True,
                recommended_clinician_check="Prompt clinician assessment of the reported symptoms.",
            ))
            indicators.append(indicator)

        chest = "chest pain" in blob
        breathlessness = any(item in blob for item in ("breathless", "shortness of breath", "difficulty breathing"))
        if chest and breathlessness:
            add("reported_chest_pain_with_breathlessness", ("chest pain", "breath"), "Chest pain with reported breathlessness is an urgent symptom combination for clinician review.")
        if any(item in blob for item in ("can't breathe", "cannot breathe", "severe difficulty breathing", "severe shortness of breath")):
            add("reported_severe_breathing_difficulty", ("breathe", "breath"), "Reported severe breathing difficulty warrants prompt clinician review.")
        if any(item in blob for item in ("loss of consciousness", "passed out", "fainted", "unconscious")):
            add("reported_loss_of_consciousness", ("conscious", "passed out", "fainted", "unconscious"), "Reported loss of consciousness warrants prompt clinician review.")
        if "bleeding" in blob and any(item in blob for item in ("severe", "uncontrolled", "won't stop", "will not stop")):
            add("reported_severe_bleeding", ("bleeding",), "Reported severe or uncontrolled bleeding warrants prompt clinician review.")
        neurological = any(item in blob for item in ("weakness", "numbness", "slurred speech", "confusion", "vision loss"))
        if "sudden" in blob and neurological:
            add("reported_sudden_neurological_symptoms", ("sudden",), "Reported sudden neurological symptoms warrant prompt clinician review.")
        return flags, indicators

    @staticmethod
    def _evidence_for(texts: list[str], terms: tuple[str, ...]) -> Optional[str]:
        selected = [text for text in texts if any(term in _normalise(text) for term in terms)]
        return "; ".join(selected) if selected else None

    def _reported_texts(self, history: ClinicalHistory) -> list[str]:
        values: list[str] = []
        if history.chief_complaint:
            values.append(history.chief_complaint)
        values.extend(history.associated_symptoms or history.reported_symptoms)
        values.extend(history.patient_reported_concerns)
        hpi = history.history_of_present_illness
        if isinstance(hpi, HistoryOfPresentIllness):
            values.extend(str(value) for value in hpi.model_dump().values() if value is not None)
        return values

    def _source_terms(self, history: ClinicalHistory) -> set[str]:
        source = self._reported_texts(history)
        source.extend(
            history.past_medical_history
            + history.family_history
            + (history.allergies or history.reported_allergies)
        )
        source.extend(
            m.name_as_reported
            for m in (history.medications or history.reported_medications)
        )
        source.extend(history.unknown_information + history.missing_information + history.contradictions)
        return {
            term for term in re.findall(r"[a-z0-9]+", _normalise(" ".join(source)))
            if len(term) > 2 and term not in _STOP_WORDS
        }

    def _relevant_missing(self, history: ClinicalHistory) -> list[str]:
        missing = set(history.unknown_information or history.missing_information)
        if not history.chief_complaint:
            return ["chief_complaint"]
        hpi = history.history_of_present_illness
        hpi_missing = {"duration", "severity", "associated_symptoms"}
        if isinstance(hpi, HistoryOfPresentIllness):
            if hpi.duration is not None:
                hpi_missing.discard("duration")
            if hpi.severity is not None:
                hpi_missing.discard("severity")
        relevant = [name for name in ("duration", "severity", "associated_symptoms", "allergies", "medications") if name in missing or name in hpi_missing]
        return _unique(relevant)

    def _base_uncertainties(self, history: ClinicalHistory) -> list[str]:
        return list(history.patient_reported_concerns)

    @staticmethod
    def _is_empty(history: ClinicalHistory) -> bool:
        return not any((
            history.chief_complaint,
            history.associated_symptoms,
            history.reported_symptoms,
            history.patient_reported_concerns,
            history.past_medical_history,
            history.medications or history.reported_medications,
            history.allergies or history.reported_allergies,
        ))

    @staticmethod
    def _deduplicate_flags(flags: list[RiskFlag]) -> list[RiskFlag]:
        result: list[RiskFlag] = []
        seen: set[tuple[str, str]] = set()
        for flag in flags:
            key = (flag.category, _normalise(flag.evidence or flag.description))
            if key not in seen:
                seen.add(key)
                result.append(flag)
        return result

    @staticmethod
    def _attention_level(
        deterministic: list[RiskFlag], contextual: RiskAssessment, all_flags: list[RiskFlag]
    ) -> AttentionLevel:
        level = contextual.overall_attention_level
        if any(flag.severity == RiskSeverity.HIGH for flag in all_flags):
            level = AttentionLevel.URGENT
        elif any(flag.severity == RiskSeverity.MODERATE for flag in all_flags):
            level = max(level, AttentionLevel.ATTENTION, key=lambda item: _ATTENTION_ORDER[item])
        if deterministic:
            level = AttentionLevel.URGENT
        return level
