# Cliniqo — AI Medical Assistant & Health Vault

Prototype assistive layer for licensed clinicians. It identifies, structures, and summarizes information for physician review. It does **not** diagnose, prescribe, recommend medication changes, or replace a physician.

This repository contains the foundation plus the **Interview Agent** and
**Clinical Structuring Agent**. The structuring agent converts a supplied
conversation (including Phase 1 `InterviewState`/`InterviewTurnResult`) into a
Pydantic-validated, evidence-grounded `ClinicalHistory`; it does not diagnose.
The **Safety/Risk Agent** consumes that validated history and flags reported
safety signals for clinician review; it does not diagnose or direct treatment.
The **Document Intelligence Agent** receives OCR text from an external OCR
pipeline and extracts document-derived information with source evidence.
The **Physician Summary Agent** organizes validated upstream outputs into a
concise, clinician-facing summary without creating new clinical conclusions.
The **Medical Orchestrator** coordinates these five agents, retains validated
session state, and exposes failures without fabricating a completed workflow.

## Scope

| Layer | Status |
| --- | --- |
| LLM client, config, schemas, prompts | Implemented |
| Interview Agent | Implemented |
| Clinical Structuring Agent | Implemented (Phase 2) |
| Safety/Risk Agent | Implemented (Phase 3) |
| Document Intelligence Agent | Implemented (Phase 4) |
| Physician Summary Agent | Implemented (Phase 5) |
| Multi-Agent Orchestrator | Implemented (Phase 6) |
| Synthetic Evaluation / Red Team | Implemented (Phase 7) |
| Privacy Gateway / LLM boundary protection | Implemented (Phase 8) |
| Groq primary + Ollama fallback / hardened summary | Implemented (Phase 10) |
| Frontend / UI | Out of scope |
| Backend / API | FastAPI implemented |
| Database | Supabase session persistence implemented |
| OCR | Out of scope |
| NLP / ASR | Out of scope |

## Installation

Requires Python 3.10 or newer.

### Virtual environment

```bash
cd ai_medical_assistant
python3 -m venv .venv
source .venv/bin/activate
```

On Windows:

```bash
python -m venv .venv
.venv\Scripts\activate
```

### Dependencies

```bash
pip install -r requirements.txt
```

## Environment setup

Secrets live in environment variables. Never commit `.env` or paste API keys into source files.

1. Copy the example file:

   ```bash
   cp .env.example .env
   ```

2. Open `.env` and set `GROQ_API_KEY` to a Groq API key. Do not commit that file.

Optional variables (defaults are in `core/config.py`):

- `GROQ_MODEL` — default `openai/gpt-oss-20b`
- `LLM_TIMEOUT_SECONDS` — default `30`
- `LLM_TEMPERATURE` — default `0.2`
- `SUPABASE_URL` — Supabase project URL
- `SUPABASE_SERVICE_ROLE_KEY` — server-only Supabase service-role key; never expose it to the frontend
- `SUPABASE_REQUIRED` — set to `true` to fail startup when Supabase is not configured; default `false` uses an in-memory development fallback

### Supabase database setup

Run the SQL in `supabase/migrations/202609160001_create_clinical_sessions.sql`
in the Supabase SQL editor or with the Supabase CLI. Then set the three
Supabase variables in `.env` and start the API:

```bash
uvicorn api.main:app --reload --port 8000
```

The API stores the complete validated `OrchestrationState` as a JSONB session
snapshot. The service-role key is used only by the backend, and row-level
security is enabled with no browser policy. `/health` reports
`persistence: "supabase"` when connected, or `persistence: "memory"` when the
development fallback is active.

### Versioned API surface

The new backend surface is available under `/api/v1` and is documented by
FastAPI at `/docs`:

- Patients: `POST /api/v1/patients`, `GET /api/v1/patients/{patient_id}`
- Sessions: `POST /api/v1/sessions`, `GET /api/v1/sessions/{session_id}`, `POST /api/v1/sessions/{session_id}/complete`
- Conversation: `POST` and `GET /api/v1/sessions/{session_id}/messages`
- Clinical data: `/medical-history`, `/medications`, `/allergies`, `/family-history`, `/lifestyle`
- Documents/OCR: `/api/v1/sessions/{session_id}/documents`, `/api/v1/documents/{document_id}/ocr`
- Safety: `POST` and `GET /api/v1/sessions/{session_id}/red-flags`
- Summary: `POST /api/v1/sessions/{session_id}/generate-summary`, `GET /api/v1/sessions/{session_id}/summary`
- Doctor case: `GET` and `PUT /api/v1/doctor/cases/{session_id}`
- Consent: `POST` and `GET /api/v1/sessions/{session_id}/consent`

The original `/api/session` endpoints remain available for the existing static
frontend while the frontend is migrated to the versioned contracts.

## Running tests

```bash
source .venv/bin/activate
pytest
```

- Configuration and client-initialization tests always run.
- Live Groq calls run only when both `GROQ_API_KEY` is set and
  `RUN_LIVE_GROQ_TESTS=1`. They are skipped by default, so normal tests do
  not consume provider quota.

## Local patient-flow demo

