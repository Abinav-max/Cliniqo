"""Synthetic privacy invariants for the outbound LLM boundary."""

from __future__ import annotations

from typing import Any

import pytest

from agents.document_agent import DocumentAgent
from agents.interview_agent import InterviewAgent
from agents.risk_agent import RiskAgent
from agents.structuring_agent import StructuringAgent
from agents.summary_agent import SummaryAgent
from core.config import Settings
from core.exceptions import LLMConnectionError, StructuredOutputError
from core.llm_client import LLMClient
from core.orchestrator import MedicalOrchestrator
from core.schemas import ClinicalHistory, DocumentExtraction, RiskAssessment, SummaryInput
from privacy import PrivacyGateway, PrivacyGatewayError, PrivacyPayloadBlockedError


class CaptureLLM:
    def __init__(self, responses: list[Any]) -> None:
        self.responses = list(responses)
        self.calls: list[str] = []

    def generate_json(self, prompt: str, **_: Any) -> Any:
        self.calls.append(prompt)
        return self.responses.pop(0) if self.responses else {}


_CASES = [
    ("name", "Name: TEST_PERSON_123\nChest pain for two days.", "TEST_PERSON_123", "person"),
    ("name_sentence", "My name is Arun. I have chest pain.", "Arun", "person"),
    ("unlabelled_name", "Arun Nithees reports chest pain for two days.", "Arun Nithees", "person"),
    ("phone", "Phone: 9999999999\nChest pain for two days.", "9999999999", "phone"),
    ("email", "Email: synthetic.patient@example.test\nChest pain for two days.", "synthetic.patient@example.test", "email"),
    ("address", "Address: 12 Test Street\nChest pain for two days.", "12 Test Street", "address"),
    ("dob", "DOB: 1990-01-02\nChest pain for two days.", "1990-01-02", "dob"),
    ("mrn", "MRN: TEST_MRN_123\nChest pain for two days.", "TEST_MRN_123", "mrn"),
    ("hospital", "Hospital ID: TEST_HOSPITAL_55\nChest pain for two days.", "TEST_HOSPITAL_55", "hospital_id"),
    ("insurance", "Insurance ID: TEST_INSURANCE_42\nChest pain for two days.", "TEST_INSURANCE_42", "insurance_id"),
    ("patient_id", "Patient ID: TEST_PATIENT_99\nChest pain for two days.", "TEST_PATIENT_99", "patient_id"),
    ("ssn", "SSN 123-45-6789. Chest pain for two days.", "123-45-6789", "ssn"),
    ("url", "https://example.test/patient/TEST_PERSON_123 has chest pain.", "https://example.test/patient/TEST_PERSON_123", "url"),
    ("account", "Account Number: ACCT-TEST-987\nChest pain for two days.", "ACCT-TEST-987", "account_number"),
    ("document_id", 'Document ID: TEST_DOCUMENT_77\nHemoglobin: 13.2', "TEST_DOCUMENT_77", "document_id"),
    ("multiple", "Name: TEST_PERSON_123; Phone: 9999999999; chest pain.", "TEST_PERSON_123", "person"),
    ("clinical_sentence", "Patient TEST_PERSON_123 has severe chest pain and breathlessness.", "TEST_PERSON_123", "person"),
    ("ocr_header", "Patient Name: TEST_PERSON_123\nGlucose: 110", "TEST_PERSON_123", "person"),
    ("source_evidence", '"source_evidence": "Name: TEST_PERSON_123; chest pain"', "TEST_PERSON_123", "person"),
    ("medication_note", "Phone: 9999999999; taking metformin 500 mg daily.", "9999999999", "phone"),
    ("allergy_note", "Email: synthetic.patient@example.test; allergic to penicillin.", "synthetic.patient@example.test", "email"),
    ("lab_report", "MRN: TEST_MRN_123\nHemoglobin: 13.2", "TEST_MRN_123", "mrn"),
    ("discharge", "Patient Name: TEST_PERSON_123\nDischarge diagnosis: asthma", "TEST_PERSON_123", "person"),
    ("uncertain_ocr", "MRN: TEST_MRN_123\nMetfor? 500 mg", "TEST_MRN_123", "mrn"),
    ("api_key", "TEST_API_KEY_ABC123 and chest pain for two days.", "TEST_API_KEY_ABC123", "secret"),
    ("json_metadata", '{"document_id": "TEST_DOCUMENT_77", "chief_complaint": "chest pain"}', "TEST_DOCUMENT_77", "document_id"),
]


