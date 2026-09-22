# Privacy Protection Test Report

Test date: 2026-09-09

## Privacy Gateway

Status: PASS

All five agents sanitize their prompt before calling an injected or production LLM interface. `LLMClient` performs a second, fail-closed privacy-gateway check immediately before the repository's only Gemini SDK call.

## Identifier Detection

Total tests: 27  
Passed: 27  
Failed: 0

Synthetic coverage includes names, phone numbers, email addresses, addresses, dates of birth, MRNs, hospital/insurance/patient/document/account identifiers, social-security-style values, URLs, JSON metadata, source evidence, medication/allergy/laboratory text, discharge text, uncertain OCR, multiple identifiers, and a clean clinical control.

## Outbound LLM Protection

Total: 7  
Passed: 7  
Failed: 0

Captured-payload tests cover Interview, Structuring, Risk, Document, Summary, repair, and direct `LLMClient` paths. Original synthetic identifiers were absent while clinical content such as chest pain, breathlessness, laboratory values, and medications remained available.

## OCR Protection

Total: 2  
Passed: 2  
Failed: 0

The document-agent test verifies that synthetic hospital, patient, MRN, phone, and document identifiers do not occur in the outbound prompt, while Hemoglobin 13.2 and Glucose 110 remain. No raw OCR is sent to the LLM boundary; OCR is redacted and minimized first.

## Summary Protection

Total: 1  
Passed: 1  
Failed: 0

The summary test verifies de-identification of structured source text and deliberate omission of the duplicate raw patient transcript from the summary prompt.

## Repair Prompt Protection

Total: 1  
Passed: 1  
Failed: 0

A forced structuring validation failure produced a captured repair prompt without the synthetic identifier, while retaining the validation context and clinical fact.

## Error/Logging Protection

Total: 2  
Passed: 2  
Failed: 0

The LLM client converts provider/client failures to `LLM_PROCESSING_ERROR` and privacy failures to `PRIVACY_GATEWAY_BLOCKED`. The orchestrator stores a stage code instead of injected exception text. Application logs use safe reason/type/status metadata rather than prompt, OCR, response, or credential contents.

## Bypass Protection

Total: 2  
Passed: 2  
Failed: 0

Gateway failure blocks both direct LLM client use and an agent call. Static audit found one production `generate_content` call, in `core/llm_client.py`, and all production agent `generate_json` paths prepare a safe prompt first.

## Safety Regression

Phase 1: PASS  
Phase 2: PASS  
Phase 3: PASS  
Phase 4: PASS  
Phase 5: PASS  
Phase 6: PASS  
Phase 7: PASS

The complete suite result was **156 passed, 0 failed, 2 skipped**. The two skips are the existing optional live-Gemini tests; no live calls were run.

## Privacy Invariants

| Invariant | Result |
|---|---|
| 1. No production LLM request bypasses Privacy Gateway | PASS |
| 2. Original patient identifiers are absent from outbound test payloads | PASS |
| 3. Raw OCR identifiers are absent from outbound test payloads | PASS |
| 4. API keys are absent from outbound test payloads | PASS |
| 5. User-facing workflow errors do not retain raw patient data | PASS |
| 6. User-facing workflow errors do not retain API keys | PASS |
| 7. Gateway failure does not transmit raw data | PASS |
| 8. Clinical information remains usable after de-identification | PASS |
| 9. Urgent chest-pain/breathlessness context survives filtering | PASS |
| 10. Source attribution survives filtering | PASS |
| 11. Contradiction handling regression tests pass | PASS |
| 12. Uncertainty handling regression tests pass | PASS |
| 13. Patient-reported concern handling regression tests pass | PASS |
| 14. Document OCR is redacted/minimized before outbound use | PASS |
| 15. Summary excludes duplicate raw transcript | PASS |

## Remaining Limitations

- Deterministic pattern/entity detection cannot guarantee recognition of every identifier, especially unlabelled names and novel formats.
- Application-level de-identification does not establish regulatory compliance or clinical privacy certification.
- Vendor data-handling terms, account configuration, retention, and external LLM behavior must be verified independently.
- Infrastructure-level encryption, access control, network egress controls, and persistence controls are outside this repository.
- This remains a prototype and is not clinically validated.
