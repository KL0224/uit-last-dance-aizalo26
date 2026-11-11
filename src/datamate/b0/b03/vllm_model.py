"""Offline vLLM backend: Python trực tiếp load weights, không dùng HTTP API."""

from dataclasses import replace
import json
import os
from typing import Any

os.environ.setdefault("VLLM_USE_FLASHINFER_SAMPLER", "0")

from .base import BaseLLM
from .diagnostics import exception_diagnostics
from .errors import InferenceError, ModelLoadError, ModelNotLoadedError
from .types import ChatMessage, GenerationDiagnostics, GenerationOptions, GenerationResult, ModelConfig


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
        self._reasoning_configured = False

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

            reasoning_kwargs = {}
            if self.default_options.thinking_token_budget is not None:
                try:
                    from vllm.config import ReasoningConfig

                    # Probe before allocating VRAM; old versions must fail clearly.
                    SamplingParams(
                        max_tokens=self.default_options.max_new_tokens,
                        thinking_token_budget=self.default_options.thinking_token_budget,
                    )
                    reasoning_kwargs["reasoning_config"] = ReasoningConfig(
                        reasoning_start_str="<think>", reasoning_end_str="</think>",
                    )
                except (ImportError, TypeError, ValueError) as exc:
                    raise ModelLoadError(
                        "Installed vLLM does not support thinking_token_budget / ReasoningConfig. "
                        "Install a compatible vLLM version; budget will not be silently ignored."
                    ) from exc
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
                **reasoning_kwargs,
            )
        except ModelLoadError:
            raise
        except ImportError as exc:
            raise ModelLoadError(
                "Cannot import vLLM. Install the inference extra in a compatible GPU environment."
            ) from exc
        except Exception as exc:
            raise ModelLoadError(f"Failed to load model at {model_path}: {exc}") from exc
        # Chỉ đánh dấu loaded sau khi khởi tạo engine thành công.
        self._sampling_params_class = SamplingParams
        self._engine = engine
        self._reasoning_configured = bool(reasoning_kwargs)

    def _require_loaded(self) -> None:
        if not self.is_loaded:
            raise ModelNotLoadedError("Call model.load() before inference.")

    def _sampling_params(self, options: GenerationOptions | None) -> Any:
        selected = options if options is not None else self.default_options
        if selected.max_new_tokens >= self.config.max_model_len:
            raise ValueError("max_new_tokens must leave context space for input tokens")
        budget_kwargs = {}
        if selected.thinking_token_budget is not None:
            if not self._reasoning_configured:
                raise InferenceError(
                    "Thinking budget requires loading the engine with a default thinking_token_budget."
                )
            budget_kwargs["thinking_token_budget"] = selected.thinking_token_budget
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
            **budget_kwargs,
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
        selected = options if options is not None else self.default_options
        observed = GenerationDiagnostics(
            thinking_enabled=self.config.chat_template_kwargs.get("enable_thinking"),
            thinking_token_budget=selected.thinking_token_budget,
            max_new_tokens=selected.max_new_tokens,
        )
        try:
            params = self._sampling_params(options)
            # vLLM tự scheduling batch và trả kết quả theo thứ tự prompts.
            # Không tự cắt/truncate prompt: context vượt giới hạn phải báo lỗi.
            outputs = self._engine.generate(prompts, sampling_params=params, use_tqdm=False)
            results = self._convert_outputs(outputs, expected=len(prompts))
            return [replace(result, diagnostics=replace(
                observed, raw_response=result.text, input_tokens=result.input_tokens,
                output_tokens=result.output_tokens, finish_reason=result.finish_reason,
            )) for result in results]
        except Exception as exc:
            error = InferenceError(f"Batch generation failed: {exc}")
            error.diagnostics = exception_diagnostics(exc, observed)
            raise error from exc

    def chat(
        self, messages: list[ChatMessage], *, options: GenerationOptions | None = None
    ) -> GenerationResult:
        self._require_loaded()
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a nonempty list of ChatMessage")
        if any(not isinstance(message, ChatMessage) for message in messages):
            raise TypeError("Every message must be a ChatMessage")
        return self.chat_batch([messages], options=options)[0]

    def _apply_chat_template(
        self,
        messages: list[ChatMessage],
        *,
        tokenize: bool,
        options: GenerationOptions | None = None,
    ) -> Any:
        """Apply exactly the same checkpoint template for counting and inference."""
        payload = [{"role": message.role, "content": message.content} for message in messages]
        tokenizer = self._engine.get_tokenizer()
        template_kwargs = dict(self.config.chat_template_kwargs or {})
        try:
            return tokenizer.apply_chat_template(
                payload,
                tokenize=tokenize,
                add_generation_prompt=True,
                **template_kwargs,
            )
        except Exception as exc:
            selected = options if options is not None else self.default_options
            if selected.thinking_token_budget is not None:
                error = InferenceError(f"Chat template failed with thinking budget: {exc}")
                error.diagnostics = exception_diagnostics(exc, GenerationDiagnostics(
                    thinking_enabled=template_kwargs.get("enable_thinking"),
                    thinking_token_budget=selected.thinking_token_budget,
                    max_new_tokens=selected.max_new_tokens,
                ))
                raise error from exc
            return tokenizer.apply_chat_template(
                payload,
                tokenize=tokenize,
                add_generation_prompt=True,
            )

    def count_chat_tokens(self, messages: list[ChatMessage]) -> int:
        """Count input tokens after applying the checkpoint's chat template."""
        self._require_loaded()
        if not isinstance(messages, list) or not messages:
            raise ValueError("messages must be a nonempty list of ChatMessage")
        if any(not isinstance(message, ChatMessage) for message in messages):
            raise TypeError("Every message must be a ChatMessage")
        token_ids = self._apply_chat_template(messages, tokenize=True)
        if not isinstance(token_ids, list):
            raise InferenceError("Tokenizer returned an unexpected chat token shape")
        return len(token_ids)

    def chat_batch(
        self, messages_batch: list[list[ChatMessage]], *, options: GenerationOptions | None = None
    ) -> list[GenerationResult]:
        """Sinh assistant replies cho một batch các hội thoại đồng thời trên vLLM."""
        self._require_loaded()
        if not messages_batch:
            return []
        prompts = [
            self._apply_chat_template(messages, tokenize=False, options=options)
            for messages in messages_batch
        ]
        return self.generate_batch(prompts, options=options)