The repository does not include a frontend, but you can exercise the complete
interactive patient workflow from a terminal after configuring `.env`:

```bash
source .venv/bin/activate
python scripts/patient_session.py
```

Type messages as a synthetic patient. The runner shows the Interview Agent's
next question and the current clinician-review summary. Use `/summary` to show
the latest summary and `/quit` to clear the in-memory session and exit. It is a
development demo only: do not enter real patient-identifying information.

## How the AI architecture works

```
agents/          Interview, structuring, safety/risk, document, and summary agents
core/orchestrator Stateful coordinator for the five agents
core/llm_client  Privacy-gated provider facade (text + JSON)
core/llm_provider Groq primary, local Ollama fallback transport/routing
core/config      Environment-driven settings
core/schemas     Pydantic models for structured, clinician-review outputs
core/prompts     Shared safety instructions
core/exceptions  Typed errors (missing key, connection, parse failures)
```

1. **Config** loads `GROQ_API_KEY` via `python-dotenv` / pydantic-settings. A missing key raises `MissingAPIKeyError`.
2. **LLMClient** is the shared, privacy-gated provider facade. It supports plain text and structured JSON (optionally validated with a Pydantic model), keeps Groq as the primary provider, and maps provider errors to safe structured codes.
3. **Schemas** (`PatientMessage`, `ClinicalHistory`, `RiskFlag`, `DocumentExtraction`, `PhysicianSummary`) describe assistive payloads. They include an explicit clinician-review flag and do not encode diagnoses or orders.
4. **InterviewAgent** gathers a conversation and tracks Phase 1 uncertainty.
   **StructuringAgent** accepts that state/result or raw turns, requests
   `ClinicalHistory` structured output, validates/repairs it, then removes any
   fact that cannot be grounded in a patient turn.
5. **RiskAgent** uses a hybrid safety layer: small transparent deterministic
   rules flag selected reported urgent patterns (for example chest pain with
   breathlessness), while the LLM can add evidence-grounded contextual review
   items and relevant information gaps. Final validation requires evidence,
   preserves contradictions and uncertainty, uses only `routine`, `attention`,
   or `urgent`, and rejects diagnosis or medication-advice output. Deterministic
   flags cannot be downgraded by the LLM.
6. **DocumentAgent** starts after OCR. It accepts `DocumentInput` metadata and
   OCR text—not images or PDFs—and returns a `DocumentExtraction` containing
   source-evidenced medications, document-mentioned diagnoses, laboratory
   values, dates, symptoms, allergies, procedures, observations, and
   document-reported follow-up text. It never merges those facts with patient
   history; a later summary layer may do so.
7. **SummaryAgent** accepts `SummaryInput` (or the individual native Phase 2–4
   models) and produces `PhysicianSummary`. It gives structured history
   priority, labels uploaded-document findings as document-derived, preserves
   risk flags and their attention level, and retains contradictions and
   uncertainty. Its post-generation validator rejects unsupported diagnoses,
   medication advice, laboratory/medication/allergy hallucinations, and risk
   downgrades. It is not an application orchestrator.
8. **MedicalOrchestrator** coordinates the native agent interfaces through an
   `OrchestrationState` model. Agents are dependency-injected for deterministic
   testing. For every patient turn it runs Interview → Structuring → Risk →
   Summary, with Document extraction included only when new `DocumentInput`
   OCR text is supplied. It retains state across turns, deduplicates documents,
   and keeps validated outputs available when a later stage fails.

### Phase 6 workflow

```text
Patient message
      │
      ▼
Interview Agent → Structuring Agent → Risk Agent ──────────┐
      │                                                     │
      │      new OCR document?                              ▼
      └───────────── yes → Document Agent → Summary Agent → Physician Summary
                          no ──────────────────────────────┘
```

The document path is conditional: without new OCR input, the Document Agent is
not called. On a document failure, patient-derived history and risk assessment
remain available, the document is not represented as extracted, and state is
returned as `partial_failure` with a visible stage error. A failed structuring,
risk, or summary stage likewise cannot be presented as a completed workflow.

Before a completed state is returned, the orchestrator verifies that a risk
assessment exists for structured history, urgent attention was not downgraded,
risk flags remain represented in the summary, document-source attribution is
retained, and the final summary remains non-diagnostic and free of medication
advice. Unit tests use dependency injection and fake agents; live Groq calls
remain opt-in via `RUN_LIVE_GROQ_TESTS=1`.

### Phase 7 evaluation

The `evaluation/` package supplements—not replaces—the unit tests. It runs a
deterministic synthetic dataset of 30 scenarios through the existing pipeline
with injected mock LLM outputs. It also runs 10 red-team attacks against
grounding, diagnosis prevention, medication-advice prevention, risk
preservation, source attribution, contradictions, and OCR uncertainty.

```bash
python -m evaluation.runner
```

This command writes reproducible, machine-readable results to
`evaluation/results/latest.json` and a companion report to
`evaluation/results/latest_report.md`. Measured metrics include structured
extraction accuracy, hallucination rate, safety compliance, risk preservation,
source attribution, contradiction and uncertainty preservation, and workflow
reliability. No evaluation scenario uses real patient data or live provider calls.

