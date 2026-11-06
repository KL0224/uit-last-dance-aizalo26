"""Các kiểu dữ liệu chung; không phụ thuộc PyTorch, CUDA hoặc vLLM."""

from __future__ import annotations

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
    max_model_len: int = 8192
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

    def __post_init__(self) -> None:
        if self.status not in {"answerable", "unanswerable"}:
            raise ValueError(f"Unsupported status: {self.status}")
        if isinstance(self.tables_used, list):
            object.__setattr__(self, "tables_used", tuple(self.tables_used))
        if isinstance(self.assumptions, list):
            object.__setattr__(self, "assumptions", tuple(self.assumptions))

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

        return B05GenerationResult(
            answer_type=self.answer_type or "generic",
            sql=self.sql or "",
            tables_used=list(self.tables_used),
            assumptions=list(self.assumptions),
            answer_semantics=AnswerSemantics(),
        )
