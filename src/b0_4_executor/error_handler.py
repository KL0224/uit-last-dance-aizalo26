import re
from typing import Tuple, Literal
import duckdb

from .schemas import EmptyQueryError, SecurityViolation, QueryTimeoutError


RECOVERABLE_ERROR_TYPES = {
    "SyntaxError",
    "CatalogError",
    "BinderError",
    "ConversionError",
    "DataError",
    "TimeoutError",
    "SecurityViolation",
    "EmptyQueryError",
}


def classify_error(exc: Exception) -> Tuple[str, bool]:
    """
    Classifies an exception into an error_type and a boolean indicating
    whether the error is recoverable by LLM retry.
    """
    if isinstance(exc, EmptyQueryError):
        return "EmptyQueryError", True

    if isinstance(exc, SecurityViolation):
        return "SecurityViolation", True

    if isinstance(exc, (QueryTimeoutError, TimeoutError, duckdb.InterruptException)):
        return "TimeoutError", True

    if isinstance(exc, duckdb.ParserException):
        return "SyntaxError", True

    if isinstance(exc, duckdb.CatalogException):
        return "CatalogError", True

    if isinstance(exc, duckdb.BinderException):
        return "BinderError", True

    if isinstance(exc, duckdb.ConversionException):
        return "ConversionError", True

    if isinstance(exc, (duckdb.DataError, duckdb.OutOfRangeException)):
        return "DataError", True

    if isinstance(exc, duckdb.PermissionException):
        return "SecurityViolation", True

    if isinstance(exc, (FileNotFoundError, duckdb.IOException)):
        return "DatabaseIOError", False

    if isinstance(exc, duckdb.OutOfMemoryException):
        return "OutOfMemoryError", False

    if isinstance(exc, duckdb.InternalException):
        return "InternalError", False

    # Check for general Python errors
    if isinstance(exc, SyntaxError):
        return "SyntaxError", True

    return "ExecutionError", False


def format_error_message(exc: Exception, error_type: str, timeout_sec: float = 10.0) -> str:
    """
    Cleans and extracts the most actionable error message for LLM retry.
    Strips internal file paths and Python tracebacks, while preserving
    DuckDB line pointers and 'Did you mean' hints.
    """
    if error_type == "TimeoutError":
        return (
            f"Query execution timed out after {timeout_sec:.1f}s. "
            "Please optimize your SQL query (e.g. check for Cartesian joins, missing WHERE clauses, or excessive recursion)."
        )

    if error_type == "EmptyQueryError":
        return "SQL query is empty. Please provide a valid, single SELECT query."

    if error_type == "SecurityViolation":
        msg = str(exc).strip()
        return f"Security Violation: {msg}. Only single read-only SELECT queries are permitted."

    raw_msg = str(exc)

    # Remove Python file paths like C:\foo\bar.py or /foo/bar.py
    cleaned = re.sub(r'File ".*?", line \d+, in .*?\n', "", raw_msg)
    cleaned = re.sub(r"[A-Za-z]:\\[^ \n\r\t:]+", "<path>", cleaned)

    # Strip excessive leading/trailing whitespace
    cleaned = cleaned.strip()

    return cleaned if cleaned else f"{error_type}: An unexpected error occurred during execution."


def determine_route(
    error_type: str,
    is_recoverable: bool,
    retry_count: int,
    max_retries: int
) -> Literal["recoverable", "abstain"]:
    """
    Determines next route:
    - If retry_count >= max_retries: 'abstain' (exhausted retries)
    - If retry_count < max_retries and error is recoverable: 'recoverable'
    - Otherwise: 'abstain'
    """
    if retry_count >= max_retries:
        return "abstain"

    if is_recoverable and error_type in RECOVERABLE_ERROR_TYPES:
        return "recoverable"

    return "abstain"

