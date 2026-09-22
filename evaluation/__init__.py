"""Deterministic synthetic evaluation tools for the medical AI prototype."""


def run_evaluation(*, write_reports: bool = False):
    """Lazily import the runner so ``python -m evaluation.runner`` is clean."""
    from evaluation.runner import run_evaluation as _run_evaluation

    return _run_evaluation(write_reports=write_reports)


__all__ = ["run_evaluation"]