The red-team suite intentionally tries prompt injection, diagnosis demands,
medication advice, unsupported vital signs/medications/laboratories, empty
history completion, and urgent-risk downgrades. These tests are software
quality checks for the defined synthetic cases; they are not clinical
validation, clinical safety certification, or diagnostic-accuracy measurement.

## Privacy Architecture

Every production-bound LLM prompt passes through the application privacy
gateway before it reaches the shared provider client. The gateway deterministically
detects common identifiers, replaces them with non-reversible generic tokens,
minimizes identity-only content, and validates the safe payload. The token
mapping is never created or sent to Groq or Ollama. Each agent applies the gateway so
dependency-injected LLMs also receive de-identified content; `LLMClient` applies
it again immediately before the only provider call. A privacy failure blocks
the request rather than sending the raw prompt.

```text
Patient
  ↓
Application
  ↓
Privacy Gateway
  ↓
De-identification
  ↓
Data Minimization
  ↓
Validated LLM Payload
  ↓
Groq or local Ollama
```

The gateway scans free text, conversation evidence, OCR text, and serialized
metadata for common names, contact details, addresses, dates of birth, medical
and patient identifiers, account/insurance identifiers, document identifiers,
URLs, and social-security-style identifiers. It retains clinical symptoms,
duration, medicines, allergies, risk evidence, and laboratory values when those
do not themselves contain identifiers. Summary prompts omit the duplicate raw
patient transcript when validated structured history, risk, and document
findings are available. Repair prompts follow the same gateway path.

Logs use stage/status and safe error codes rather than prompts, OCR, model
responses, or provider exception text. `MedicalOrchestrator.clear_session()`
releases its retained in-memory conversation and derived state when a caller no
longer needs it. The project does not create a database or persistence layer.

Privacy tests use synthetic identifiers only and capture outbound test prompts
for every agent, including document OCR, summary, and repair paths. Deterministic
pattern detection cannot guarantee that every identifier will be recognized.
This application-level protection does not establish regulatory compliance,
clinical validation, certification, vendor data-handling terms, or
infrastructure-level encryption/access controls. Do not use real patient data
in tests or prompts.

## Dual LLM Architecture

Groq is the primary cloud provider. Local Ollama using `gemma3:12b` is the
optional secondary provider, never the default. The application first prepares
a privacy-safe payload, then asks Groq. Only a classified Groq rate-limit,
temporary 5xx/unavailability, timeout, or existing supported request failure
may cause exactly one retry with the same safe payload through Ollama.

```text
Normal:   Application → Privacy Gateway → Groq

Fallback: Application → Privacy Gateway → Groq
                                      ↓ eligible quota/transient failure
                                   Ollama → Gemma 3 12B
```

Invalid credentials, malformed requests, privacy-gateway failures, safety
rejections, schema/application errors, and configuration errors do not trigger
fallback. If fallback is disabled (`LLM_FALLBACK_ENABLED=false`) or local Ollama
is unavailable, the request returns a safe structured failure; it never loops
or retries Groq again.

Both providers consume only `SafeLLMPayload` values from the existing Privacy
Gateway. The Groq API key is used only by the Groq provider and is never placed
in an Ollama request. JSON parsing and Pydantic validation stay in the shared
client for either provider. Ollama remains optional: Groq-only deployments set
`LLM_FALLBACK_ENABLED=false` and do not require a running local server.

The Summary Agent uses a strict Pydantic schema and validates every output
against validated Phase 2–4 inputs. Final summary provenance uses only the
enumerated `clinical_history`, `risk_assessment`, `document`, or
`patient_conversation` categories; it never stores raw patient/OCR evidence as
provenance. Unsupported facts, provenance labels, diagnoses, medication advice,
and risk downgrades are rejected with one bounded repair attempt.

## Medical safety

Outputs are drafts for licensed clinician review. Do not use real patient-identifiable data in tests or prompts.

Risk flagging identifies reported indicators for review; it does not establish
the cause of those indicators and is not a diagnosis. The deterministic rules
are deliberately small and are not a complete triage system. The LLM is a
constrained contextual assistant, not a clinical decision-maker.

Document extraction is deliberately tolerant of imperfect OCR but does not
silently correct it: ambiguous interpretations are marked `uncertain` and keep
their OCR source text. Values without supporting OCR evidence are removed. A
document's explicit diagnosis is represented only as a diagnosis *mentioned by
the document*, never as an independent AI diagnosis. Document-reported
follow-up instructions are preserved as source text, while AI recommendations
and prescriptions are rejected.

The Document Intelligence Agent extracts information from OCR text. It does not
independently diagnose or prescribe treatment. OCR itself is outside this
project's scope.

The Physician Summary Agent organizes information from upstream agents and does
not independently diagnose or prescribe treatment. It keeps patient-reported
concerns distinct, identifies document-derived facts, and does not silently
resolve source conflicts. Document-derived diagnoses remain explicitly labeled
as mentions in an uploaded document rather than AI diagnoses.

**This prototype is not clinically validated and must not be used as a
substitute for professional medical judgment.**
