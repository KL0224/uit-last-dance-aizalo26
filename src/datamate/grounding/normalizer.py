"""Deterministic normalization for common Vietnamese question shorthand."""

from __future__ import annotations

import re
import unicodedata


_MAX_QUESTION_CHARS = 8_192
_SUBSTITUTIONS: tuple[tuple[re.Pattern[str], str], ...] = tuple(
    (re.compile(pattern, flags=re.IGNORECASE), replacement)
    for pattern, replacement in (
        (r"(?<!\w)h\.nay(?!\w)", "hôm nay"),
        (r"(?<!\w)h\.qua(?!\w)", "hôm qua"),
        (r"(?<!\w)t\.này(?!\w)", "tháng này"),
        (r"(?<!\w)hnay(?!\w)", "hôm nay"),
        (r"(?<!\w)hqua(?!\w)", "hôm qua"),
        (r"(?<!\w)thg\s+này(?!\w)", "tháng này"),
        (r"(?<!\w)thg\s+trước(?!\w)", "tháng trước"),
        (r"(?<!\w)dt(?!\w)", "doanh thu"),
        (r"(?<!\w)sl(?!\w)", "số lượng"),
        (r"(?<!\w)sp(?!\w)", "sản phẩm"),
        (r"(?<!\w)kh(?!\w)", "khách hàng"),
        (r"(?<!\w)(?:đh|dh)(?!\w)", "đơn hàng"),
    )
)


class VietnameseQuestionNormalizer:
    """Expand a conservative allowlist of shorthand before all grounding stages."""

    def normalize(self, question: str) -> str:
        """Return NFC text with known standalone shorthand expanded."""
        if not isinstance(question, str):
            raise TypeError("question must be text")
        if len(question) > _MAX_QUESTION_CHARS:
            raise ValueError("Question exceeds the grounding size limit")
        normalized = unicodedata.normalize("NFC", question).strip()
        for pattern, replacement in _SUBSTITUTIONS:
            normalized = pattern.sub(replacement, normalized)
        normalized = re.sub(r"\s+", " ", normalized)
        if len(normalized) > _MAX_QUESTION_CHARS:
            raise ValueError("Normalized question exceeds the grounding size limit")
        return normalized


__all__ = ["VietnameseQuestionNormalizer"]
