"""C4: Value Grounder — linking entity mentions and filters to actual database values."""

from __future__ import annotations

import unicodedata

from .contracts import (
    FilterCondition,
    MatchedValue,
    QuestionIntent,
    SelectedSchema,
)
from .protocols import BusinessContextProtocol


def _normalize_text(text: str) -> str:
    """Normalize Unicode NFC and lowercase."""
    return unicodedata.normalize("NFC", text).strip().lower()


def _strip_accents(text: str) -> str:
    """Remove Vietnamese diacritics for accent-insensitive fallback matching."""
    norm = _normalize_text(text).replace("đ", "d")
    decomposed = unicodedata.normalize("NFD", norm)
    return "".join(ch for ch in decomposed if unicodedata.category(ch) != "Mn")


class ValueGrounder:
    """Link Vietnamese entity phrases and filter values to real database values."""

    def ground(
        self,
        question: str,
        intent: QuestionIntent,
        selected_schema: SelectedSchema,
        context: BusinessContextProtocol,
    ) -> tuple[tuple[MatchedValue, ...], tuple[FilterCondition, ...]]:
        """Match entities and filter conditions against aliases and table sample values."""
        matched_list: list[MatchedValue] = []
        seen_matches: set[tuple[str, str, str]] = set()

        value_aliases = context.get_value_aliases()
        tables_by_name = {t.name: t for t in context.get_tables()}
        selected_table_names = [t.table_name for t in selected_schema.tables]
        ordered_table_names = selected_table_names + [
            t.name for t in context.get_tables() if t.name not in selected_table_names
        ]

        def _lookup_value(raw_phrase: str) -> MatchedValue | None:
            norm_p = _normalize_text(raw_phrase)
            if not norm_p:
                return None

            # 1. Exact alias lookup from BusinessContext
            if norm_p in value_aliases:
                tbl, col, db_val = value_aliases[norm_p]
                return MatchedValue(
                    raw_text=raw_phrase,
                    table_name=tbl,
                    column_name=col,
                    matched_db_value=db_val,
                    match_type="exact_alias",
                    confidence=1.0,
                )

            # 2. Exact or accent-stripped match against column sample_values
            stripped_p = _strip_accents(raw_phrase)
            for t_name in ordered_table_names:
                t_spec = tables_by_name.get(t_name)
                if t_spec is None:
                    continue
                for col in t_spec.columns:
                    for sv in col.sample_values:
                        sv_str = str(sv)
                        if _normalize_text(sv_str) == norm_p:
                            return MatchedValue(
                                raw_text=raw_phrase,
                                table_name=t_name,
                                column_name=col.name,
                                matched_db_value=sv,
                                match_type="exact_sample",
                                confidence=0.98,
                            )
                        if _strip_accents(sv_str) == stripped_p:
                            return MatchedValue(
                                raw_text=raw_phrase,
                                table_name=t_name,
                                column_name=col.name,
                                matched_db_value=sv,
                                match_type="unaccented_sample",
                                confidence=0.90,
                            )
                        if len(norm_p) >= 4 and norm_p in _normalize_text(sv_str):
                            return MatchedValue(
                                raw_text=raw_phrase,
                                table_name=t_name,
                                column_name=col.name,
                                matched_db_value=sv,
                                match_type="substring_sample",
                                confidence=0.80,
                            )
            return None

        # 1. Ground entities from intent
        for ent in intent.entities:
            mv = _lookup_value(ent)
            if mv is not None:
                key = (mv.table_name, mv.column_name, str(mv.matched_db_value))
                if key not in seen_matches:
                    seen_matches.add(key)
                    matched_list.append(mv)

        # 2. Ground filter conditions
        updated_filters: list[FilterCondition] = []
        for f_cond in intent.filters:
            if f_cond.is_having or isinstance(f_cond.raw_value, (int, float)):
                updated_filters.append(f_cond)
                continue

            raw_val_str = str(f_cond.raw_value)
            mv = _lookup_value(raw_val_str)
            if mv is not None:
                key = (mv.table_name, mv.column_name, str(mv.matched_db_value))
                if key not in seen_matches:
                    seen_matches.add(key)
                    matched_list.append(mv)
                updated_filters.append(
                    FilterCondition(
                        field_hint=f_cond.field_hint,
                        operator=f_cond.operator,
                        raw_value=f_cond.raw_value,
                        grounded_column=f"{mv.table_name}.{mv.column_name}",
                        grounded_value=mv.matched_db_value,
                        is_having=f_cond.is_having,
                    )
                )
            else:
                updated_filters.append(f_cond)

        return tuple(matched_list), tuple(updated_filters)


__all__ = ["ValueGrounder"]

