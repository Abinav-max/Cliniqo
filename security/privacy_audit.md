# Security and Privacy Audit

Audit date: 2026-09-09
Method: static, read-only review of the repository's `agents/`, `core/`, `tests/`, `evaluation/`, configuration examples, and README. This audit did not inspect `.env` contents, make network calls, or assess infrastructure outside this repository.

## PRIVACY AUDIT RESULT

**Overall result: CRITICAL.** The application sends clinical content to Gemini through one shared SDK client. There is no implemented technical de-identification, consent gate, payload-minimization layer, or vendor-boundary policy enforcement before those calls. If a user supplies identifiers in chat or in an uploaded document's OCR, identifiable medical data can be sent externally.

The safety prompts tell the model not to use or invent patient-identifiable data, but that is behavioral guidance to the model. It does not remove identifiers already present in the request.

## Gemini call locations

The only direct Gemini SDK request is `core/llm_client.py:167-171`, which invokes `google.genai.Client(...).models.generate_content(model=..., contents=prompt, config=...)`. The configured Gemini API key is supplied when the client is constructed at `core/llm_client.py:36-45`.

| Component | Calls Gemini? | Data sent | Patient identifiers possible? | Risk |
|---|---|---|---|---|
| `core/llm_client.py` | Yes, direct | Any caller's prompt; system instruction and response schema/configuration | Yes, because the client has no content filter or redaction step | HIGH |
| `agents/interview_agent.py` | Yes, through `generate_json` | Current collected information, entire raw conversation history, and latest patient message | Yes: every free-text patient message can include any identifier | CRITICAL |
| `agents/structuring_agent.py` | Yes, through `generate_json` | Full rendered conversation, including patient and assistant turns | Yes: raw conversation is forwarded unchanged | HIGH |
| `agents/risk_agent.py` | Yes, through `generate_json` | Full `ClinicalHistory` JSON, including session ID, source notes, source evidence, clinical details, medicines, allergies, and social history | Yes: source fields and arbitrary structured fields can contain identifiers | HIGH |
| `agents/document_agent.py` | Yes, through `generate_json` | Document metadata and complete `ocr_text` | Yes: OCR and document ID/date may contain identifiers | CRITICAL |
| `agents/summary_agent.py` | Yes, through `generate_json` | Full `SummaryInput`: history, risk assessment, document extractions with source text, and raw patient conversation | Yes: this aggregates data from all upstream stages | CRITICAL |
| `core/orchestrator.py` | No direct SDK call | Retains full conversation/state, invokes all agents, and supplies raw patient-only conversation to Summary | Yes: it deliberately forwards patient text to Summary | HIGH |
| `evaluation/` | No production Gemini call | Synthetic scenarios are processed through fake LLMs | No realistic identifiers found in reviewed fixtures | LOW |
| Optional live tests | Yes, only when explicitly enabled | A connectivity prompt and one stated synthetic interview message | The reviewed live inputs are synthetic; future edits could change that | LOW |

## Patient data flow

```text
Patient chat ──> Interview Agent ──> Gemini
                    │ raw conversation + extracted fields
                    v
                Structuring Agent ──> Gemini
                    │ ClinicalHistory + source excerpts
                    v
                  Risk Agent ──> Gemini

OCR document ──> Document Agent ──> Gemini
                    │ complete OCR + document metadata
                    v
Interview/History/Risk/Document outputs + raw patient conversation
                    └──────────────> Summary Agent ──> Gemini
```

`MedicalOrchestrator` retains the conversation and serialized interview state in `OrchestrationState`, then passes all patient turns to the summary stage (`core/orchestrator.py:162-170`, `200-210`). The repository does not include a database, storage service, encryption layer, retention control, or transport policy beyond the SDK call; deployment code may add controls that are not visible here.

### Per-stage data handling

