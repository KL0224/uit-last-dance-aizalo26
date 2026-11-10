"""Preserve generation evidence independently of parser and gate decisions."""

from dataclasses import asdict, replace
import traceback
from typing import Any

from .types import GenerationDiagnostics


def exception_diagnostics(exc: Exception, base: GenerationDiagnostics | None = None) -> GenerationDiagnostics:
    observed = base or getattr(exc, "diagnostics", None) or GenerationDiagnostics()
    return replace(
        observed,
        failure_kind=observed.failure_kind or "inference_error",
        error_type=type(exc).__name__,
        error_message=str(exc),
        traceback="".join(traceback.format_exception(exc)),
    )


def diagnostics_dict(value: Any) -> dict[str, Any] | None:
    if isinstance(value, Exception):
        return asdict(exception_diagnostics(value))
    observed = getattr(value, "diagnostics", None)
    return asdict(observed) if observed is not None else None
