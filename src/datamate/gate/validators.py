"""Execution and Result Validator for B0.5 Basic Output Gate (DataMate 2026)."""

import math
from typing import List

from .contracts import AnswerType, ExecutionStatus, GateRequest, ValidationResult
from .errors import ErrorCode


def validate_execution(request: GateRequest) -> ValidationResult:
    """Validate query execution status, shape, non-finite values, and null constraints."""
    execution = request.execution
    warnings: List[str] = [str(w) for w in execution.warnings]

    # 1. Execution status check
    if execution.status == ExecutionStatus.ERROR:
        err_msg = execution.error.message if execution.error else "Unknown execution error"
        return ValidationResult(
            passed=False,
            error_code=ErrorCode.EXECUTOR_FAILURE,
            details=f"Execution failed: {err_msg}",
            warnings=warnings,
        )

    if execution.status == ExecutionStatus.NOT_EXECUTED:
        return ValidationResult(
            passed=False,
            error_code="NOT_EXECUTED",
            details="Query was not executed",
            warnings=warnings,
        )

    # 2. Truncated result check
    if execution.truncated:
        return ValidationResult(
            passed=False,
            error_code=ErrorCode.TRUNCATED_RESULT,
            details="Execution result was truncated to preview rows",
            warnings=warnings,
        )

    # 3. Generation must exist
    if request.generation is None:
        return ValidationResult(
            passed=False,
            error_code=ErrorCode.CONTRACT_ERROR,
            details="Missing generation in request",
            warnings=warnings,
        )

    answer_type = request.generation.answer_type
    rows = execution.rows
    columns = execution.columns

    # Check row_count consistency if provided
    if execution.row_count is not None and len(rows) != execution.row_count:
        warnings.append(f"Row count mismatch: len(rows)={len(rows)} vs row_count={execution.row_count}")

    # 4. Shape & Content Validation by Answer Type
    # Case A: Scalar types (number, percent, string, date, boolean)
    if answer_type in (
        AnswerType.NUMBER,
        AnswerType.PERCENT,
        AnswerType.STRING,
        AnswerType.DATE,
        AnswerType.BOOLEAN,
    ):
        if len(rows) == 0:
            return ValidationResult(
                passed=False,
                error_code=ErrorCode.EMPTY_RESULT,
                details=f"Scalar type '{answer_type}' expected 1 row, got 0 rows",
                warnings=warnings,
            )

        if len(rows) > 1:
            return ValidationResult(
                passed=False,
                error_code=ErrorCode.SCALAR_SHAPE_MISMATCH,
                details=f"Scalar type '{answer_type}' expected 1 row, got {len(rows)} rows",
                warnings=warnings,
            )

        first_row = rows[0]
        if not isinstance(first_row, list) or len(first_row) == 0:
            return ValidationResult(
                passed=False,
                error_code=ErrorCode.SCALAR_SHAPE_MISMATCH,
                details=f"Scalar type '{answer_type}' expected at least 1 column in row, got 0",
                warnings=warnings,
            )
        if len(first_row) > 1:
            warnings.append(f"Scalar type '{answer_type}' expected 1 column, got {len(first_row)}; extracted first column")

        candidate = first_row[0]
        if candidate is None:
            return ValidationResult(
                passed=False,
                error_code=ErrorCode.NULL_RESULT,
                details=f"Scalar result for '{answer_type}' is NULL",
                warnings=warnings,
            )

        if isinstance(candidate, float) and (math.isnan(candidate) or math.isinf(candidate)):
            return ValidationResult(
                passed=False,
                error_code=ErrorCode.OUTPUT_TYPE_ERROR,
                details=f"Scalar result for '{answer_type}' is NaN/Inf",
                warnings=warnings,
            )

        if answer_type == AnswerType.BOOLEAN and not isinstance(candidate, bool):
            return ValidationResult(
                passed=False,
                error_code=ErrorCode.OUTPUT_TYPE_ERROR,
                details=f"Expected boolean True/False, got {type(candidate).__name__}",
                warnings=warnings,
            )

        return ValidationResult(
            passed=True,
            normalized_candidate=candidate,
            warnings=warnings,
        )

    # Case B: List type
    elif answer_type == AnswerType.LIST:
        clean_items = []
        for r_idx, row in enumerate(rows):
            if not isinstance(row, list) or len(row) == 0:
                return ValidationResult(
                    passed=False,
                    error_code=ErrorCode.SCALAR_SHAPE_MISMATCH,
                    details=f"List row {r_idx} must have at least 1 column, got 0",
                    warnings=warnings,
                )
            if len(row) > 1 and r_idx == 0:
                warnings.append(f"List row expected 1 column, got {len(row)}; extracted first column")
            item = row[0]
            if item is None:
                return ValidationResult(
                    passed=False,
                    error_code=ErrorCode.NULL_RESULT,
                    details=f"List row {r_idx} is NULL",
                    warnings=warnings,
                )
            if isinstance(item, float) and (math.isnan(item) or math.isinf(item)):
                return ValidationResult(
                    passed=False,
                    error_code=ErrorCode.OUTPUT_TYPE_ERROR,
                    details=f"List row {r_idx} is NaN/Inf",
                    warnings=warnings,
                )
            clean_items.append(item)

        if len(clean_items) == 0:
            policy = request.generation.answer_semantics.empty_set_policy
            if policy != "allowed":
                return ValidationResult(
                    passed=False,
                    error_code=ErrorCode.EMPTY_RESULT,
                    details="List result is empty and empty_set_policy != 'allowed'",
                    warnings=warnings,
                )

        return ValidationResult(
            passed=True,
            normalized_candidate=clean_items,
            warnings=warnings,
        )

    # Case C: Table type
    elif answer_type == AnswerType.TABLE:
        # Tự động unwrap bảng 1x1 về kiểu vô hướng (scalar) phù hợp
        if len(rows) == 1 and len(columns) == 1:
            val = rows[0][0]
            val_str = str(val).strip()
            import re
            q_text = (request.question.question if request.question else "").lower()
            if re.match(r"^\d{4}-\d{2}(-\d{2})?$", val_str):
                request.generation.answer_type = AnswerType.DATE
            elif any(k in q_text for k in ["%", "phần trăm", "phan tram", "tỉ lệ", "ti le", "tăng", "giảm", "tang", "giam"]):
                request.generation.answer_type = AnswerType.PERCENT
            elif isinstance(val, (int, float)) or (isinstance(val, str) and re.match(r"^-?\d+(\.\d+)?$", val_str)):
                request.generation.answer_type = AnswerType.NUMBER
            else:
                request.generation.answer_type = AnswerType.STRING
            return validate_execution(request)

        # Tự động unwrap bảng 2 cột của câu hỏi danh sách/Top-N về List
        q_text = (request.question.question if request.question else "").lower()
        table_explicit_keywords = (
            "table", "bảng", "bang", "cái bảng", "cho bảng",
            "kèm", "kem", "và số", "va so", "mỗi người", "moi nguoi",
            "từng người", "tung nguoi", "số nợ của từng", "con no bao nhieu", "còn nợ bao nhiêu",
        )
        list_indicators = (
            "top", "món", "mon", "mặt hàng", "mat hang", "sản phẩm", "san pham",
            "khách", "khach", "những", "nhung", "liệt kê", "liet ke", "danh sách", "danh sach", "ai",
        )
        if (
            len(rows) > 1
            and len(columns) == 2
            and any(k in q_text for k in list_indicators)
            and not any(k in q_text for k in table_explicit_keywords)
        ):
            request.generation.answer_type = AnswerType.LIST
            return validate_execution(request)

        if not columns or not all(isinstance(c, str) and c.strip() for c in columns):
            return ValidationResult(
                passed=False,
                error_code=ErrorCode.TABLE_SHAPE_ERROR,
                details="Table columns must be non-empty list of non-empty strings",
                warnings=warnings,
            )

        num_cols = len(columns)
        for r_idx, row in enumerate(rows):
            if not isinstance(row, list) or len(row) != num_cols:
                return ValidationResult(
                    passed=False,
                    error_code=ErrorCode.TABLE_SHAPE_ERROR,
                    details=f"Table row {r_idx} width {len(row) if isinstance(row, list) else 0} != column count {num_cols}",
                    warnings=warnings,
                )
            for c_idx, cell in enumerate(row):
                if cell is None:
                    return ValidationResult(
                        passed=False,
                        error_code=ErrorCode.NULL_RESULT,
                        details=f"Table row {r_idx}, col {c_idx} is NULL",
                        warnings=warnings,
                    )
                if isinstance(cell, float) and (math.isnan(cell) or math.isinf(cell)):
                    return ValidationResult(
                        passed=False,
                        error_code=ErrorCode.OUTPUT_TYPE_ERROR,
                        details=f"Table row {r_idx}, col {c_idx} is NaN/Inf",
                        warnings=warnings,
                    )

        if len(rows) == 0:
            policy = request.generation.answer_semantics.empty_set_policy
            if policy != "allowed":
                return ValidationResult(
                    passed=False,
                    error_code=ErrorCode.EMPTY_RESULT,
                    details="Table rows empty and empty_set_policy != 'allowed'",
                    warnings=warnings,
                )

        candidate_table = {"columns": columns, "rows": rows}
        return ValidationResult(
            passed=True,
            normalized_candidate=candidate_table,
            warnings=warnings,
        )

    # Case D: unanswerable & abstain
    elif answer_type in (AnswerType.UNANSWERABLE, AnswerType.ABSTAIN):
        return ValidationResult(
            passed=True,
            normalized_candidate=None,
            warnings=warnings,
        )

    else:
        return ValidationResult(
            passed=False,
            error_code=ErrorCode.CONTRACT_ERROR,
            details=f"Unsupported answer_type: {answer_type}",
            warnings=warnings,
        )