| Stage | Input | Processing | LLM call | Data crossing the Gemini boundary | Output / retained data |
|---|---|---|---|---|---|
| Interview | A patient message | Appends raw text to `conversation_history`; derives collected fields | `InterviewAgent._call_llm` | Entire conversation history, full collected-information JSON, and latest message (`agents/interview_agent.py:379-400`) | Interview state retains raw patient/assistant turns and structured excerpts |
| Structuring | Interview result or conversation | Renders every role/content pair | `StructuringAgent._generate` | Full rendered conversation (`agents/structuring_agent.py:180-189`) | `ClinicalHistory`, including raw source evidence and optional source notes |
| Risk | `ClinicalHistory` | Runs deterministic flags before contextual review | `RiskAgent._generate` | Full serialized history (`agents/risk_agent.py:211-218`) | `RiskAssessment`, including evidence/flags and session ID |
| Document | `DocumentInput` with OCR text | Serializes metadata and appends OCR verbatim | `DocumentAgent._generate` | Metadata plus full OCR (`agents/document_agent.py:144-151`) | `DocumentExtraction`, retaining OCR-derived source text/excerpts |
| Summary | History, risk, document extractions, optional patient conversation | Serializes the complete `SummaryInput` | `SummaryAgent._generate` | Full combined payload (`agents/summary_agent.py:205-211`) | `PhysicianSummary`; the orchestrator also retains upstream state |
| Repair paths | Failed/invalid model output plus original stage input | Constructs a repair prompt | A second `generate_json` call | Original sensitive input is resent, alongside attempted model output and validation error | Applies to structuring, risk, document, and summary (`_repair_prompt` methods) |

## Potential identifier exposure

No schema or agent performs allow-listing, detection, tokenization, masking, or deletion of identifiers before a Gemini request. A field not being named explicitly in a schema does not prevent it from being included in free text or OCR.

| Identifier type | Potential entry point | Gemini-exposed stages |
|---|---|---|
| Name | Patient chat, raw conversation, OCR, `source_notes`, `source_evidence` | Interview, Structuring, Risk when retained in history, Document, Summary |
| Phone number | Patient chat or OCR | Interview, Structuring, Document, Summary; Risk if copied into history evidence/notes |
| Email address | Patient chat or OCR | Interview, Structuring, Document, Summary; Risk if copied into history evidence/notes |
| Address | Patient chat or OCR | Interview, Structuring, Document, Summary; Risk if copied into history evidence/notes |
| Date of birth / age-related identifiers | Patient chat or OCR | Interview, Structuring, Document, Summary; Risk if structured or copied into evidence |
| Hospital ID, MRN, insurance number, patient ID | Patient chat, OCR, `document_id`, session-related fields | Document and Summary directly for `document_id`; Interview/Structuring/Summary for free text; Risk/summary for retained `session_id` and structured evidence |
| Free-text identifier | Any unstructured `content`, clinical text field, note, excerpt, or OCR text | All agent stages that receive that text |
| Document identifiers | `document_id`, document metadata, OCR headers/footers | Document and Summary |

`PatientMessage` has `message_id` and `session_id` fields (`core/schemas.py:61-69`), while `ClinicalHistory`, `RiskAssessment`, `DocumentInput`, `DocumentExtraction`, and `PhysicianSummary` also model session/document identifiers. The prompt paths do not consistently include every metadata field, but nothing prevents values that are identifying or linkable from reaching Gemini through serialized inputs or free text.

## OCR exposure

**FULL OCR TEXT MAY REACH EXTERNAL LLM.**

`DocumentAgent._build_prompt` puts `document.model_dump_json(exclude={'ocr_text'})` and then `document.ocr_text` directly into the prompt (`agents/document_agent.py:144-151`). There is no OCR filtering, field selection, character limit, name/MRN detection, or redaction. Validation repair resends the same OCR plus the failed output (`agents/document_agent.py:153-160`).

The Summary Agent then sends document-extraction fields and retained OCR-derived evidence/source text in its complete payload. This creates a second external disclosure channel for document content, even after document extraction.

## Logging exposure

Normal prompts and responses are not explicitly logged by the application code reviewed. `core/orchestrator.py` logs only stage and status (`core/orchestrator.py:282-284`), and no repository logging sink/handler configuration was found.

There are still meaningful leakage paths:

