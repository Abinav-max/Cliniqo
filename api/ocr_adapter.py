"""OCR Adapter: maps external OCR service JSON to backend DocumentInput and frontend review format."""

from __future__ import annotations

import hashlib
import json
import logging
from datetime import datetime
from typing import Any

from core.schemas import DocumentInput

logger = logging.getLogger(__name__)


class OCRAdapterError(Exception):
    """Raised when OCR response cannot be adapted."""


def extract_ocr_text(ocr_response: dict[str, Any]) -> str:
    """Extract full OCR text from the OCR response."""
    parts = []
    
    # From OCR pages
    ocr_data = ocr_response.get("ocr", {})
    pages = ocr_data.get("pages", [])
    for page in pages:
        page_text = page.get("text", "")
        if page_text:
            parts.append(f"[Page {page.get('page', '?')}]\n{page_text}")
    
    # Fallback to extracted_text_summary or key_findings from AI section
    ai_data = ocr_response.get("ai", {})
    if not parts and ai_data.get("extracted_text_summary"):
        parts.append(ai_data["extracted_text_summary"])
    if not parts and ai_data.get("key_findings"):
        parts.extend(ai_data["key_findings"])
    
    # Fallback to structured_data text representation
    if not parts:
        structured = ocr_response.get("structured_data", {})
        if structured:
            parts.append(json.dumps(structured, indent=2))
    
    return "\n\n".join(parts) if parts else ""


def build_document_input(ocr_response: dict[str, Any], *, source_filename: str | None = None) -> DocumentInput:
    """Convert external OCR response to backend DocumentInput."""
    
    document_id = ocr_response.get("document_id")
    if not document_id:
        source = ocr_response.get("source", {})
        document_id = source.get("filename", f"ocr_{hashlib.md5(str(ocr_response).encode()).hexdigest()[:8]}")
    
    # Extract document type from classification
    classification = ocr_response.get("classification", {})
    document_type = classification.get("selected") or classification.get("detected")
    
    # Extract document date from structured data, then patient-provided context.
    structured_data = ocr_response.get("structured_data", {})
    document_date = structured_data.get("date") or ocr_response.get("document_date")
    temporal = ocr_response.get("classification", {}) or {}
    
    # Extract OCR text
    ocr_text = extract_ocr_text(ocr_response)
    
    if not ocr_text.strip():
        logger.warning("OCR response contains no extractable text")
        # Use a minimal fallback to prevent empty input
        ocr_text = f"Document: {source_filename or document_id}\nType: {document_type}\nNo extractable OCR text found."
    
    return DocumentInput(
        document_id=document_id,
        document_type=document_type,
        document_date=document_date,
        document_date_type=ocr_response.get("document_date_type", "unknown"),
        document_date_source=ocr_response.get("document_date_source", "unknown"),
        document_classification=ocr_response.get("document_classification") or temporal.get("selected") or "historical",
        classification_source=ocr_response.get("classification_source") or temporal.get("source") or "patient",
        ocr_text=ocr_text,
    )


def build_frontend_review_response(ocr_response: dict[str, Any]) -> dict[str, Any]:
    """Build the response format for the frontend's Review Extracted Information screen."""
    
    source = ocr_response.get("source", {})
    classification = ocr_response.get("classification", {})
    quality = ocr_response.get("quality", {})
    ocr_data = ocr_response.get("ocr", {})
    ai_data = ocr_response.get("ai", {})
    extracted_fields = ocr_response.get("extracted_fields", [])
    warnings = ocr_response.get("warnings", [])
    review = ocr_response.get("review", {})
    structured_data = ocr_response.get("structured_data", {})
    
    document_id = ocr_response.get("document_id") or source.get("document_id", "unknown")
    filename = source.get("filename", "document.pdf")
    page_count = source.get("page_count", 1)
    
    # Determine document type and mismatch
    selected_type = classification.get("selected")
    detected_type = classification.get("detected")
    ai_detected = classification.get("ai_detected_type")
    type_mismatch = classification.get("type_mismatch", False)
    requires_confirmation = classification.get("requires_confirmation", False)
    confidence = classification.get("confidence", 0.0)
    
    # Build pages for preview
    pages = []
    for page in ocr_data.get("pages", []):
        pages.append({
            "page": page.get("page"),
            "width": page.get("width"),
            "height": page.get("height"),
            "text": page.get("text", "")[:5000],  # Limit for UI
            "blocks": page.get("blocks", [])[:50],  # Limit blocks
        })
    
    # Build extracted fields for inspector
    inspector_fields = []
    for idx, field in enumerate(extracted_fields):
        inspector_fields.append({
            "id": field.get("id", f"field_{idx}"),
            "field": field.get("field"),
            "value": field.get("value"),
            "raw_value": field.get("raw_value"),
            "normalized_value": field.get("normalized_value"),
            "user_value": field.get("user_value"),
            "confidence": field.get("confidence"),
            "ocr_confidence": field.get("ocr_confidence"),
            "ai_extraction_confidence": field.get("ai_extraction_confidence"),
            "verification_confidence": field.get("verification_confidence"),
            "source": field.get("source"),
            "page": field.get("page"),
            "bbox": field.get("bbox"),
            "source_text": field.get("source_text"),
            "editable": field.get("editable", True),
            "warning": field.get("warning"),
        })
    
    # Determine review status
    review_required = review.get("required", False)
    review_status = review.get("status", "pending")
    
    # Build quality metrics
    quality_score = quality.get("score", 0)
    avg_ocr_confidence = quality.get("average_ocr_confidence", 0)
    image_quality = quality.get("image_quality", "unknown")
    text_density = quality.get("text_density", "unknown")
    page_coverage = quality.get("page_coverage", 0)
    extraction_completeness = quality.get("extraction_completeness", 0)
    quality_issues = quality.get("issues", [])
    
    return {
        "document_id": document_id,
        "filename": filename,
        "page_count": page_count,
        "document_type": selected_type,
        "review_status": review_status,
        "review_required": review_required,
        "ocr_confidence": avg_ocr_confidence,
        "extraction_completeness": extraction_completeness,
        "classification": {
            "selected": selected_type,
            "detected": detected_type,
            "ai_detected": ai_detected,
            "confidence": confidence,
            "type_mismatch": type_mismatch,
            "requires_confirmation": requires_confirmation,
            "warning": classification.get("warning"),
        },
        "quality": {
            "score": quality_score,
            "average_ocr_confidence": avg_ocr_confidence,
            "image_quality": image_quality,
            "text_density": text_density,
            "page_coverage": page_coverage,
            "extraction_completeness": extraction_completeness,
            "issues": quality_issues,
        },
        "pages": pages,
        "extracted_fields": inspector_fields,
        "warnings": warnings,
        "structured_data": structured_data,
    }


