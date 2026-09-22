"""Document Intelligence Agent for OCR text supplied by an external pipeline.

This module intentionally performs no OCR and does not inspect image or PDF
pixels. It structures only the OCR text passed to :class:`DocumentInput`.
"""

from __future__ import annotations

import json
import re
from difflib import SequenceMatcher
from typing import Any, Callable, Optional, Protocol, TypeVar, runtime_checkable

from pydantic import BaseModel, ValidationError

from core.exceptions import StructuredOutputError
from core.prompts import DOCUMENT_SYSTEM_INSTRUCTION, SAFETY_SYSTEM_INSTRUCTION
from core.schemas import (
    DocumentEvidenceItem,
    DocumentExtraction,
    DocumentInput,
    DocumentMedication,
    LabResult,
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


T = TypeVar("T")
_ENTITY_FIELDS = (
    "diagnoses_mentioned",
    "procedures",
    "symptoms",
    "allergies",
    "clinical_observations",
    "follow_up_instructions",
    "unknown_or_unclear",
)


def _normalise(text: str) -> str:
    return re.sub(r"\s+", " ", text.strip().lower())


def _unique_by_source(items: list[T], source: Callable[[T], str]) -> list[T]:
    result: list[T] = []
    seen: set[str] = set()
    for item in items:
        key = _normalise(source(item))
        if key and key not in seen:
            seen.add(key)
            result.append(item)
    return result


class DocumentAgent:
    """Extract validated document-derived facts from OCR text only.

    Any LLM output is treated as untrusted and is validated against the exact
    supplied OCR text before it is returned. The agent neither runs nor replaces
    OCR.
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
            f"{SAFETY_SYSTEM_INSTRUCTION}\n\n{DOCUMENT_SYSTEM_INSTRUCTION}"
        )

    def extract(self, document: DocumentInput | dict[str, Any] | str) -> DocumentExtraction:
        """Convert externally supplied OCR text into a grounded extraction."""
        input_document = self._coerce_input(document)
        if not input_document.ocr_text.strip():
            return DocumentExtraction(
                document_id=input_document.document_id,
                document_type=input_document.document_type,
                document_date=input_document.document_date,
                missing_or_illegible_sections=["OCR text was empty."],
            )
        try:
            raw = self._generate(self._build_prompt(input_document))
        except StructuredOutputError as first:
            if str(first) == "PRIVACY_GATEWAY_BLOCKED":
                raise
            try:
                extracted = self._validate(self._generate(self._repair_prompt(input_document, {}, first)))
            except Exception as second:
                raise StructuredOutputError(
                    "Document extraction output could not be repaired and validated."
                ) from second
        else:
            extracted = self._validate_or_repair(raw, input_document)
        return self._ground_and_normalise(extracted, input_document)

    process = extract
    process_document = extract

    @staticmethod
    def _coerce_input(document: DocumentInput | dict[str, Any] | str) -> DocumentInput:
        if isinstance(document, DocumentInput):
            return document
        if isinstance(document, str):
            return DocumentInput(ocr_text=document)
        return DocumentInput.model_validate(document)

    def _generate(self, prompt: str) -> Any:
        try:
            safe_prompt = self._privacy_gateway.prepare(
                prompt, source_type="document"
            ).safe_text
        except PrivacyGatewayError as exc:
            raise StructuredOutputError("PRIVACY_GATEWAY_BLOCKED") from exc
        return self._llm.generate_json(
            safe_prompt,
            schema=DocumentExtraction,
            system_instruction=self._system_prompt,
            temperature=self._temperature,
        )

    def _validate_or_repair(self, raw: Any, document: DocumentInput) -> DocumentExtraction:
        try:
            return self._validate(raw)
        except (ValidationError, StructuredOutputError, TypeError, ValueError) as first:
            try:
                return self._validate(self._generate(self._repair_prompt(document, raw, first)))
            except Exception as second:
                raise StructuredOutputError(
                    "Document extraction output could not be repaired and validated."
                ) from second

    @staticmethod
    def _validate(raw: Any) -> DocumentExtraction:
        if isinstance(raw, DocumentExtraction):
            return raw
        if isinstance(raw, str):
            raw = json.loads(raw)
        if not isinstance(raw, dict):
            raise TypeError("Document extraction output must be a JSON object.")
        return DocumentExtraction.model_validate(raw)

    def _build_prompt(self, document: DocumentInput) -> str:
        # A document identifier links the record externally but is not needed to
        # extract clinical facts. Keep only useful type/date metadata; OCR still
        # receives the mandatory privacy treatment in _generate.
        metadata = document.model_dump(exclude={"ocr_text", "document_id"})
        return (
            "Extract a DocumentExtraction JSON object from the following OCR text. "
            "Every entity must include the exact OCR source_text that supports it. "
            "Do not add a recommendation field or make an AI treatment recommendation.\n\n"
            f"Upstream metadata:\n{json.dumps(metadata, indent=2)}\n\n"
            f"OCR text:\n{document.ocr_text}"
        )

    def _repair_prompt(self, document: DocumentInput, raw: Any, error: Exception) -> str:
        return (
            "Repair the previous DocumentExtraction JSON. Remove unsupported values, "
            "recommendations, and entities without exact OCR source_text. Preserve "
            "ambiguous OCR as uncertain instead of silently correcting it.\n"
            f"Validation error: {error}\nAttempted output: {json.dumps(raw, default=str)}\n\n"
            + self._build_prompt(document)
        )

    def _ground_and_normalise(
        self, extracted: DocumentExtraction, document: DocumentInput
    ) -> DocumentExtraction:
        ocr = document.ocr_text

        # Upstream metadata takes precedence over a probabilistic classification.
        extracted.document_id = document.document_id or extracted.document_id
        extracted.document_type = document.document_type
        extracted.document_classification = document.document_classification
        extracted.classification_source = document.classification_source
        extracted.document_date_type = document.document_date_type
        extracted.document_date_source = document.document_date_source
        extracted.temporal_status = document.document_classification if document.document_classification in {"current", "historical"} else "unknown"
        if document.document_date:
            extracted.document_date = document.document_date
            extracted.document_date_source_text = None
        elif not self._grounded_value(
            extracted.document_date, extracted.document_date_source_text, ocr, False
        ):
            extracted.document_date = None
            extracted.document_date_source_text = None

        extracted.medications = _unique_by_source(
            [item for item in extracted.medications if self._valid_medication(item, ocr)],
            lambda item: item.source_text,
        )
        extracted.lab_results = _unique_by_source(
            [item for item in extracted.lab_results if self._valid_lab_result(item, ocr)],
            lambda item: item.source_text,
        )
        for field in _ENTITY_FIELDS:
            items = getattr(extracted, field)
            setattr(
                extracted,
                field,
                _unique_by_source(
                    [item for item in items if self._valid_evidence_item(item, ocr)],
                    lambda item: item.source_text,
                ),
            )

        # Legacy fields are derived only from already-grounded entities.
        extracted.reported_values = {
            result.test_name: " ".join(
                part for part in (result.value_as_reported, result.unit_as_reported) if part
            )
            for result in extracted.lab_results
            if result.value_as_reported
        }
        extracted.missing_or_illegible_sections = _unique_strings(
            extracted.missing_or_illegible_sections
            + [item.text for item in extracted.unknown_or_unclear]
        )
        if extracted.source_excerpt and not self._source_in_document(extracted.source_excerpt, ocr):
            extracted.source_excerpt = None
        if extracted.extracted_text_summary and not self._source_in_document(
            extracted.extracted_text_summary, ocr
        ):
            extracted.extracted_text_summary = None
        extracted.key_findings = []
        extracted.source_type = "document"
        extracted.for_clinician_review_only = True
        return extracted

    def _valid_medication(self, item: DocumentMedication, ocr: str) -> bool:
        if not self._source_in_document(item.source_text, ocr):
            return False
        values = (
            item.name_as_reported,
            item.dose_as_reported,
            item.frequency_as_reported,
            item.route_as_reported,
            item.duration_as_reported,
        )
        return all(
            self._grounded_value(value, item.source_text, ocr, item.uncertain)
            for value in values
            if value is not None
        )

    def _valid_lab_result(self, item: LabResult, ocr: str) -> bool:
        if not self._source_in_document(item.source_text, ocr):
            return False
        values = (
            item.test_name,
            item.value_as_reported,
            item.unit_as_reported,
            item.reference_range_as_reported,
            item.date_as_reported,
        )
        return all(
            self._grounded_value(value, item.source_text, ocr, item.uncertain)
            for value in values
            if value is not None
        )

    def _valid_evidence_item(self, item: DocumentEvidenceItem, ocr: str) -> bool:
        return self._source_in_document(item.source_text, ocr) and self._grounded_value(
            item.text, item.source_text, ocr, item.uncertain
        )

    def _source_in_document(self, source: str, ocr: str) -> bool:
        """Compare evidence after the same de-identification used at egress.

        A model only receives redacted OCR, so a valid returned source excerpt
        can contain privacy tokens that do not occur verbatim in retained raw
        OCR. This preserves evidence grounding without restoring identifiers.
        """
        try:
            safe_source = self._privacy_gateway.prepare(
                source, source_type="document_grounding"
            ).safe_text
            safe_ocr = self._privacy_gateway.prepare(
                ocr, source_type="document_grounding"
            ).safe_text
        except PrivacyGatewayError:
            return False
        return bool(safe_source.strip()) and _normalise(safe_source) in _normalise(safe_ocr)

    def _grounded_value(
        self, value: Optional[str], source: Optional[str], ocr: str, uncertain: bool
    ) -> bool:
        if value is None:
            return True
        if not source or not self._source_in_document(source, ocr):
            return False
        normal_value = _normalise(value)
        normal_source = _normalise(source)
        if normal_value in normal_source:
            return True
        # An uncertain item may preserve a cautiously interpreted OCR value only
        # when it still resembles the OCR source; uncertainty is not a bypass for
        # invented facts.
        if uncertain:
            return self._uncertainly_supported(normal_value, normal_source)
        tokens = re.findall(r"[a-z0-9.]+", normal_value)
        return bool(tokens) and all(token in normal_source for token in tokens)

    @staticmethod
    def _uncertainly_supported(value: str, source: str) -> bool:
        value_tokens = re.findall(r"[a-z0-9.]+", value)
        source_tokens = re.findall(r"[a-z0-9.]+", source)
        if not value_tokens or not source_tokens:
            return False
        return all(
            any(SequenceMatcher(None, token, candidate).ratio() >= 0.78 for candidate in source_tokens)
            for token in value_tokens
        )


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        key = _normalise(value)
        if value and key not in seen:
            seen.add(key)
            result.append(value)
    return result