@pytest.mark.parametrize("_name,text,identifier,category", _CASES)
def test_gateway_removes_synthetic_identifier_and_retains_clinical_context(
    _name: str, text: str, identifier: str, category: str
) -> None:
    payload = PrivacyGateway().prepare(text, source_type="test")
    assert identifier not in payload.safe_text
    assert category in payload.detected_categories
    if any(term in text.lower() for term in ("chest pain", "hemoglobin", "glucose", "metformin", "penicillin", "asthma")):
        assert any(term in payload.safe_text.lower() for term in ("chest pain", "hemoglobin", "glucose", "metformin", "penicillin", "asthma"))


def test_clean_clinical_text_remains_usable() -> None:
    payload = PrivacyGateway().prepare("Severe chest pain and breathlessness for two days.", source_type="test")
    assert payload.redaction_count == 0
    assert "chest pain" in payload.safe_text.lower()
    assert "breathlessness" in payload.safe_text.lower()


def test_empty_and_oversized_payloads_fail_closed() -> None:
    gateway = PrivacyGateway(max_payload_chars=10)
    with pytest.raises(PrivacyPayloadBlockedError):
        gateway.prepare(" ", source_type="test")
    with pytest.raises(PrivacyPayloadBlockedError):
        gateway.prepare("x" * 11, source_type="test")


def test_detector_failure_fails_closed() -> None:
    class BrokenDetector:
        def redact(self, _: str) -> tuple[str, list[str], int]:
            raise RuntimeError("raw data must not escape")

    with pytest.raises(PrivacyGatewayError):
        PrivacyGateway(detector=BrokenDetector()).prepare("chest pain", source_type="test")


def test_interview_outbound_prompt_is_deidentified() -> None:
    llm = CaptureLLM([{"assistant_message": "When did the chest pain start?"}])
    InterviewAgent(llm).handle_message("My name is TEST_PERSON_123 and my phone is 9999999999. I have chest pain.")
    prompt = llm.calls[0]
    assert "TEST_PERSON_123" not in prompt and "9999999999" not in prompt
    assert "chest pain" in prompt.lower()


def test_structuring_outbound_prompt_is_deidentified() -> None:
    llm = CaptureLLM([{"chief_complaint": "chest pain", "source_evidence": {"chief_complaint": "I have chest pain."}}])
    StructuringAgent(llm).structure("Name: TEST_PERSON_123\nI have chest pain.")
    assert "TEST_PERSON_123" not in llm.calls[0]
    assert "chest pain" in llm.calls[0].lower()


def test_risk_outbound_prompt_is_deidentified_and_preserves_urgent_context() -> None:
    llm = CaptureLLM([{}])
    history = ClinicalHistory(
        session_id="TEST_PATIENT_99",
        chief_complaint="severe chest pain",
        associated_symptoms=["breathlessness"],
        source_evidence={"chief_complaint": "Name: TEST_PERSON_123; severe chest pain"},
    )
    RiskAgent(llm).assess(history)
    assert "TEST_PERSON_123" not in llm.calls[0] and "TEST_PATIENT_99" not in llm.calls[0]
    assert "severe chest pain" in llm.calls[0].lower()
    assert "breathlessness" in llm.calls[0].lower()


def test_document_ocr_outbound_prompt_is_deidentified_and_retains_labs() -> None:
    llm = CaptureLLM([{"lab_results": [{"test_name": "Hemoglobin", "value_as_reported": "13.2", "source_text": "Hemoglobin: 13.2"}, {"test_name": "Glucose", "value_as_reported": "110", "source_text": "Glucose: 110"}]}])
    DocumentAgent(llm).extract({"document_id": "TEST_DOCUMENT_77", "ocr_text": "Hospital: TEST_HOSPITAL\nPatient Name: TEST_PERSON_123\nMRN: TEST_MRN_123\nPhone: 9999999999\n\nHemoglobin: 13.2\nGlucose: 110"})
    prompt = llm.calls[0]
    for identifier in ("TEST_HOSPITAL", "TEST_PERSON_123", "TEST_MRN_123", "9999999999", "TEST_DOCUMENT_77"):
        assert identifier not in prompt
    assert "hemoglobin" in prompt.lower() and "13.2" in prompt and "glucose" in prompt.lower() and "110" in prompt


