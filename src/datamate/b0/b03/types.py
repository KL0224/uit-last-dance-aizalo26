"""Các kiểu dữ liệu chung; không phụ thuộc PyTorch, CUDA hoặc vLLM."""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal


@dataclass(frozen=True)
class ChatMessage:
    """Một message text; bản đầu chưa nhận ảnh, tool calls hoặc audio."""

    role: Literal["system", "user", "assistant"]
    content: str

    def __post_init__(self) -> None:
        if self.role not in {"system", "user", "assistant"}:
            raise ValueError(f"Unsupported chat role: {self.role}")
        if not isinstance(self.content, str):
            raise TypeError("ChatMessage.content must be a string")


@dataclass(frozen=True)
class GenerationOptions:
    """Sampling áp dụng cho toàn bộ request/batch; không thay đổi weights.

    max_new_tokens chỉ giới hạn output. Tổng input và output vẫn phải nằm
    trong max_model_len; vLLM kiểm tra theo tokenizer thực tế của checkpoint.
    temperature=0 cho greedy decoding; seed không đảm bảo giống bit-for-bit
    giữa các phiên bản engine hoặc phần cứng.
    """

    max_new_tokens: int = 1024
    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int = 20
    repetition_penalty: float = 1.0
    presence_penalty: float = 1.5
    stop: tuple[str, ...] = ()
    seed: int | None = None

    def __post_init__(self) -> None:
        if self.max_new_tokens < 1:
            raise ValueError("max_new_tokens must be positive")
        if self.temperature < 0 or not 0 < self.top_p <= 1:
            raise ValueError("temperature must be >= 0; top_p must be in (0, 1]")
        if self.top_k != -1 and self.top_k < 1:
            raise ValueError("top_k must be -1 (disabled) or a positive integer")
        if self.repetition_penalty <= 0 or not -2 <= self.presence_penalty <= 2:
            raise ValueError("Invalid repetition_penalty or presence_penalty")
        if isinstance(self.stop, str) or any(
            not isinstance(item, str) or not item for item in self.stop
        ):
            raise ValueError("stop must be a sequence of nonempty strings")
        # Chuẩn hóa list đọc từ TOML thành tuple để không bị sửa ngoài ý muốn.
        object.__setattr__(self, "stop", tuple(self.stop))


@dataclass(frozen=True)
class ModelConfig:
    """Cấu hình load engine; model_path phải trỏ tới snapshot trên đĩa.

    chat_template_kwargs được chuyển nguyên sang chat template của model.
    Ví dụ enable_thinking chỉ có ý nghĩa nếu template của checkpoint hỗ trợ.
    """

    model_path: Path
    dtype: str = "bfloat16"
    max_model_len: int = 16384
    gpu_memory_utilization: float = 0.9
    tensor_parallel_size: int = 1
    max_num_seqs: int = 4
    trust_remote_code: bool = False
    chat_template_kwargs: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        object.__setattr__(self, "model_path", Path(self.model_path).expanduser().resolve())
        if self.max_model_len < 1 or self.tensor_parallel_size < 1 or self.max_num_seqs < 1:
            raise ValueError("Context length, tensor parallel size and max_num_seqs must be positive")
        if not 0 < self.gpu_memory_utilization < 1:
            raise ValueError("gpu_memory_utilization must be in (0, 1)")
        # Sao chép dict để caller không vô tình đổi cấu hình bằng dict ban đầu.
        object.__setattr__(self, "chat_template_kwargs", dict(self.chat_template_kwargs))


@dataclass(frozen=True)
class GenerationResult:
    """Kết quả sinh text thô từ model độc lập backend.

    text là completion nguyên bản. Với thinking bật, nó có thể chứa cả
    thinking markers/content; tầng model không tự parse hay xóa phần này.
    """

    text: str
    input_tokens: int
    output_tokens: int
    finish_reason: str | None


@dataclass(frozen=True)
class Text2SQLResult:
    """Đặc tả kết quả Text-to-SQL logic theo đúng chuẩn input_output_text2sql.md.

    Cung cấp cầu nối giữa mô hình LLM (B0.3) với Tầng thực thi (B0.4) và Cổng kiểm duyệt (B0.5).
    """

    status: Literal["answerable", "unanswerable"]
    answer_type: str | None = None
    sql: str | None = None
    tables_used: tuple[str, ...] = ()
    assumptions: tuple[str, ...] = ()
    reason: str | None = None
    answer_semantics: dict[str, Any] | None = None
    missing_fields: tuple[str, ...] = ()
    thinking: str | None = None
    raw_response: str | None = None

    def __post_init__(self) -> None:
        if self.status not in {"answerable", "unanswerable"}:
            raise ValueError(f"Unsupported status: {self.status}")
        if isinstance(self.tables_used, list):
            object.__setattr__(self, "tables_used", tuple(self.tables_used))
        if isinstance(self.assumptions, list):
            object.__setattr__(self, "assumptions", tuple(self.assumptions))
        if isinstance(self.missing_fields, list):
            object.__setattr__(self, "missing_fields", tuple(self.missing_fields))

    def to_b05_generation_result(self) -> Any:
        """Chuyển đổi sang GenerationResult của B0.5 Basic Output Gate."""
        from datamate.b0.b05.contracts import AnswerSemantics, GenerationResult as B05GenerationResult

        if self.status == "unanswerable":
            return B05GenerationResult(
                answer_type="unanswerable",
                sql="",
                tables_used=list(self.tables_used),
                assumptions=list(self.assumptions),
                answer_semantics=AnswerSemantics(),
            )

        from .parser import normalize_answer_type

        answer_type = normalize_answer_type(self.answer_type, self.sql)
        semantics = dict(self.answer_semantics or {})
        if answer_type == "number" and not semantics.get("numeric_kind"):
            kind = _infer_numeric_kind(self.sql or "")
            if kind:
                semantics["numeric_kind"] = kind
        allowed = {
            "numeric_kind",
            "percent_unit",
            "list_ordered",
            "time_role",
            "empty_set_policy",
        }
        return B05GenerationResult(
            answer_type=answer_type,
            sql=self.sql or "",
            tables_used=list(self.tables_used),
            assumptions=list(self.assumptions),
            answer_semantics=AnswerSemantics(
                **{k: v for k, v in semantics.items() if k in allowed}
            ),
        )

    def to_b05_evidence_proof(self, context: Any = None) -> Any:
        """Build B0.5 evidence; verified only against the supplied schema catalog."""
        from .evidence import build_evidence_proof

        if self.status != "unanswerable":
            from datamate.b0.b05.contracts import EvidenceProof

            return EvidenceProof()
        return build_evidence_proof(context, self.reason, self.missing_fields)


_MONEY_PARTS = frozenset(
    "tien gia doanh_thu thu chi_phi phi lai no chiet khau amount cost price revenue profit".split()
)


def _infer_numeric_kind(sql: str) -> str | None:
    """Infer B0.5 numeric_kind from the first projected expression; None when unsure."""
    match = re.match(r"\s*SELECT\s+(?:DISTINCT\s+)?(.+?)\s+FROM\b", sql, re.IGNORECASE | re.DOTALL)
    projection = (match.group(1) if match else sql).lower()
    if re.match(r"\s*count\s*\(", projection):
        return "count"
    aggregate = re.match(r"\s*(avg|sum)\s*\((.*)\)", projection, re.DOTALL)
    if not aggregate:
        return None
    parts = set(re.split(r"[^a-z]+", aggregate.group(2)))
    if not parts & _MONEY_PARTS:
        return None
    return "average_money_vnd" if aggregate.group(1) == "avg" else "money_vnd"
