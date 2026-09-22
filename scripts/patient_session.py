"""Local, terminal-only demo of the patient interview workflow.

This is a development runner, not a patient-facing product or clinical tool.
It uses the configured Gemini-primary/Ollama-fallback pipeline and prints only
the interviewer response and clinician-review summary for each entered turn.
"""

from __future__ import annotations

import sys
from pathlib import Path

# Running ``python scripts/patient_session.py`` makes ``scripts/`` the first
# import location. Add the repository root so the local ``core`` package is
# available without asking users to set PYTHONPATH manually.
PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from core.exceptions import MedicalAIError
from core.orchestrator import MedicalOrchestrator
from core.schemas import PhysicianSummary


_BANNER = """
AI Medical Assistant — local demo

Type a patient message and press Enter. Commands:
  /summary   Show the latest clinician-review summary
  /quit      End this local session

This prototype is for licensed-clinician review only. It does not diagnose,
prescribe, or replace clinical judgment. Do not enter real patient-identifying
information in this development demo.
""".strip()


def _print_summary(summary: PhysicianSummary) -> None:
    print("\n--- Clinician-review summary ---")
    print(f"Overview: {summary.overview}")
    print(f"Attention level: {summary.overall_attention_level.value}")
    for label, values in (
        ("Safety items", summary.safety_items_to_review),
        ("Information gaps", summary.information_gaps),
        ("Questions for clinician", summary.questions_for_clinician),
        ("Document findings", summary.document_derived_findings),
        ("Uncertainties", summary.uncertainties),
    ):
        if values:
            print(f"{label}:")
            for value in values:
                print(f"- {value}")


def main() -> None:
    print(_BANNER)
    try:
        orchestrator = MedicalOrchestrator()
    except MedicalAIError as exc:
        print(f"Unable to start the configured LLM workflow: {exc}")
        return

    while True:
        try:
            message = input("\nPatient> ").strip()
        except (EOFError, KeyboardInterrupt):
            print("\nSession ended.")
            return
        if not message:
            continue
        if message.lower() in {"/quit", "/exit"}:
            orchestrator.clear_session()
            print("Session cleared and ended.")
            return
        if message.lower() == "/summary":
            if orchestrator.state.physician_summary:
                _print_summary(orchestrator.state.physician_summary)
            else:
                print("No clinician-review summary is available yet.")
            continue

        state = orchestrator.handle_patient_message(message)
        if state.errors:
            print(f"Workflow status: {state.workflow_status.value}")
            print(f"Safe error code: {state.errors[-1].message}")
            continue
        interview_state = state.interview_state or {}
        history = interview_state.get("conversation_history", [])
        if history and history[-1].get("role") == "assistant":
            print(f"\nAssistant> {history[-1]['content']}")
        if state.physician_summary:
            _print_summary(state.physician_summary)


if __name__ == "__main__":
    main()
