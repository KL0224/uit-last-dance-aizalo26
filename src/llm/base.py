"""Interface để code ứng dụng không gắn chặt với một inference engine."""

from abc import ABC, abstractmethod

from .types import ChatMessage, GenerationOptions, GenerationResult


class BaseLLM(ABC):
    """Backend mới phải giữ cùng ý nghĩa input/output của các method này.

    Interface đồng bộ, không quản lý lịch sử hội thoại: mỗi lần chat(), caller
    truyền toàn bộ messages cần dùng. Chưa cam kết thread safety hoặc unload.
    """

    @abstractmethod
    def load(self) -> None:
        """Load một lần; gọi lại khi đã load thành công không tạo engine mới."""

    @abstractmethod
    def generate(
        self, prompt: str, *, options: GenerationOptions | None = None
    ) -> GenerationResult:
        """Completion của raw prompt; không tự thêm chat template."""

    @abstractmethod
    def chat(
        self, messages: list[ChatMessage], *, options: GenerationOptions | None = None
    ) -> GenerationResult:
        """Sinh assistant reply bằng chat template đi kèm checkpoint."""

    @abstractmethod
    def generate_batch(
        self, prompts: list[str], *, options: GenerationOptions | None = None
    ) -> list[GenerationResult]:
        """Sinh completion cho batch raw prompts; kết quả giữ thứ tự đầu vào."""
