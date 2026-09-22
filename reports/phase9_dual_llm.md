# Phase 9 — Dual LLM Provider

## Architecture

Primary: Gemini  
Secondary: Ollama + Gemma 3 12B  
Fallback: Automatic only for supported Gemini quota/transient failures.

`LLMClient` remains the shared Phase 8 privacy-gated facade. It prepares a `SafeLLMPayload` before calling the centralized `FallbackLLMProvider`. The router calls Gemini first, and on an eligible classified failure sends the exact same safe request to local Ollama once. Gemini and Ollama transports accept `SafeLLMPayload`, not raw application strings. Both providers return text to the same shared JSON parsing and Pydantic validation path.

## Provider Tests

Gemini: PASS  
Ollama: PASS  
Provider abstraction: PASS  
Provider routing: PASS  
Automatic fallback: PASS  
Fallback disabled: PASS  
No fallback loop: PASS

Mocked coverage verifies Gemini success does not call Ollama; 429, 500/503-class transient failures, and timeout-class failures use one fallback; authentication, safety, and request errors do not. A failing Ollama provider stops after one attempt.

## Privacy

Gemini privacy: PASS  
Ollama privacy: PASS  
Fallback privacy: PASS  
No raw patient identifiers: PASS

Captured fallback tests verify that synthetic name, phone, and MRN values are absent from the Ollama request while clinical context remains. A privacy-gateway failure results in zero Gemini and zero Ollama requests. Gemini credentials are not used in the Ollama request body.

## Safety

Risk preservation: PASS  
Diagnosis prevention: PASS  
Medication safety: PASS  
Hallucination prevention: PASS  
Contradiction preservation: PASS  
Uncertainty preservation: PASS  
Source attribution: PASS

The existing deterministic risk layer remains upstream/authoritative. A Gemini rate-limit during risk processing followed by mocked Ollama output retains urgent attention and risk flags. Existing Phase 7 synthetic red-team checks remain green.

## Regression

Phase 1: PASS  
Phase 2: PASS  
Phase 3: PASS  
Phase 4: PASS  
Phase 5: PASS  
Phase 6: PASS  
Phase 7: PASS  
Phase 8: PASS  
Phase 9: PASS

## Tests

Total: 190  
Passed: 187  
Failed: 0  
Skipped: 3

The skipped tests are two optional live Gemini tests plus one optional local-Ollama test. The local-Ollama test was attempted with a synthetic prompt and skipped because the local service was unavailable. No live Gemini call or quota-consuming fallback test was run. The explicit Phase 8 privacy suite passed: 39 passed.

## Gemini Benchmark

Not run. No live Gemini benchmark values were measured in this implementation run, so no extraction, hallucination, safety, risk, attribution, contradiction, uncertainty, or workflow metrics are reported as provider-specific values.

## Ollama Benchmark

Not run. No live local Ollama benchmark values were measured in this implementation run, so no extraction, hallucination, safety, risk, attribution, contradiction, uncertainty, or workflow metrics are reported as provider-specific values.

## Files Created

- `core/llm_provider.py`
- `tests/test_llm_provider.py`
- `tests/test_gemini_provider.py`
- `tests/test_ollama_provider.py`
- `tests/test_provider_router.py`
- `tests/test_fallback.py`
- `tests/test_fallback_privacy.py`
- `reports/phase9_dual_llm.md`

## Files Modified

- `core/config.py`
- `core/llm_client.py`
- `agents/structuring_agent.py`
- `agents/risk_agent.py`
- `agents/document_agent.py`
- `agents/summary_agent.py`
- `.env.example`
- `README.md`

## Remaining Issues

- The optional local-Ollama test was attempted with synthetic data but the local service was unavailable; a running local Ollama service with `gemma3:12b` is required for that integration check.
- The optional live Gemini test requires explicit opt-in and was not run.
- Deterministic application-level identifier detection has the limitations documented in the Phase 8 report. This implementation does not establish regulatory compliance, provider data-handling guarantees, or clinical validation.
