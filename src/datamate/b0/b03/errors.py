"""Các lỗi ứng dụng có thể bắt mà không cần import vLLM."""


class LLMError(RuntimeError):
    """Lỗi chung của tầng model, có thể mang diagnostics của request."""

    diagnostics = None


class ModelNotLoadedError(LLMError):
    """Caller gọi inference trước load()."""


class ModelLoadError(LLMError):
    """Thiếu dependency/weights, GPU không tương thích hoặc engine load lỗi."""


class InferenceError(LLMError):
    """Inference thất bại; exception gốc được giữ qua exception chaining."""


class Text2SQLParseError(LLMError):
    """Lỗi khi không thể parse hoặc trích xuất JSON/SQL hợp lệ từ output của model."""
