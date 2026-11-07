"""Public API cho Module B0.3 (Text-to-SQL LLM Layer).

Import package này không tự động import GPU runtime (vLLM/PyTorch).
"""

from .base import BaseLLM
from .config import load_config
from .errors import (
    InferenceError,
    LLMError,
    ModelLoadError,
    ModelNotLoadedError,
    Text2SQLParseError,
)
from .evidence import build_evidence_proof
from .generator import Text2SQLGenerator
from .parser import (
    extract_tables_from_sql,
    infer_answer_type_from_sql,
    parse_text2sql_response,
)
from .prompt import (
    build_repair_messages,
    build_text2sql_messages,
    format_context_for_prompt,
)
from .types import (
    ChatMessage,
    GenerationOptions,
    GenerationResult,
    ModelConfig,
    Text2SQLResult,
)
from .vllm_model import VLLMModel

__all__ = [
    # Base LLM Interfaces & Model
    "BaseLLM",
    "VLLMModel",
    "load_config",
    # Dataclasses & Types
    "ChatMessage",
    "GenerationOptions",
    "GenerationResult",
    "ModelConfig",
    "Text2SQLResult",
    # Prompt & Parsing Tools
    "build_text2sql_messages",
    "build_repair_messages",
    "format_context_for_prompt",
    "parse_text2sql_response",
    "extract_tables_from_sql",
    "infer_answer_type_from_sql",
    "build_evidence_proof",
    # High-level Orchestration
    "Text2SQLGenerator",
    # Exceptions
    "LLMError",
    "ModelLoadError",
    "ModelNotLoadedError",
    "InferenceError",
    "Text2SQLParseError",
]
