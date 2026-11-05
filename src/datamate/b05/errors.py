"""Error taxonomy and custom exceptions for B0.5 Basic Output Gate."""

from dataclasses import dataclass
from typing import Optional


# Standard Error & Reason Codes (B0.5 Specification §5, §11)
class ErrorCode:
    VALID_RESULT = "VALID_RESULT"
    VALID_RESULT_AFTER_RETRY = "VALID_RESULT_AFTER_RETRY"
    CONFIRMED_MISSING_EVIDENCE = "CONFIRMED_MISSING_EVIDENCE"

    # Retryable errors (attempt 0 -> retry 1)
    SQL_SYNTAX = "SQL_SYNTAX"
    SCHEMA_ERROR = "SCHEMA_ERROR"
    SQL_TYPE_ERROR = "SQL_TYPE_ERROR"
    SCALAR_SHAPE_MISMATCH = "SCALAR_SHAPE_MISMATCH"
    OUTPUT_TYPE_ERROR = "OUTPUT_TYPE_ERROR"

    # Non-retryable / specific termination codes
    EMPTY_RESULT = "EMPTY_RESULT"
    NULL_RESULT = "NULL_RESULT"
    QUERY_TIMEOUT = "QUERY_TIMEOUT"
    TRUNCATED_RESULT = "TRUNCATED_RESULT"
    SECURITY_VIOLATION = "SECURITY_VIOLATION"
    EXECUTOR_FAILURE = "EXECUTOR_FAILURE"
    CONTRACT_ERROR = "CONTRACT_ERROR"
    MISSING_EVIDENCE = "MISSING_EVIDENCE"
    UNKNOWN_ERROR = "UNKNOWN_ERROR"
    RETRY_EXHAUSTED = "RETRY_EXHAUSTED"
    TIME_BUDGET_EXHAUSTED = "TIME_BUDGET_EXHAUSTED"
    CONFLICTING_EVIDENCE = "CONFLICTING_EVIDENCE"
    TABLE_SHAPE_ERROR = "TABLE_SHAPE_ERROR"
    FORMAT_AMBIGUOUS = "FORMAT_AMBIGUOUS"


@dataclass
class ErrorClassification:
    code: str
    retryable: bool
    evidence: str
    safe_feedback: str


class GateError(Exception):
    """Base exception for B0.5 Gate module."""
    def __init__(self, message: str, code: str = ErrorCode.UNKNOWN_ERROR):
        super().__init__(message)
        self.code = code
        self.message = message


class ContractError(GateError):
    """Raised when GateRequest or external input violates the data contract."""
    def __init__(self, message: str):
        super().__init__(message, code=ErrorCode.CONTRACT_ERROR)


class ValidationError(GateError):
    """Raised when query execution result fails shape or value validation."""
    def __init__(self, message: str, code: str = ErrorCode.OUTPUT_TYPE_ERROR):
        super().__init__(message, code=code)


class FormattingError(GateError):
    """Raised when typed value cannot be formatted strictly to 1 of 9 official types."""
    def __init__(self, message: str, code: str = ErrorCode.OUTPUT_TYPE_ERROR):
        super().__init__(message, code=code)


class OutputWriteError(GateError):
    """Raised when submission or audit log file writing encounters an unrecoverable I/O error."""
    def __init__(self, message: str):
        super().__init__(message, code="OUTPUT_WRITE_ERROR")

