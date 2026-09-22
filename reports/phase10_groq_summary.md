# Phase 10 — Groq Migration and Summary Hardening

## Status

- Primary provider: Groq.
- Default Groq model: `openai/gpt-oss-20b` (configurable through `GROQ_MODEL`).
- Secondary provider: local Ollama using `gemma3:12b`.
- Routing: one Groq attempt followed by at most one Ollama attempt for an eligible provider failure. No retry loop exists.
- Privacy boundary: unchanged. `PrivacyGateway` creates the sole `SafeLLMPayload` accepted by both provider transports.

## Groq integration

`GroqProvider` uses Groq's OpenAI-compatible chat-completions endpoint and requires `GROQ_API_KEY` from environment-driven `Settings`. The key is not stored in source, included in request JSON, logged, or sent to Ollama. JSON requests use Groq JSON-object mode; shared JSON parsing and Pydantic validation stay in `LLMClient`.

## Summary Agent root causes and changes

The prior unsupported-provenance failure had two causes:

1. The final composition path copied a raw upstream patient excerpt into `PhysicianSummary.source_evidence`, even though this field was validated as a source-category map.
2. The prompt did not enumerate the permitted provider provenance labels, so a model could emit labels such as `patient` or `clinical_assessment` that did not match the existing source categories.

The unsupported-facts failure was caused by a token-only prose validator rejecting harmless connective provider wording (for example, `patient reports`) alongside unsafe content. The validator still rejects non-grounded clinical terms, diagnosis assertions, medication advice, invented allergy status, and unsupported values.

Phase 10 makes provenance a closed `SummarySourceType` enum:

- `clinical_history`
- `risk_assessment`
- `document`
- `patient_conversation`

The Summary prompt enumerates these labels. Invalid labels are rejected and are never silently relabeled. Provider-supplied provenance keys must resolve to a real summary field/fact ID, and the cited text must be supported by the cited source category. Final deterministic source entries use stable field-level fact IDs and source categories; raw patient/OCR excerpts are not copied into final provenance.

Pydantic validation remains the source of truth. Controlled repair remains bounded to one repair request and follows the same Privacy Gateway path. Risk attention cannot be downgraded; deterministic risk flags, contradictions, and OCR uncertainty remain preserved during final composition.

## Tests and verification

Commands run:

```bash
.venv/bin/python -m compileall agents core evaluation tests scripts
.venv/bin/pytest -q tests/test_privacy.py tests/test_fallback_privacy.py
.venv/bin/pytest -q
RUN_LIVE_OLLAMA_TESTS=1 .venv/bin/pytest -q tests/test_ollama_provider.py::test_optional_live_ollama_chat_uses_synthetic_prompt
```

Results:

- Collected: 199
- Passed: 196
- Failed: 0
- Skipped: 3 opt-in live-provider tests
- Phase 8 privacy and outbound-payload regression suite: passed
- Local Ollama service/model check: passed; `gemma3:12b` responded to a synthetic non-clinical request

Added/updated coverage includes Groq request privacy, Groq HTTP failure classification, Groq-to-Ollama one-way routing, bounded fallback, Summary enum provenance, invalid provenance rejection, provenance-reference grounding, raw-excerpt prevention, and Groq/Ollama Summary contract parity.

## Live end-to-end result and limitation

The requested full synthetic Groq-rate-limit-to-Ollama workflow was started, but the local workflow did not return a final state before the tool session closed. It is therefore **inconclusive**, not a pass. The bounded Ollama transport check passed separately.

`GROQ_API_KEY` is not configured in the current environment, so live Groq-primary end-to-end verification could not be run. Add it to `.env` and use `LLM_PRIMARY_PROVIDER=groq` before running the patient-session demo. This project is not clinically validated, does not establish diagnostic accuracy or regulatory compliance, and does not guarantee patient privacy. Use synthetic, non-identifying test data only.
