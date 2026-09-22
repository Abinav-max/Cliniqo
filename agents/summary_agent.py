"""Physician-facing summary generation from validated upstream agent outputs."""

from __future__ import annotations

import json
import re
from typing import Any, Optional, Protocol, runtime_checkable

from pydantic import BaseModel, ConfigDict, ValidationError

from core.exceptions import LLMConnectionError, LLMResponseError, StructuredOutputError
from core.prompts import SAFETY_SYSTEM_INSTRUCTION, SUMMARY_SYSTEM_INSTRUCTION
from core.schemas import (
    AttentionLevel,
    ClinicalHistory,
    DocumentExtraction,
    HistoryOfPresentIllness,
    PhysicianSummary,
    RiskAssessment,
    SummaryInput,
    SummarySourceType,
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


class SummarySelection(BaseModel):
    """Provider output limited to IDs of validated, renderable source facts.

    The final summary is rendered deterministically from those fact IDs. The
    model therefore cannot introduce free-form clinical claims or provenance.
    """

    model_config = ConfigDict(extra="forbid")

    fact_ids: list[str]


_ATTENTION_ORDER = {
    AttentionLevel.ROUTINE: 0,
    AttentionLevel.ATTENTION: 1,
    AttentionLevel.URGENT: 2,
}
_SAFE_WORDS = {
    "chief", "complaint", "history", "reported", "document", "uploaded",
    "record", "records", "review", "clinician", "information", "missing",
    "uncertain", "extraction", "patient", "concern", "concerns", "with",
    "and", "for", "of", "the", "a", "an", "in", "on", "to", "is",
    "was", "were", "from", "by", "only", "status", "attention", "urgent",
    "routine", "safety", "flag", "flags", "follow", "up", "summary",
    # Non-clinical connective language is allowed. Clinical terms still have to
    # be present in validated upstream input, so this is not a hallucination
    # bypass for symptoms, diagnoses, medications, allergies, or laboratory data.
    "reports", "reporting", "presents", "presentation", "noted", "notes",
    "states", "experiencing", "experiences", "currently", "also", "including",
    "regarding", "based", "available", "provided", "listed", "details",
    "findings", "level", "items", "requires", "assessment", "reviewed",
    "reviewing", "needs", "need", "consider", "whether", "what", "when",
    "where", "how", "please", "further", "clarify", "clarification",
    "verify", "verification", "possible", "duration", "severity", "symptoms",
    "associated",
}
_DIAGNOSIS_ASSERTION = re.compile(
    r"\b(?:diagnos(?:is|ed)|(?:patient|they)\s+(?:has|have|is having)\s+"
    r"(?:a |an )?(?:heart attack|myocardial infarction|pneumonia|appendicitis|"
    r"stroke|diabetes))\b",
    re.IGNORECASE,
)
_MEDICATION_ADVICE = re.compile(
    r"\b(?:start|stop|continue|increase|decrease|change|adjust|switch)\s+"
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
        key = _normalise(value)
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result


class SummaryAgent:
    """Produce a concise, source-attributed physician summary without new facts."""

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
        self._system_prompt = f"{SAFETY_SYSTEM_INSTRUCTION}\n\n{SUMMARY_SYSTEM_INSTRUCTION}"

    def summarize(
        self,
        clinical_history: SummaryInput | ClinicalHistory | dict[str, Any] | None = None,
        risk_assessment: Optional[RiskAssessment] = None,
        document_extractions: Optional[list[DocumentExtraction]] = None,
        *,
        patient_conversation: Optional[list[str]] = None,
        ayush_assessment: Any = None,
    ) -> PhysicianSummary:
        """Summarize validated upstream outputs; no application orchestrator needed."""
        payload = self._coerce_input(
            clinical_history, risk_assessment, document_extractions, patient_conversation, ayush_assessment
        )
        if self._is_empty(payload):
            return PhysicianSummary(
                overview="No validated clinical, risk, or document information was available for summary.",
            )
        generated: Optional[PhysicianSummary] = None
        try:
            raw = self._generate(self._build_prompt(payload))
            generated = self._validate_or_repair(raw, payload)
        except Exception:
            generated = self._build_grounded_fallback_summary(payload)
        return self._compose(payload, generated)

    def _build_grounded_fallback_summary(self, payload: SummaryInput) -> PhysicianSummary:
        ch = payload.clinical_history
        risk = payload.risk_assessment
        parts = []
        highlights = []
        gaps = []
        clinician_questions = []
        
        is_generic_word = lambda w: not w or str(w).strip().lower() in (
            'clinical evaluation', 'not specified', 'general intake', 'unknown', 'none', 'nothing', 'intake', 'no symptoms recorded yet', 'clinical assessment', 'nil', 'n/a', 'no chronic conditions recorded'
        )

        def _clean_symptom(text: str | None) -> str:
            if not text or is_generic_word(text):
                return ""
            cleaned = str(text).strip()
            cleaned = re.sub(r'^[“"\'\s]+|[”"\'\s]+$', '', cleaned)
            cleaned = re.sub(r'^(?:I(?:\'ve| have)?(?: been experiencing| got| had| am having| am experiencing| feel| felt| have)?|Patient (?:has|is complaining of|presents with)|Suffering from|Complaining of|Experiencing)\s+', '', cleaned, flags=re.IGNORECASE)
            return cleaned.strip()

        if ch:
            raw_chief = ch.chief_complaint or ch.chief_concern or (ch.reported_symptoms[0] if ch.reported_symptoms else None)
            chief = _clean_symptom(raw_chief)
            hpi = ch.history_of_present_illness
            dur = getattr(hpi, 'duration', None) if hpi else None
            loc = getattr(hpi, 'location', None) if hpi else None
            qual = getattr(hpi, 'quality', None) if hpi else None
            
            is_generic_chief = is_generic_word(chief)
            has_valid_dur = bool(dur and str(dur).strip().lower() not in ('recorded on intake', 'unknown', 'none', '', 'recorded today'))

            if not is_generic_chief and chief:
                chief_desc = f"Patient presents for clinical evaluation of {chief}"
                if has_valid_dur:
                    chief_desc += f" with duration of {dur}"
                if loc and not is_generic_word(loc):
                    chief_desc += f", localized to {loc}"
                if qual and not is_generic_word(qual):
                    chief_desc += f" ({qual})"
                parts.append(chief_desc + ".")
                highlights.append(f"Chief Concern: {chief}" + (f" ({dur})" if has_valid_dur else ""))
            else:
                parts.append("Patient presents for routine clinical intake assessment and health profile review.")

            all_symptoms = [s for s in (ch.reported_symptoms or []) if not is_generic_word(s)]
            for sym in (ch.associated_symptoms or []):
                if not is_generic_word(sym) and sym not in all_symptoms and sym != chief:
                    all_symptoms.append(sym)
            if all_symptoms and len(all_symptoms) > 1:
                highlights.append(f"Associated Symptoms: {', '.join(all_symptoms)}")

            filtered_pmh = [c for c in (ch.past_medical_history or []) if not is_generic_word(c)]
            if filtered_pmh:
                med_hist_str = ", ".join(filtered_pmh)
                parts.append(f"Medical history is notable for {med_hist_str}.")
                highlights.append(f"Documented Medical History: {med_hist_str}")
                clinician_questions.append(f"Review ongoing care and management plan for {med_hist_str}.")
            
            meds = [m.name_as_reported for m in (ch.medications or ch.reported_medications or []) if getattr(m, 'name_as_reported', None) and not is_generic_word(getattr(m, 'name_as_reported'))]
            if meds:
                parts.append(f"Active medications: {', '.join(meds)}.")
                highlights.append(f"Active Medications: {', '.join(meds)}")
                clinician_questions.append("Reconcile current medication schedule and check for drug-drug interactions.")
            
            allergies = [a for a in (ch.allergies or ch.reported_allergies or []) if not is_generic_word(a)]
            if allergies:
                parts.append(f"Allergy flags: {', '.join(allergies)}.")
                highlights.append(f"Allergy Alert: {', '.join(allergies)}")

        if payload.ayush_assessment:
            ay = payload.ayush_assessment
            ay_fields = [
                ("Prakriti", ay.prakriti), ("Vikriti", ay.vikriti), ("Sara", ay.sara),
                ("Samhanana", ay.samhanana), ("Pramana", ay.pramana), ("Satmya", ay.satmya),
                ("Sattva", ay.sattva), ("Ahara Shakti", ay.ahara_shakti),
                ("Vyayama Shakti", ay.vyayama_shakti), ("Vaya", ay.vaya)
            ]
            for name, value in ay_fields:
                if value:
                    highlights.append(f"AYUSH {name}: {value}")
            if ay.ahara_vihara:
                narrative = ay.ahara_vihara.get("narrative") if isinstance(ay.ahara_vihara, dict) else str(ay.ahara_vihara)
                if narrative:
                    highlights.append(f"AYUSH Ahara-Vihara: {narrative}")

        # Document Extractions & Vault Findings
        if payload.document_extractions:
            doc_count = len(payload.document_extractions)
            doc_types = list(dict.fromkeys(d.document_type for d in payload.document_extractions if d.document_type))
            type_str = f" ({', '.join(doc_types)})" if doc_types else ""
            parts.append(f"Health vault contains {doc_count} verified scanned clinical document(s){type_str}.")
            highlights.append(f"Attached Records: {doc_count} verified document(s){type_str}")

            for d in payload.document_extractions:
                if d.medications:
                    for dm in d.medications:
                        m_name = getattr(dm, 'name_as_reported', None) or getattr(dm, 'name', None)
                        if m_name and not is_generic_word(m_name) and not any(m_name.lower() in h.lower() for h in highlights):
                            highlights.append(f"Prescription Record: {m_name}")
                if d.lab_results:
                    for lr in d.lab_results:
                        t_name = getattr(lr, 'test_name', None) or getattr(lr, 'name', None)
                        val = getattr(lr, 'value_as_reported', None) or getattr(lr, 'value', None)
                        unit = getattr(lr, 'unit_as_reported', None) or getattr(lr, 'unit', '') or ''
                        if t_name and val:
                            highlights.append(f"Lab Finding: {t_name} = {val} {unit}".strip())
        
        if risk and risk.risk_flags:
            for rf in risk.risk_flags:
                if getattr(rf, 'description', None):
                    gaps.append(f"Safety review: {rf.description}")
        
        if not is_generic_chief:
            clinician_questions.append("Correlate reported symptom timeline with physical examination findings.")
        else:
            clinician_questions.append("Conduct comprehensive baseline health examination and vital signs review.")
        
        overview_text = " ".join(parts) if parts else "Clinical intake synthesized from verified patient health facts."
        att_level = self._required_attention(risk)
        
        return PhysicianSummary(
            overview=overview_text,
            structured_history_highlights=_unique(highlights),
            questions_for_clinician=_unique(clinician_questions),
            information_gaps=_unique(gaps),
            overall_attention_level=att_level,
            for_clinician_review_only=True
        )

    generate = summarize
    create_summary = summarize

    @staticmethod
    def _coerce_input(
        first: SummaryInput | ClinicalHistory | dict[str, Any] | None,
        risk: Optional[RiskAssessment],
        documents: Optional[list[DocumentExtraction]],
        conversation: Optional[list[str]],
        ayush_assessment: Any = None,
    ) -> SummaryInput:
        if isinstance(first, SummaryInput):
            return first
        if isinstance(first, dict) and any(
            key in first for key in ("clinical_history", "risk_assessment", "document_extractions")
        ):
            return SummaryInput.model_validate(first)
        if first is not None and not isinstance(first, ClinicalHistory):
            first = ClinicalHistory.model_validate(first)
        return SummaryInput(
            clinical_history=first,
            risk_assessment=risk,
            document_extractions=documents or [],
            patient_conversation=conversation or [],
            ayush_assessment=ayush_assessment,
        )

    def _generate(self, prompt: str) -> Any:
        try:
            safe_prompt = self._privacy_gateway.prepare(
                prompt, source_type="summary"
            ).safe_text
        except PrivacyGatewayError as exc:
            raise StructuredOutputError("PRIVACY_GATEWAY_BLOCKED") from exc
        return self._llm.generate_json(
            safe_prompt,
            schema=SummarySelection,
            system_instruction=self._system_prompt,
            temperature=self._temperature,
        )

    def _validate_or_repair(self, raw: Any, payload: SummaryInput) -> PhysicianSummary:
        try:
            return self._validate(raw, payload)
        except (ValidationError, StructuredOutputError, TypeError, ValueError) as first:
            try:
                return self._validate(self._generate(self._repair_prompt(payload, raw, first)), payload)
            except Exception as second:
                raise StructuredOutputError(
                    "Physician summary output could not be repaired and safely validated."
                ) from second

    def _validate(self, raw: Any, payload: SummaryInput) -> PhysicianSummary:
        if isinstance(raw, str):
            raw = json.loads(raw)
        if isinstance(raw, dict) and "fact_ids" in raw:
            raw = SummarySelection.model_validate(raw)
        if isinstance(raw, SummarySelection):
            catalog = self._fact_catalog(payload)
            if not raw.fact_ids or any(fact_id not in catalog for fact_id in raw.fact_ids):
                raise StructuredOutputError("Summary output contains an unsupported evidence reference.")
            raw = PhysicianSummary(
                overview=" ".join(_unique([catalog[fact_id] for fact_id in raw.fact_ids])),
                overall_attention_level=self._required_attention(payload.risk_assessment),
            )
        if not isinstance(raw, PhysicianSummary):
            if not isinstance(raw, dict):
                raise TypeError("Physician summary output must be a JSON object.")
            raw = PhysicianSummary.model_validate(raw)

        required_level = self._required_attention(payload.risk_assessment)
        if _ATTENTION_ORDER[raw.overall_attention_level] < _ATTENTION_ORDER[required_level]:
            raise StructuredOutputError("Summary output downgraded the upstream risk attention level.")

        allowed_terms = self._source_terms(payload)
        all_text = [raw.overview]
        for field in (
            "structured_history_highlights", "safety_items_to_review", "information_gaps",
            "questions_for_clinician", "document_derived_findings", "contradictions",
            "patient_reported_concerns", "uncertainties",
        ):
            all_text.extend(getattr(raw, field))
        for text in all_text:
            self._validate_text(text, allowed_terms, payload)
        # Pydantic must have coerced every model-provided provenance label into
        # the closed enum. We never rewrite an invalid provider label.
        if any(not isinstance(source, SummarySourceType) for source in raw.source_evidence.values()):
            raise StructuredOutputError("Summary output contains unsupported source provenance.")
        for fact_id, source in raw.source_evidence.items():
            text = self._summary_text_for_fact_id(raw, fact_id)
            if text is None:
                raise StructuredOutputError("Summary output contains an unsupported evidence reference.")
            self._validate_text(text, self._source_terms_for_category(payload, source), payload)
        raw.for_clinician_review_only = True
        return raw

    @staticmethod
    def _summary_text_for_fact_id(summary: PhysicianSummary, fact_id: str) -> Optional[str]:
        """Resolve only stable, field-level IDs emitted by the summary schema."""
        if fact_id == "overview":
            return summary.overview
        field, separator, index_text = fact_id.rpartition(".")
        if not separator or not index_text.isdigit():
            return None
        values = getattr(summary, field, None)
        index = int(index_text)
        if not isinstance(values, list) or index >= len(values):
            return None
        value = values[index]
        return value if isinstance(value, str) else None

    @staticmethod
    def _source_terms_for_category(payload: SummaryInput, source: SummarySourceType) -> set[str]:
        if source is SummarySourceType.CLINICAL_HISTORY and payload.clinical_history:
            value: Any = payload.clinical_history.model_dump()
        elif source is SummarySourceType.RISK_ASSESSMENT and payload.risk_assessment:
            value = payload.risk_assessment.model_dump()
        elif source is SummarySourceType.DOCUMENT:
            value = [document.model_dump() for document in payload.document_extractions]
        elif source is SummarySourceType.PATIENT_CONVERSATION:
            value = payload.patient_conversation
        else:
            return set()
        return set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", _normalise(json.dumps(value, default=str))))

    def _validate_text(self, text: str, allowed_terms: set[str], payload: SummaryInput) -> None:
        lowered = _normalise(text)
        if _MEDICATION_ADVICE.search(text):
            raise StructuredOutputError("Summary output contains prohibited medication advice.")
        if _DIAGNOSIS_ASSERTION.search(text):
            # Document diagnosis mentions require clear document attribution.
            if not ("diagnosis mentioned in uploaded document" in lowered and self._has_document_diagnosis(payload, text)):
                raise StructuredOutputError("Summary output contains an unsupported diagnosis.")
        if "no known allergies" in lowered and not self._has_explicit_no_allergy(payload):
            raise StructuredOutputError("Summary output invented allergy status.")
        tokens = {
            token for token in re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", lowered)
            if len(token) > 1 and token not in _SAFE_WORDS
        }
        if any(token not in allowed_terms for token in tokens):
            raise StructuredOutputError("Summary output contains unsupported facts.")

    def _build_prompt(self, payload: SummaryInput) -> str:
        # History/risk/document outputs are the summary model's required facts.
        # The raw transcript is intentionally excluded to avoid a duplicate,
        # higher-risk disclosure; it remains application-side for validation.
        minimized_payload = payload.model_dump()
        minimized_payload["patient_conversation"] = []
        if minimized_payload.get("clinical_history"):
            minimized_payload["clinical_history"]["session_id"] = None
        if minimized_payload.get("risk_assessment"):
            minimized_payload["risk_assessment"]["session_id"] = None
        for document in minimized_payload.get("document_extractions", []):
            document["document_id"] = None
        catalog = self._fact_catalog(payload)
        return (
            "Select validated facts for a concise clinician-review overview. "
            "Return only SummarySelection JSON with fact_ids, choosing only IDs "
            "from Allowed facts. Do not write summary prose, diagnoses, advice, "
            "or source labels. Include every relevant selected fact.\n\n"
            f"Allowed facts:\n{json.dumps(catalog, indent=2, default=str)}\n\n"
            f"Validated inputs:\n{json.dumps(minimized_payload, indent=2, default=str)}"
        )

    def _repair_prompt(self, payload: SummaryInput, raw: Any, error: Exception) -> str:
        return (
            "Repair the previous SummarySelection JSON. Return only valid fact_ids "
            "from Allowed facts. Do not add prose, diagnoses, advice, provenance, "
            "or facts.\n"
            f"Validation error: {error}\nAttempted output: {json.dumps(raw, default=str)}\n\n"
            + self._build_prompt(payload)
        )

    def _fact_catalog(self, payload: SummaryInput) -> dict[str, str]:
        """Return deterministic summary-ready text keyed by stable fact IDs."""
        catalog: dict[str, str] = {}
        history, risk = payload.clinical_history, payload.risk_assessment
        if history:
            history_lines, _ = self._history_lines(history)
            for index, line in enumerate(history_lines):
                catalog[f"clinical_history.{index}"] = line
            for index, value in enumerate(history.patient_reported_concerns):
                catalog[f"clinical_history.concern.{index}"] = value
        if risk:
            for index, flag in enumerate(risk.risk_flags):
                line = f"{risk.overall_attention_level.value.title()} review: {flag.description}"
                if flag.evidence:
                    line += f" Evidence: {flag.evidence}"
                catalog[f"risk_assessment.{index}"] = line
        for document_index, document in enumerate(payload.document_extractions):
            lines, _, _ = self._document_lines(document, document_index)
            for line_index, line in enumerate(lines):
                catalog[f"document.{document_index}.{line_index}"] = line
        return catalog

    def _compose(self, payload: SummaryInput, generated: PhysicianSummary) -> PhysicianSummary:
        history, risk, documents = payload.clinical_history, payload.risk_assessment, payload.document_extractions
        highlights, docs, safety, gaps, contradictions, concerns, uncertainties = [], [], [], [], [], [], []
        evidence: dict[str, str] = {}

        if history:
            highlights, history_evidence = self._history_lines(history)
            evidence.update(history_evidence)
            gaps.extend(history.missing_information or history.unknown_information)
            contradictions.extend(history.contradictions)
            concerns.extend(history.patient_reported_concerns)
        for index, document in enumerate(documents):
            lines, document_evidence, uncertain = self._document_lines(document, index)
            docs.extend(lines)
            evidence.update(document_evidence)
            uncertainties.extend(uncertain)
        if risk:
            for index, flag in enumerate(risk.risk_flags):
                line = f"{risk.overall_attention_level.value.title()} review: {flag.description}"
                if flag.evidence:
                    line += f" Evidence: {flag.evidence}"
                safety.append(line)
                evidence[f"safety_items_to_review.{index}"] = SummarySourceType.RISK_ASSESSMENT
            gaps.extend(risk.missing_information)
            contradictions.extend(risk.contradictions)
            uncertainties.extend(risk.uncertainties)

        # The LLM may add only text that survived validation; deterministic lines
        # ensure upstream flags, contradictions, and source labels cannot vanish.
        highlights = _unique(highlights + generated.structured_history_highlights)
        docs = _unique(docs + generated.document_derived_findings)
        safety = _unique(safety + generated.safety_items_to_review)
        gaps = _unique(gaps + generated.information_gaps)
        contradictions = _unique(contradictions + generated.contradictions)
        concerns = _unique(concerns + generated.patient_reported_concerns)
        uncertainties = _unique(uncertainties + generated.uncertainties)
        evidence.update(generated.source_evidence)
        for index, line in enumerate(highlights):
            evidence.setdefault(f"structured_history_highlights.{index}", SummarySourceType.CLINICAL_HISTORY)
        for index, line in enumerate(docs):
            evidence.setdefault(f"document_derived_findings.{index}", SummarySourceType.DOCUMENT)
        for index, line in enumerate(safety):
            evidence.setdefault(f"safety_items_to_review.{index}", SummarySourceType.RISK_ASSESSMENT)
        for index, line in enumerate(concerns):
            evidence.setdefault(f"patient_reported_concerns.{index}", SummarySourceType.CLINICAL_HISTORY)

        session_id = history.session_id if history else (risk.session_id if risk else None)
        clinician_questions = _unique(generated.questions_for_clinician)
        if not clinician_questions:
            if gaps:
                clinician_questions.extend(gaps)
            elif history:
                if history.past_medical_history:
                    clinician_questions.append(f"Review ongoing care and management for {', '.join(history.past_medical_history)}.")
                if history.medications or history.reported_medications:
                    clinician_questions.append("Reconcile active medication dosages, schedule, and adherence.")
                clinician_questions.append("Correlate reported symptom timeline with physical examination findings.")

        return PhysicianSummary(
            session_id=session_id,
            overview=generated.overview,
            structured_history_highlights=highlights,
            safety_items_to_review=safety,
            information_gaps=gaps,
            questions_for_clinician=clinician_questions,
            document_derived_findings=docs,
            contradictions=contradictions,
            patient_reported_concerns=concerns,
            uncertainties=uncertainties,
            overall_attention_level=self._required_attention(risk),
            source_evidence=evidence,
        )

    @staticmethod
    def _history_lines(history: ClinicalHistory) -> tuple[list[str], dict[str, str]]:
        lines, evidence = [], {}
        is_generic = lambda w: not w or str(w).strip().lower() in (
            'clinical evaluation', 'not specified', 'general intake', '', 'intake', 'unknown', 'none', 'nothing', 'no symptoms recorded yet', 'clinical assessment', 'nil', 'n/a', 'no chronic conditions recorded'
        )

        if history.chief_complaint and not is_generic(history.chief_complaint):
            hpi = history.history_of_present_illness
            dur = getattr(hpi, 'duration', None) if isinstance(hpi, HistoryOfPresentIllness) else None
            has_valid_dur = bool(dur and str(dur).strip().lower() not in ('recorded on intake', 'unknown', 'none', '', 'recorded today'))
            line = f"Primary Concern: {history.chief_complaint}" + (f" ({dur})" if has_valid_dur else "") + "."
            lines.append(line)
            evidence["structured_history_highlights.0"] = SummarySourceType.CLINICAL_HISTORY

        hpi = history.history_of_present_illness
        if isinstance(hpi, HistoryOfPresentIllness):
            parts = []
            if hpi.location and not is_generic(hpi.location): parts.append(f"location {hpi.location}")
            if hpi.quality and not is_generic(hpi.quality): parts.append(hpi.quality)
            if hpi.severity is not None:
                rendered_severity = (
                    f"{hpi.severity}/10" if isinstance(hpi.severity, int) else hpi.severity
                )
                parts.append(f"severity {rendered_severity}")
            valid_assoc = [s for s in (history.associated_symptoms or []) if not is_generic(s)]
            if valid_assoc: parts.append("associated symptoms: " + ", ".join(valid_assoc))
            if parts:
                lines.append("History of present illness: " + "; ".join(parts) + ".")

        filtered_pmh = [c for c in (history.past_medical_history or []) if not is_generic(c)]
        if filtered_pmh:
            lines.append("Past medical history: " + ", ".join(filtered_pmh) + ".")

        meds = history.medications or history.reported_medications
        if meds:
            valid_meds = [m for m in meds if getattr(m, 'name_as_reported', None) and not is_generic(getattr(m, 'name_as_reported'))]
            if valid_meds:
                lines.append("Patient-reported medications: " + ", ".join(_format_medication(m) for m in valid_meds) + ".")

        allergies = history.allergies or history.reported_allergies
        if allergies:
            valid_allergies = [a for a in allergies if not is_generic(a)]
            if valid_allergies:
                lines.append("Patient-reported allergies: " + ", ".join(valid_allergies) + ".")

        if history.family_history:
            valid_fam = [f for f in history.family_history if not is_generic(f)]
            if valid_fam:
                lines.append("Family history: " + ", ".join(valid_fam) + ".")

        if history.social_history and not is_generic(history.social_history):
            lines.append("Personal/social history: " + history.social_history + ".")
        if history.previous_investigations:
            valid_inv = [i for i in history.previous_investigations if not is_generic(i)]
            if valid_inv:
                lines.append("Previous investigations: " + ", ".join(valid_inv) + ".")
        return lines, evidence

    @staticmethod
    def _document_lines(document: DocumentExtraction, index: int) -> tuple[list[str], dict[str, str], list[str]]:
        label = f"document {document.document_id}" if document.document_id else "uploaded document"
        lines, evidence, uncertain = [], {}, []
        temporal = document.temporal_status or document.document_classification or "unknown"
        date_note = f" on {document.document_date}" if document.document_date else " (medical date unknown)"
        context_note = f" [{temporal}{date_note}]"
        for medication in document.medications:
            line = f"{label.title()} documents medication: {_format_medication(medication)}{context_note}. Current use is not implied by this document."
            if medication.uncertain: line += " Extraction uncertainty noted."
            lines.append(line)
        for lab in document.lab_results:
            value = " ".join(part for part in (lab.value_as_reported, lab.unit_as_reported) if part)
            line = f"{label.title()} documents {lab.test_name}{context_note}" + (f" of {value}." if value else ".")
            if lab.uncertain: line += " Extraction uncertainty noted."
            lines.append(line)
        for diagnosis in document.diagnoses_mentioned:
            lines.append(f"Diagnosis mentioned in uploaded document [{temporal}{date_note}]: {diagnosis.text}.")
            if diagnosis.uncertain: uncertain.append(f"Document diagnosis extraction uncertain: {diagnosis.text}.")
        for item in document.follow_up_instructions:
            lines.append(f"Uploaded document follow-up instruction: {item.text}.")
        for item in document.unknown_or_unclear:
            uncertain.append(f"Document extraction uncertain: {item.text}.")
        for line_index, _ in enumerate(lines):
            evidence[f"document_derived_findings.{index}.{line_index}"] = SummarySourceType.DOCUMENT
        return lines, evidence, uncertain

    @staticmethod
    def _source_terms(payload: SummaryInput) -> set[str]:
        blob = payload.model_dump_json()
        return set(re.findall(r"[a-z0-9]+(?:\.[0-9]+)?", _normalise(blob)))

    @staticmethod
    def _required_attention(risk: Optional[RiskAssessment]) -> AttentionLevel:
        return risk.overall_attention_level if risk else AttentionLevel.ROUTINE

    @staticmethod
    def _has_document_diagnosis(payload: SummaryInput, text: str) -> bool:
        lowered = _normalise(text)
        return any(
            _normalise(item.text) in lowered
            for document in payload.document_extractions
            for item in document.diagnoses_mentioned
        )

    @staticmethod
    def _has_explicit_no_allergy(payload: SummaryInput) -> bool:
        return any(
            _normalise(item.text) in {"no known allergies", "no allergies"}
            for document in payload.document_extractions
            for item in document.allergies
        )

    @staticmethod
    def _is_empty(payload: SummaryInput) -> bool:
        return not any((payload.clinical_history, payload.risk_assessment, payload.document_extractions, payload.patient_conversation, payload.ayush_assessment))


def _format_medication(medication: Any) -> str:
    parts = [medication.name_as_reported]
    for name in ("dose_as_reported", "frequency_as_reported", "route_as_reported", "duration_as_reported"):
        value = getattr(medication, name, None)
        if value:
            parts.append(value)
    return " ".join(parts)
