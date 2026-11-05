"""Offline vLLM backend: Python trực tiếp load weights, không dùng HTTP API."""

import json
from typing import Any

from .base import BaseLLM
from .errors import InferenceError, ModelLoadError, ModelNotLoadedError
from .types import ChatMessage, GenerationOptions, GenerationResult, ModelConfig


class VLLMModel(BaseLLM):
    """Một object sở hữu một vLLM engine trong suốt vòng đời process.

    Constructor không import vLLM hoặc cấp phát VRAM. Tạo nhiều object rồi
    load() từng object sẽ tạo nhiều engine/bản weights; hãy dùng chung object
    khi các agent chỉ khác prompt. Không gọi đồng thời từ nhiều thread.
    """

    def __init__(
        self, config: ModelConfig, default_options: GenerationOptions | None = None
    ) -> None:
        self.config = config
        self.default_options = default_options or GenerationOptions()
        self._engine: Any = None
        self._sampling_params_class: Any = None

    @property
    def is_loaded(self) -> bool:
        """Chỉ phản ánh engine đã khởi tạo, không phải GPU health check."""
        return self._engine is not None

    def load(self) -> None:
        """Load local snapshot một lần; không tự tải weights từ model ID."""
        if self.is_loaded:
            return
        model_path = self.config.model_path
        if not model_path.is_dir() or not (model_path / "config.json").is_file():
            raise ModelLoadError(
                f"Not a local model snapshot: {model_path}. Run the download script first."
            )
        # Snapshot do script của project tải có manifest trạng thái. Không
        # load khi download bị ngắt, kể cả config.json đã có trên đĩa.
        # Snapshot có sẵn từ nguồn khác không bắt buộc có manifest này.
        manifest_path = model_path / ".model-download.json"
        if manifest_path.exists():
            try:
                manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if not isinstance(manifest, dict) or manifest.get("status") != "complete":
                    raise ValueError("Snapshot download is not marked complete")
            except (OSError, ValueError) as exc:
                raise ModelLoadError(f"Invalid/incomplete download manifest: {manifest_path}") from exc
        try:
            # Lazy import: laptop không cài vLLM vẫn import được package llm.
            from vllm import LLM, SamplingParams

            engine = LLM(
                model=str(model_path),
                tokenizer=str(model_path),
                dtype=self.config.dtype,
                max_model_len=self.config.max_model_len,
                gpu_memory_utilization=self.config.gpu_memory_utilization,
                tensor_parallel_size=self.config.tensor_parallel_size,
                max_num_seqs=self.config.max_num_seqs,
                trust_remote_code=self.config.trust_remote_code,
                # Không để generation_config của checkpoint âm thầm đổi
                # sampling defaults mà ứng dụng đã khai báo.
                generation_config="vllm",
            )
        except ImportError as exc:
            raise ModelLoadError(
                "Cannot import vLLM. Install the inference extra in a compatible GPU environment."
            ) from exc
        except Exception as exc:
            raise ModelLoadError(f"Failed to load model at {model_path}: {exc}") from exc
        # Chỉ đánh dấu loaded sau khi khởi tạo engine thành công.
        self._sampling_params_class = SamplingParams
        self._engine = engine

    def _require_loaded(self) -> None:
        if not self.is_loaded:
            raise ModelNotLoadedError("Call model.load() before inference.")

    def _sampling_params(self, options: GenerationOptions | None) -> Any:
        selected = options if options is not None else self.default_options
        if selected.max_new_tokens >= self.config.max_model_len:
            raise ValueError("max_new_tokens must leave context space for input tokens")
        return self._sampling_params_class(
            n=1,
            max_tokens=selected.max_new_tokens,
            temperature=selected.temperature,
            top_p=selected.top_p,
            top_k=selected.top_k,
            repetition_penalty=selected.repetition_penalty,
            presence_penalty=selected.presence_penalty,
            stop=list(selected.stop) or None,
            seed=selected.seed,
        )

    @staticmethod
    def _convert_outputs(outputs: list[Any], expected: int) -> list[GenerationResult]:
        """Chuyển kết quả engine sang kiểu chung, không âm thầm bỏ request."""
        if len(outputs) != expected:
            raise InferenceError(f"Expected {expected} outputs, received {len(outputs)}")
        results = []
        for output in outputs:
            if len(output.outputs) != 1 or output.prompt_token_ids is None:
                raise InferenceError("Engine returned missing tokens or unexpected candidate count")
            completion = output.outputs[0]
            results.append(GenerationResult(
                text=completion.text,
                input_tokens=len(output.prompt_token_ids),
                output_tokens=len(completion.token_ids),
                finish_reason=completion.finish_reason,
            ))
        return results

    def generate(
        self, prompt: str, *, options: GenerationOptions | None = None
    ) -> GenerationResult:
        """Dùng chung đường xử lý batch để hai API không lệch hành vi."""
        return self.generate_batch([prompt], options=options)[0]

    def generate_batch(
        self, prompts: list[str], *, options: GenerationOptions | None = None
    ) -> list[GenerationResult]:
        self._require_loaded()
        if not isinstance(prompts, list) or any(not isinstance(p, str) for p in prompts):
            raise TypeError("prompts must be a list of strings")
        if not prompts:
            return []
        params = self._sampling_params(options)
        try:
            # vLLM tự scheduling batch và trả kết quả theo thứ tự prompts.
            # Không tự cắt/truncate prompt: context vượt giới hạn phải báo lỗi.
            outputs = self._engine.generate(prompts, sampling_params=params, use_tqdm=False)
            return self._convert_outputs(outputs, expected=len(prompts))
        except Exception as exc:
            raise InferenceError(f"Batch generation failed: {exc}") from exc

    def chat(
        self, messages: list[ChatMessage], *, options: GenerationOptions | None = None
    ) -> GenerationResult:
        self._require_loaded()
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a nonempty list of ChatMessage")
        if any(not isinstance(message, ChatMessage) for message in messages):
            raise TypeError("Every message must be a ChatMessage")
        params = self._sampling_params(options)
        payload = [{"role": m.role, "content": m.content} for m in messages]
        try:
            # Engine áp dụng chat template gốc; không tự nối role markers.
            # enable_thinking trong config chỉ tác động chat(), không tác
            # động raw prompt của generate()/generate_batch().
            outputs = self._engine.chat(
                payload,
                sampling_params=params,
                chat_template_kwargs=dict(self.config.chat_template_kwargs),
                use_tqdm=False,
            )
            return self._convert_outputs(outputs, expected=1)[0]
        except Exception as exc:
            raise InferenceError(f"Chat generation failed: {exc}") from exc