def test_summary_excludes_raw_transcript_and_deidentifies_structured_sources() -> None:
    llm = CaptureLLM([{"overview": "Reported chest pain."}])
    history = ClinicalHistory(chief_complaint="chest pain", source_evidence={"chief_complaint": "Name: TEST_PERSON_123; chest pain"})
    document = DocumentExtraction(source_excerpt="MRN: TEST_MRN_123; Hemoglobin: 13.2")
    payload = SummaryInput(
        clinical_history=history,
        risk_assessment=RiskAssessment(),
        document_extractions=[document],
        patient_conversation=["My name is TEST_PERSON_123 and I have chest pain."],
    )
    SummaryAgent(llm).summarize(payload)
    prompt = llm.calls[0]
    assert "TEST_PERSON_123" not in prompt and "TEST_MRN_123" not in prompt
    assert "patient_conversation" in prompt and '"patient_conversation": []' in prompt
    assert "chest pain" in prompt.lower()


def test_repair_prompt_is_deidentified() -> None:
    llm = CaptureLLM([
        {"unexpected": "Name: TEST_PERSON_123; chest pain"},
        {"chief_complaint": "chest pain", "source_evidence": {"chief_complaint": "I have chest pain."}},
    ])
    StructuringAgent(llm).structure("Name: TEST_PERSON_123\nI have chest pain.")
    assert len(llm.calls) == 2
    assert all("TEST_PERSON_123" not in prompt for prompt in llm.calls)
    assert "Validation problem" in llm.calls[1]
    assert "chest pain" in llm.calls[1].lower()


def test_llm_client_rechecks_direct_prompt_before_sdk(monkeypatch: pytest.MonkeyPatch) -> None:
    client = LLMClient(Settings(groq_api_key="test-not-a-real-key"))
    captured: list[str] = []

    class Response:
        text = "OK"

    def fake_generate_safe(payload: Any, **_: Any) -> Response:
        captured.append(payload.safe_text)
        return Response()

    monkeypatch.setattr(client, "_generate_safe", fake_generate_safe)
    assert client.generate_text("Name: TEST_PERSON_123. Chest pain.") == "OK"
    assert "TEST_PERSON_123" not in captured[0]
    assert "chest pain" in captured[0].lower()


def test_llm_client_blocks_gateway_failure(monkeypatch: pytest.MonkeyPatch) -> None:
    class BrokenGateway:
        def prepare(self, *_: Any, **__: Any) -> Any:
            raise PrivacyGatewayError("PRIVACY_GATEWAY_UNAVAILABLE")

    client = LLMClient(Settings(groq_api_key="test-not-a-real-key"), privacy_gateway=BrokenGateway())
    with pytest.raises(LLMConnectionError, match="PRIVACY_GATEWAY_BLOCKED"):
        client.generate_text("chest pain")


def test_agent_blocks_when_privacy_gateway_is_unavailable() -> None:
    class BrokenGateway:
        def prepare(self, *_: Any, **__: Any) -> Any:
            raise PrivacyGatewayError("PRIVACY_GATEWAY_UNAVAILABLE")

    with pytest.raises(StructuredOutputError, match="PRIVACY_GATEWAY_BLOCKED"):
        DocumentAgent(CaptureLLM([]), privacy_gateway=BrokenGateway()).extract("Hemoglobin: 13.2")


def test_workflow_errors_do_not_retain_injected_sensitive_exception_text() -> None:
    class FailingInterview:
        def handle_message(self, _: str) -> Any:
            raise RuntimeError("Name: TEST_PERSON_123; api key TEST_API_KEY_ABC123")

    state = MedicalOrchestrator(
        interview_agent=FailingInterview(),
        structuring_agent=object(),
        risk_agent=object(),
        document_agent=object(),
        summary_agent=object(),
    ).handle_patient_message("chest pain")
    assert state.errors[-1].message == "INTERVIEW_STAGE_FAILED"
    assert "TEST_PERSON_123" not in state.errors[-1].message
    assert "TEST_API_KEY_ABC123" not in state.errors[-1].message