- `LLMClient` logs `str(exc)` for Gemini API/client errors (`core/llm_client.py:174-184`). It redacts the exact configured API-key string only. It does not redact identifiers or clinical text that could appear in a provider/transport exception.
- The orchestrator converts exception text into `WorkflowError.message` and returns it in retained workflow state (`core/orchestrator.py:265-274`). A caller that persists or logs state could therefore persist provider error text.
- Repair prompts include the attempted model output; if that output repeats sensitive input, it is disclosed in the retry request as well.
- Evaluation and red-team helpers return or print exception details, but reviewed fixtures use fake LLMs and synthetic data.

## API key exposure

Positive controls observed:

- Runtime configuration reads `GEMINI_API_KEY` from environment/`.env`; it is not hardcoded in source (`core/config.py:14-50`).
- `.env` is listed in `.gitignore`; `.env.example` contains a blank key placeholder.
- The reviewed tests use `test-not-a-real-key`; live Gemini tests require both a configured key and `RUN_LIVE_GEMINI_TESTS=1`.
- Error handling replaces the exact configured key string with `[REDACTED]` before application logging.

Residual risk:

- Exact-string replacement is not general secret scrubbing; transformed, partial, or separately emitted credential material would not be removed.
- This checkout currently shows source files as untracked, so the audit cannot establish historical secret exposure from Git history. `.env` contents were intentionally not inspected.
- There is no visible secret-management integration, key rotation policy, or egress restriction in this repository.

## High-risk paths

1. **CRITICAL — Document OCR to Gemini:** full document OCR and metadata are sent without de-identification, then potentially resent during repair.
2. **CRITICAL — Aggregated summary to Gemini:** the summary call combines raw patient conversation, clinical history, risk assessment, and document-derived source text into one request.
3. **CRITICAL — Repeated interview transmission:** every non-empty turn sends the entire accumulated conversation plus a structured copy of collected information. A long interview retransmits prior sensitive content repeatedly.
4. **HIGH — Structuring and risk disclosure:** raw conversations and full structured history—including evidence excerpts and optionally linkable session identifiers—are sent externally without minimization.
5. **HIGH — Error/state propagation:** unredacted provider error detail can be logged or returned to the caller; downstream applications may persist it.
6. **MEDIUM — In-memory state concentration:** `OrchestrationState` can contain raw conversation, serialized interview state, structured clinical history, document findings, and errors. The repository provides no retention/deletion/encryption control for a caller that persists it.

## Critical findings

- There is no actual de-identification layer at the external LLM boundary.
- Full OCR is passed verbatim to Gemini.
- The summary request aggregates the broadest and most sensitive payload.
- Four agents may repeat a sensitive payload in a repair call.
- The generic prompt instruction about patient-identifiable data is not a security control and must not be treated as one.

## Recommended architecture

These are design recommendations only; this audit did not implement them.

1. Put a mandatory privacy gateway immediately before every LLM request. It should detect, redact/tokenize, and minimize identifiers; reject or require a safe fallback when confidence is insufficient.
2. Replace raw conversation forwarding with a minimized, de-identified clinical representation. Do not send both the raw transcript and a structured duplicate unless a documented necessity exists.
3. For documents, perform local or approved pre-processing that extracts only the required clinical fields; avoid sending document headers, identifiers, boilerplate, and full OCR. Use a strict size/field allow-list.
4. Create a single outbound LLM client interface that accepts only an approved, privacy-reviewed payload type. Prevent agents from passing arbitrary strings directly to the SDK wrapper.
5. Do not put raw prior model output in repair prompts. Retry with a constrained, minimized source payload or stop for review.
6. Use structured error codes for user/workflow state. Keep provider exception detail in a protected diagnostic channel after identifier and secret scrubbing.
7. Define persistence boundaries: encryption, access control, retention/deletion, state minimization, audit events without content, and secure document handling. Verify vendor configuration and data-processing terms separately from this code review.
8. Add automated tests that place representative identifiers in chat and OCR, assert that outbound payloads contain no originals, and assert that logs and `WorkflowError` messages contain no sensitive content.

## Files created

- `security/privacy_audit.md`

## Files modified

- None. The application implementation, prompts, agent behavior, tests, and configuration were not changed.
