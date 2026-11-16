"""Bộ điều phối sinh Text-to-SQL cấp cao (Generator) kết nối LLM với Prompt & Parser."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Literal, Sequence

from .base import BaseLLM
from .diagnostics import exception_diagnostics
from .parser import parse_text2sql_response
from .prompt import build_repair_messages, build_text2sql_messages
from .prompt_v1_2 import build_v1_2_messages, build_v1_2_repair_messages
from .types import GenerationDiagnostics, GenerationOptions, GenerationResult, Text2SQLResult

_PROMPT_FORMATS = frozenset({"legacy", "v1_2"})
_GROUNDED_HINT_MODES = frozenset({"auto", "markdown", "compact_json", "off"})


class Text2SQLGenerator:
    """Tầng tạo sinh SQL cấp cao nhận BusinessContext và trả về Text2SQLResult chuẩn xác.

    Tự động chuẩn bị prompt, gửi qua BaseLLM (vLLM hoặc mock), và phân tích cú pháp
    JSON/SQL đầu ra. Sẵn sàng hỗ trợ vòng lặp Bounded Retry nếu có lỗi thực thi.
    """

    def __init__(
        self,
        model: BaseLLM,
        *,
        prompt_format: Literal["legacy", "v1_2"] | None = None,
        grounded_hint_mode: Literal["auto", "markdown", "compact_json", "off"] | None = None,
    ) -> None:
        self.model = model
        resolved = prompt_format if prompt_format is not None else getattr(
            getattr(model, "config", None), "prompt_format", "legacy"
        )
        if resolved not in _PROMPT_FORMATS:
            raise ValueError(f"Unsupported prompt_format: {resolved!r}")
        self.prompt_format: Literal["legacy", "v1_2"] = resolved

        resolved_hint = grounded_hint_mode if grounded_hint_mode is not None else getattr(
            getattr(model, "config", None), "grounded_hint_mode", "auto"
        )
        if resolved_hint not in _GROUNDED_HINT_MODES:
            raise ValueError(f"Unsupported grounded_hint_mode: {resolved_hint!r}")
        self.grounded_hint_mode: Literal["auto", "markdown", "compact_json", "off"] = resolved_hint

    @property
    def effective_grounded_hint_mode(self) -> Literal["markdown", "compact_json", "off"]:
        if self.grounded_hint_mode != "auto":
            return self.grounded_hint_mode
        return "compact_json" if self.prompt_format == "v1_2" else "markdown"

    def _build_generate_messages(
        self,
        context: Any,
        question: str,
        as_of_date: str,
        industry: str | None = None,
        grounded_hint: str | None = None,
    ) -> Any:
        hint = None if self.effective_grounded_hint_mode == "off" else grounded_hint
        if self.prompt_format == "v1_2":
            return build_v1_2_messages(
                context=context,
                question=question,
                as_of_date=as_of_date,
                industry=industry,
                grounded_hint=hint,
            )
        return build_text2sql_messages(
            context=context,
            question=question,
            as_of_date=as_of_date,
            industry=industry,
            grounded_hint=hint,
        )

    def _build_repair_messages(
        self,
        context: Any,
        question: str,
        as_of_date: str,
        previous_sql: str,
        error_message: str,
        industry: str | None = None,
        grounded_hint: str | None = None,
        *,
        previous_plan: dict[str, Any] | None = None,
        error_code: str | None = None,
        failed_checks: Sequence[str] | None = None,
    ) -> Any:
        hint = None if self.effective_grounded_hint_mode == "off" else grounded_hint
        if self.prompt_format == "v1_2":
            return build_v1_2_repair_messages(
                context=context,
                question=question,
                as_of_date=as_of_date,
                previous_sql=previous_sql,
                error_message=error_message,
                industry=industry,
                grounded_hint=hint,
                previous_plan=previous_plan,
                error_code=error_code,
                failed_checks=failed_checks,
            )
        return build_repair_messages(
            context=context,
            question=question,
            as_of_date=as_of_date,
            previous_sql=previous_sql,
            error_message=error_message,
            industry=industry,
            grounded_hint=hint,
        )

    def _request_diagnostics(self, options: GenerationOptions | None) -> GenerationDiagnostics:
        selected = options if options is not None else getattr(self.model, "default_options", None)
        config = getattr(self.model, "config", None)
        template_kwargs = getattr(config, "chat_template_kwargs", {})
        return GenerationDiagnostics(
            thinking_enabled=(selected.enable_thinking if selected is not None and selected.enable_thinking is not None
                              else template_kwargs.get("enable_thinking")),
            thinking_token_budget=getattr(selected, "thinking_token_budget", None),
            max_new_tokens=getattr(selected, "max_new_tokens", None),
        )

    def _parse(
        self, result: GenerationResult, question: str | None,
        options: GenerationOptions | None,
    ) -> Text2SQLResult:
        observed = result.diagnostics or self._request_diagnostics(options)
        observed = replace(
            observed, raw_response=result.text, input_tokens=result.input_tokens,
            output_tokens=result.output_tokens, finish_reason=result.finish_reason,
        )
        try:
            parsed = parse_text2sql_response(result.text, question=question)
        except Exception as exc:
            exc.diagnostics = exception_diagnostics(exc, replace(
                observed, parse_success=False,
                failure_kind="parse_error_after_length_limit" if result.finish_reason == "length" else "parse_error",
            ))
            raise
        return replace(parsed, diagnostics=replace(observed, parse_success=True))

    def _chat(self, messages: Any, options: GenerationOptions | None) -> GenerationResult:
        try:
            return self.model.chat(messages, options=options)
        except Exception as exc:
            self._attach_inference_diagnostics(exc, options)
            raise

    def _chat_batch(self, messages: Any, options: GenerationOptions | None) -> list[GenerationResult]:
        try:
            return self.model.chat_batch(messages, options=options)
        except Exception as exc:
            self._attach_inference_diagnostics(exc, options)
            raise

    def _attach_inference_diagnostics(self, exc: Exception, options: GenerationOptions | None) -> None:
        observed = getattr(exc, "diagnostics", None) or self._request_diagnostics(options)
        exc.diagnostics = exception_diagnostics(exc, observed)

    def generate(
        self,
        context: Any,
        question: str,
        as_of_date: str,
        *,
        options: GenerationOptions | None = None,
        industry: str | None = None,
        grounded_hint: str | None = None,
    ) -> Text2SQLResult:
        """Sinh câu truy vấn SQL từ câu hỏi và BusinessContext."""
        messages = self._build_generate_messages(
            context=context,
            question=question,
            as_of_date=as_of_date,
            industry=industry,
            grounded_hint=grounded_hint,
        )
        gen_result = self._chat(messages, options)
        return self._parse(gen_result, question, options)

    def repair(
        self,
        context: Any,
        question: str,
        as_of_date: str,
        previous_sql: str,
        error_message: str,
        *,
        options: GenerationOptions | None = None,
        industry: str | None = None,
        grounded_hint: str | None = None,
        previous_plan: dict[str, Any] | None = None,
        error_code: str | None = None,
        failed_checks: Sequence[str] | None = None,
    ) -> Text2SQLResult:
        """Thực hiện 1 lần Bounded Retry sửa lại câu SQL khi bước thực thi gặp lỗi."""
        messages = self._build_repair_messages(
            context=context,
            question=question,
            as_of_date=as_of_date,
            previous_sql=previous_sql,
            error_message=error_message,
            industry=industry,
            grounded_hint=grounded_hint,
            previous_plan=previous_plan,
            error_code=error_code,
            failed_checks=failed_checks,
        )
        gen_result = self._chat(messages, options)
        return self._parse(gen_result, question, options)

    def generate_batch(
        self,
        items: list[dict[str, Any]],
        *,
        options: GenerationOptions | None = None,
    ) -> list[Any]:
        """Sinh Text2SQL cho một danh sách các câu hỏi theo batch trên GPU."""
        if not items:
            return []
        messages_batch = [
            self._build_generate_messages(
                it["context"],
                it["question"],
                it["as_of_date"],
                it.get("industry"),
                it.get("grounded_hint"),
            )
            for it in items
        ]
        gen_results = self._chat_batch(messages_batch, options)
        parsed: list[Any] = []
        for it, gr in zip(items, gen_results):
            try:
                parsed.append(self._parse(gr, it.get("question"), options))
            except Exception as parse_err:
                parsed.append(parse_err)
        return parsed

    def repair_batch(
        self,
        items: list[dict[str, Any]],
        *,
        options: GenerationOptions | None = None,
    ) -> list[Any]:
        """Sửa Text2SQL cho danh sách các câu hỏi cần retry theo batch trên GPU."""
        if not items:
            return []
        messages_batch = [
            self._build_repair_messages(
                it["context"],
                it["question"],
                it["as_of_date"],
                it["previous_sql"],
                it["error_message"],
                it.get("industry"),
                it.get("grounded_hint"),
                previous_plan=it.get("previous_plan"),
                error_code=it.get("error_code"),
                failed_checks=it.get("failed_checks"),
            )
            for it in items
        ]
        gen_results = self._chat_batch(messages_batch, options)
        parsed: list[Any] = []
        for it, gr in zip(items, gen_results):
            try:
                parsed.append(self._parse(gr, it.get("question"), options))
            except Exception as parse_err:
                parsed.append(parse_err)
        return parsed

