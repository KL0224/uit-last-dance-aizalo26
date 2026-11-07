"""Bộ điều phối sinh Text-to-SQL cấp cao (Generator) kết nối LLM với Prompt & Parser."""

from __future__ import annotations

from typing import Any

from .base import BaseLLM
from .parser import parse_text2sql_response
from .prompt import build_repair_messages, build_text2sql_messages
from .types import GenerationOptions, Text2SQLResult


class Text2SQLGenerator:
    """Tầng tạo sinh SQL cấp cao nhận BusinessContext và trả về Text2SQLResult chuẩn xác.

    Tự động chuẩn bị prompt, gửi qua BaseLLM (vLLM hoặc mock), và phân tích cú pháp
    JSON/SQL đầu ra. Sẵn sàng hỗ trợ vòng lặp Bounded Retry nếu có lỗi thực thi.
    """

    def __init__(self, model: BaseLLM) -> None:
        self.model = model

    def generate(
        self,
        context: Any,
        question: str,
        as_of_date: str,
        *,
        options: GenerationOptions | None = None,
        industry: str | None = None,
    ) -> Text2SQLResult:
        """Sinh câu truy vấn SQL từ câu hỏi và BusinessContext."""
        messages = build_text2sql_messages(context, question, as_of_date, industry)
        gen_result = self.model.chat(messages, options=options)
        return parse_text2sql_response(gen_result.text, question=question)

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
    ) -> Text2SQLResult:
        """Thực hiện 1 lần Bounded Retry sửa lại câu SQL khi bước thực thi gặp lỗi."""
        messages = build_repair_messages(
            context=context,
            question=question,
            as_of_date=as_of_date,
            previous_sql=previous_sql,
            error_message=error_message,
            industry=industry,
        )
        gen_result = self.model.chat(messages, options=options)
        return parse_text2sql_response(gen_result.text, question=question)

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
            build_text2sql_messages(
                it["context"],
                it["question"],
                it["as_of_date"],
                it.get("industry"),
            )
            for it in items
        ]
        gen_results = self.model.chat_batch(messages_batch, options=options)
        parsed: list[Any] = []
        for it, gr in zip(items, gen_results):
            try:
                parsed.append(parse_text2sql_response(gr.text, question=it.get("question")))
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
            build_repair_messages(
                context=it["context"],
                question=it["question"],
                as_of_date=it["as_of_date"],
                previous_sql=it["previous_sql"],
                error_message=it["error_message"],
                industry=it.get("industry"),
            )
            for it in items
        ]
        gen_results = self.model.chat_batch(messages_batch, options=options)
        parsed: list[Any] = []
        for it, gr in zip(items, gen_results):
            try:
                parsed.append(parse_text2sql_response(gr.text, question=it.get("question")))
            except Exception as parse_err:
                parsed.append(parse_err)
        return parsed

