"""
Module B0.4: DuckDB Read-Only Execution Engine
Baseline B0 (Direct Text-to-SQL)
"""

from .schemas import (
    ExecutionRequest,
    ExecutionResponse,
    EmptyQueryError,
    SecurityViolation,
    QueryTimeoutError,
    normalize_value,
)
from .sanitizer import extract_clean_sql, validate_read_only_sql
from .error_handler import (
    classify_error,
    determine_route,
    enrich_error_with_schema,
    format_error_message,
)
from .engine import execute_query

__all__ = [
    "ExecutionRequest",
    "ExecutionResponse",
    "EmptyQueryError",
    "SecurityViolation",
    "QueryTimeoutError",
    "normalize_value",
    "extract_clean_sql",
    "validate_read_only_sql",
    "classify_error",
    "determine_route",
    "enrich_error_with_schema",
    "format_error_message",
    "execute_query",
]