def build_timeline_event_from_document(ocr_response: dict[str, Any]) -> dict[str, Any] | None:
    """Create a timeline event from a confirmed document."""
    source = ocr_response.get("source", {})
    structured = ocr_response.get("structured_data", {})
    classification = ocr_response.get("classification", {})
    
    doc_type = classification.get("selected") or classification.get("detected") or "document"
    doc_date = structured.get("date") or ocr_response.get("document_date")
    
    # Try to parse date
    event_date = None
    if doc_date:
        try:
            # Handle various date formats
            for fmt in ("%Y-%m-%d", "%d/%m/%y", "%d/%m/%Y", "%Y-%m-%dT%H:%M:%S"):
                try:
                    event_date = datetime.strptime(doc_date, fmt).strftime("%d %b %Y")
                    break
                except ValueError:
                    continue
        except Exception:
            pass
    
    if not event_date:
        event_date = "Date unknown"
    
    doc_category_map = {
        "prescription": "prescription",
        "lab": "lab",
        "lab_report": "lab",
        "imaging": "lab",
        "discharge": "surgery",
        "discharge_summary": "surgery",
    }
    category = doc_category_map.get(doc_type.lower(), "intake")
    
    title_map = {
        "prescription": "Prescription",
        "lab": "Lab Report",
        "lab_report": "Lab Report",
        "imaging": "Imaging Report",
        "discharge": "Discharge Summary",
        "discharge_summary": "Discharge Summary",
    }
    title = title_map.get(doc_type.lower(), "Document")
    
    clinic = structured.get("clinic") or structured.get("doctor") or source.get("filename", "Unknown")
    
    return {
        "id": f"doc_{ocr_response.get('document_id', 'unknown')}",
        "category": category,
        "date": event_date,
        "title": f"{title} ({clinic})",
        "description": f"Document type: {doc_type}. {classification.get('selected') or ocr_response.get('document_classification') or 'Historical'} document. Date source: {ocr_response.get('document_date_source') or 'unknown'}.",
        "source": "document",
        "temporal_status": ocr_response.get("temporal_status") or classification.get("selected") or "unknown",
        "date_type": ocr_response.get("document_date_type", "unknown"),
        "date_source": ocr_response.get("document_date_source", "unknown"),
        "document_id": ocr_response.get("document_id"),
        "verified": True,
    }


def build_timeline_event_from_intake(session_id: str, clinical_history: dict[str, Any]) -> dict[str, Any]:
    """Create a timeline event from the patient intake."""
    chief_complaint = clinical_history.get("chief_complaint") or "Health assessment"
    hpi = clinical_history.get("history_of_present_illness", {})
    duration = hpi.get("duration", "") if isinstance(hpi, dict) else ""
    
    return {
        "id": f"intake_{session_id[:8]}",
        "category": "intake",
        "date": datetime.now().strftime("%d %b %Y"),
        "title": "Patient Health Intake & Symptom Entry",
        "description": f"Reported: {chief_complaint}{f' ({duration})' if duration else ''}",
        "source": "patient_reported",
        "session_id": session_id,
        "verified": False,
    }