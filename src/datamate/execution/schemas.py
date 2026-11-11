import datetime
import decimal
import math
from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field

try:
    import numpy as np
except ImportError:
    np = None

try:
    import pandas as pd
except ImportError:
    pd = None


class EmptyQueryError(Exception):
    """Raised when the SQL query is empty or only contains comments/whitespace."""
    pass


class SecurityViolation(Exception):
    """Raised when a non-read-only or forbidden SQL command is detected."""
    pass


class QueryTimeoutError(Exception):
    """Raised when a query exceeds the configured timeout."""
    pass


class ExecutionRequest(BaseModel):
    question_id: str = Field(..., description="ID của câu hỏi để ghi nhận vào JSONL và error logs")
    db_path: str = Field(..., description="Đường dẫn tới file .duckdb hoặc thư mục dữ liệu đã cache từ B0.1")
    sql_query: str = Field(..., description="Câu truy vấn SQL sinh ra từ B0.3 hoặc từ vòng retry")
    answer_type: Optional[str] = Field(default=None, description="Loại câu trả lời kỳ vọng từ B0.3 (1 trong 9 types)")
    retry_count: int = Field(default=0, ge=0, description="0 cho lần chạy đầu, >=1 cho lần rerun corrected SQL")
    max_retries: int = Field(default=1, ge=0, description="Giới hạn số lần thử lại (mặc định: 1 cho One bounded retry)")
    timeout_sec: float = Field(default=10.0, gt=0, description="Thời gian thực thi tối đa (giây)")
    max_rows: int = Field(default=10000, gt=0, description="Giới hạn số dòng trả về để bảo vệ bộ nhớ")

    @classmethod
    def from_b03(
        cls,
        b03_result: Any,
        question_id: str,
        db_path: str,
        retry_count: int = 0,
        max_retries: int = 1,
        timeout_sec: float = 10.0,
    ) -> "ExecutionRequest":
        """Tạo ExecutionRequest trực tiếp từ kết quả Text2SQLResult của B0.3."""
        sql = getattr(b03_result, "sql", None) or ""
        ans_type = getattr(b03_result, "answer_type", None)
        if ans_type is not None:
            try:
                from datamate.planner.parser import normalize_answer_type
                ans_type = normalize_answer_type(ans_type, sql)
            except Exception:
                pass
        return cls(
            question_id=question_id,
            db_path=db_path,
            sql_query=sql,
            answer_type=ans_type,
            retry_count=retry_count,
            max_retries=max_retries,
            timeout_sec=timeout_sec,
        )

    # Canonical semantic alias for from_b03
    from_planner = from_b03


class ExecutionResponse(BaseModel):
    question_id: str
    is_valid: bool                                      # True nếu đi nhánh 'yes', False nếu có lỗi
    route: Literal["yes", "recoverable", "abstain"]     # Nhánh điều hướng tiếp theo trên sơ đồ B0
    cleaned_sql: Optional[str] = None                   # Câu SQL sau khi đã bóc tách markdown
    columns: Optional[List[str]] = None                 # Danh sách tên cột trả về
    rows: Optional[List[Dict[str, Any]]] = None         # Dữ liệu kết quả đã chuẩn hóa kiểu Python (phục vụ B0.5)
    row_count: int = 0                                  # Số lượng dòng trả về
    error_type: Optional[str] = None                    # SyntaxError, CatalogError, BinderError, TimeoutError, SecurityViolation...
    error_message: Optional[str] = None                 # Thông báo lỗi tinh gọn để truyền vào LLM ở bước One bounded retry
    execution_time_ms: float = 0.0                      # Thời gian thực thi (mili-giây)
    truncated: bool = False                             # True nếu kết quả vượt max_rows và đã bị cắt

    def to_b05_execution_result(self) -> Any:
        """Chuyển đổi sang ExecutionResult của B0.5 Basic Output Gate."""
        from datamate.gate.contracts import ExecutionErrorDetail, ExecutionResult

        if self.is_valid and self.route == "yes":
            cols = self.columns or []
            row_matrix = []
            if self.rows:
                for r in self.rows:
                    row_matrix.append([r.get(c) for c in cols])
            return ExecutionResult(
                status="success",
                columns=cols,
                rows=row_matrix,
                row_count=self.row_count,
                truncated=self.truncated,
                elapsed_ms=self.execution_time_ms,
            )
        else:
            return ExecutionResult(
                status="error",
                columns=[],
                rows=[],
                row_count=0,
                elapsed_ms=self.execution_time_ms,
                error=ExecutionErrorDetail(
                    type=self.error_type or "ExecutionError",
                    message=self.error_message or "Execution failed",
                ),
            )

    to_gate_execution_result = to_b05_execution_result


def normalize_value(val: Any) -> Any:
    """
    Normalizes a value from DuckDB/Pandas/NumPy into JSON-safe primitive Python types.
    - NaNs, infinite numbers, pd.NA -> None
    - Timestamps, dates, datetimes -> ISO formatted strings
    - Decimals -> int or float
    - Bytes -> UTF-8 decoded string or hex
    - Lists, tuples, dicts -> recursively normalized
    """
    if val is None:
        return None

    # Handle composite structures first before scalar checks
    if isinstance(val, (list, tuple)):
        return [normalize_value(x) for x in val]

    if isinstance(val, dict):
        return {str(k): normalize_value(v) for k, v in val.items()}

    # Check for pandas/numpy NA or NaN on scalar types only
    if pd is not None and np is not None:
        if np.isscalar(val) and pd.isna(val):
            return None
    elif pd is not None:
        try:
            if pd.isna(val):
                return None
        except (ValueError, TypeError):
            pass

    if isinstance(val, bool):
        return val

    if isinstance(val, (float, int)):
        if math.isnan(val) or math.isinf(val):
            return None
        return val

    if np is not None:
        if isinstance(val, (np.floating, np.integer, np.bool_)):
            scalar = val.item()
            if isinstance(scalar, float) and (math.isnan(scalar) or math.isinf(scalar)):
                return None
            return scalar

    if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
        return val.isoformat()

    if isinstance(val, decimal.Decimal):
        if not val.is_finite():
            return None
        if val % 1 == 0:
            return int(val)
        return float(val)

    if isinstance(val, (bytes, bytearray)):
        try:
            return val.decode("utf-8")
        except UnicodeDecodeError:
            return val.hex()

    return val
