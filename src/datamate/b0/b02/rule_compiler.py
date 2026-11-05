"""Deterministic ingestion and compilation of business rule metadata."""

from __future__ import annotations

import hashlib
import math
import re
from dataclasses import replace
from pathlib import Path
from typing import Any

from .contracts import BusinessRule, RuleCatalog, SchemaCatalog
from .rule_resolver import PRECEDENCE

_SCOPE_PRECEDENCE = PRECEDENCE | {"unknown": 0}
_FIELD_TOKEN = re.compile(r"`([^`]+)`")
_RULES: dict[str, set[str]] = {
    "eq": {"field", "value"},
    "ne": {"field", "value"},
    "gt": {"field", "value"},
    "gte": {"field", "value"},
    "lt": {"field", "value"},
    "lte": {"field", "value"},
    "in": {"field", "values"},
    "is_null": {"field"},
    "and": {"items"},
    "or": {"items"},
    "not": {"item"},
    "add": {"left", "right"},
    "sub": {"left", "right"},
    "mul": {"left", "right"},
    "div": {"left", "right"},
    "field": {"field"},
    "literal": {"value"},
    "sum": {"item"},
    "count_distinct": {"field"},
    "count_rows": set(),
}


class BusinessRuleCompiler:
    """Catalog documents verbatim and compile only an explicit safe rule DSL."""

    def ingest_documents(
        self,
        paths: list[str | Path],
        business_id: str | None = None,
        schema: SchemaCatalog | None = None,
    ) -> RuleCatalog:
        """Ingest Markdown paragraphs/table rows with deterministic IDs and provenance."""
        rules: list[BusinessRule] = []
        warnings: list[str] = []
        seen_ids: dict[str, int] = {}
        for raw_path in paths:
            path = Path(raw_path)
            if not path.is_file():
                warnings.append(f"source file not found: {path}")
                continue
            is_business_document = path.name.casefold() == "readme.md" or (
                business_id is not None and business_id in path.parts
            )
            default_scope = "business" if is_business_document else "split_default"
            conflicting_business = next(
                (
                    part
                    for part in path.parts
                    if re.fullmatch(r"biz_\d+", part) and part != business_id
                ),
                None,
            )
            if conflicting_business:
                warnings.append(
                    f"skipped business-specific document {path}: belongs to {conflicting_business}, requested {business_id}"
                )
                continue
            heading_scope = default_scope
            heading_industry: str | None = None
            lines = path.read_text(encoding="utf-8").splitlines()
            for index, line in enumerate(lines):
                line_no = index + 1
                stripped = line.strip()
                if not stripped:
                    continue
                if stripped.startswith("#"):
                    level = len(stripped) - len(stripped.lstrip("#"))
                    if level <= 2:
                        heading_scope = default_scope
                        heading_industry = None
                    if (
                        "theo ngành" in stripped.casefold()
                        or "by industry" in stripped.casefold()
                    ):
                        heading_scope = "industry"
                    elif level >= 3 and heading_scope == "industry":
                        heading_industry = stripped.lstrip("#").strip()
                    continue
                if (
                    stripped.startswith("|")
                    and index + 1 < len(lines)
                    and _is_table_separator(lines[index + 1])
                ):
                    continue
                if stripped.startswith("<!--") or set(stripped) <= {"|", "-", ":", " "}:
                    continue
                text = _clean_markdown_row(stripped)
                if not text or text.lower() in {
                    "luật | mặc định",
                    "cách ghi | hiểu là",
                }:
                    continue
                source = f"{path.as_posix()}:{line_no}"
                source_key = "/".join(path.parts[-3:])
                base_id = _stable_id(
                    source_key, f"{heading_scope}:{heading_industry or ''}", text
                )
                seen_ids[base_id] = seen_ids.get(base_id, 0) + 1
                rule_id = (
                    base_id
                    if seen_ids[base_id] == 1
                    else f"{base_id}_{seen_ids[base_id]}"
                )
                fields = tuple(
                    dict.fromkeys(
                        _FIELD_TOKEN.findall(text) + _linked_fields(text, schema)
                    )
                )
                rules.append(
                    BusinessRule(
                        rule_id=rule_id,
                        text=text,
                        source=source,
                        scope=heading_scope,
                        precedence=_SCOPE_PRECEDENCE[heading_scope],
                        status="descriptive",
                        required_fields=fields,
                        topic=text.split(" | ", 1)[0]
                        if stripped.startswith("|")
                        else None,
                        industry=heading_industry,
                    )
                )
        return RuleCatalog(tuple(rules), tuple(warnings), business_id)

    def add_structured_rule(
        self,
        rule_id: str,
        text: str,
        source: str,
        scope: str,
        expression: dict[str, Any],
        schema: SchemaCatalog,
        existing: RuleCatalog | None = None,
        topic: str | None = None,
        industry: str | None = None,
        question_id: str | None = None,
    ) -> RuleCatalog:
        """Add an explicitly structured rule after field and DSL validation."""
        if scope not in _SCOPE_PRECEDENCE:
            raise ValueError(f"unsupported scope: {scope}")
        if scope == "industry" and not industry:
            raise ValueError("industry-scoped rules require industry")
        if scope == "question_override" and not question_id:
            raise ValueError("question overrides require question_id")
        columns = _schema_columns(schema)
        fields = tuple(sorted(_referenced_fields(expression)))
        errors: list[str] = []
        try:
            _validate_expression(expression, columns)
        except (TypeError, ValueError) as exc:
            errors.append(str(exc))
        status = "validated" if not errors else "invalid"
        rule = BusinessRule(
            rule_id=rule_id,
            text=text,
            source=source,
            scope=scope,
            precedence=_SCOPE_PRECEDENCE[scope],
            status=status,
            required_fields=fields,
            expression=expression,
            validation_messages=tuple(errors),
            topic=topic,
            industry=industry,
            question_id=question_id,
        )
        current = existing or RuleCatalog((), business_id=None)
        if any(item.rule_id == rule_id for item in current.rules):
            raise ValueError(f"duplicate rule_id: {rule_id}")
        rules = current.rules + (rule,)
        warnings = list(current.warnings)
        if topic:
            peers = [
                item
                for item in rules[:-1]
                if item.topic == topic
                and item.scope == scope
                and item.industry == industry
                and item.question_id == question_id
            ]
            if any(item.expression != expression for item in peers):
                warnings.append(
                    f"conflicting structured rules for topic={topic!r}, scope={scope!r}"
                )
                rules = tuple(
                    replace(
                        item,
                        status="conflict",
                        validation_messages=item.validation_messages
                        + ("conflicts with another rule in the same scope",),
                    )
                    if item.topic == topic
                    and item.scope == scope
                    and item.industry == industry
                    and item.question_id == question_id
                    else item
                    for item in rules
                )
        return RuleCatalog(tuple(rules), tuple(warnings), current.business_id)

    def compile_rule(
        self, rule: BusinessRule, schema: SchemaCatalog
    ) -> tuple[str, tuple[Any, ...]]:
        """Compile only a validated, non-conflicting rule selected by the caller."""
        if rule.status != "validated" or rule.expression is None:
            raise ValueError(f"rule {rule.rule_id} is not validated for execution")
        return self.compile_expression(rule.expression, schema)

    def compile_expression(
        self, expression: dict[str, Any], schema: SchemaCatalog
    ) -> tuple[str, tuple[Any, ...]]:
        """Compile a validated DSL expression to parameterized SQL and values."""
        columns = _schema_columns(schema)
        _validate_expression(expression, columns)
        params: list[Any] = []
        sql = _compile_node(expression, params)
        return sql, tuple(params)


def _stable_id(source: str, scope: str, text: str) -> str:
    digest = hashlib.sha256(f"{source}\0{scope}\0{text}".encode()).hexdigest()[:16]
    return f"rule_{digest}"


def _is_table_separator(text: str) -> bool:
    """A blank line is not a separator and must not consume the previous rule."""
    return "-" in text and "|" in text and set(text.strip()) <= {"|", "-", ":", " "}


def _clean_markdown_row(text: str) -> str:
    if text.startswith("|") and text.endswith("|"):
        text = text[1:-1]
    return " | ".join(part.strip() for part in text.split("|")) if "|" in text else text


def _linked_fields(text: str, schema: SchemaCatalog | None) -> list[str]:
    if schema is None:
        return []
    lowered = text.casefold()
    found: list[str] = []
    for table in schema.tables:
        for column in table.columns:
            pattern = rf"(?<![\w]){re.escape(column.name.casefold())}(?![\w])"
            if re.search(pattern, lowered):
                found.append(column.name)
    return found


def _referenced_fields(node: Any) -> set[str]:
    if isinstance(node, dict):
        found = {str(node["field"])} if isinstance(node.get("field"), str) else set()
        for value in node.values():
            found.update(_referenced_fields(value))
        return found
    if isinstance(node, list):
        return (
            set().union(*(_referenced_fields(item) for item in node)) if node else set()
        )
    return set()


def _validate_expression(
    node: Any,
    columns: dict[str, set[str]],
    depth: int = 0,
    inside_aggregate: bool = False,
) -> None:
    if depth > 32:
        raise ValueError("expression exceeds the supported depth of 32")
    if not isinstance(node, dict) or not isinstance(node.get("op"), str):
        raise TypeError("expression nodes must be objects with an 'op'")
    op = node["op"]
    if op not in _RULES:
        raise ValueError(f"unsupported expression operator: {op}")
    if set(node) != {"op"} | _RULES[op]:
        raise ValueError(f"invalid fields for operator {op}")
    if "field" in node:
        _resolve_field(node["field"], columns)
    if op in {"field", "count_distinct", "count_rows"}:
        if inside_aggregate and op in {"count_distinct", "count_rows"}:
            raise ValueError("nested aggregates are not supported")
        return
    if op == "literal":
        _validate_scalar(node["value"])
        return
    if op == "sum":
        if inside_aggregate:
            raise ValueError("nested aggregates are not supported")
        _validate_expression(node["item"], columns, depth + 1, True)
        return
    if op in {"and", "or"}:
        if not isinstance(node["items"], list) or len(node["items"]) < 2:
            raise ValueError(f"{op} requires at least two expressions")
        for item in node["items"]:
            _validate_expression(item, columns, depth + 1, inside_aggregate)
    elif op == "not":
        _validate_expression(node["item"], columns, depth + 1, inside_aggregate)
    elif op in {"add", "sub", "mul", "div"}:
        for side in ("left", "right"):
            value = node[side]
            if isinstance(value, dict):
                _validate_expression(value, columns, depth + 1, inside_aggregate)
            elif isinstance(value, bool) or not isinstance(value, (int, float)):
                raise TypeError(
                    f"arithmetic operand {side} must be numeric or expression"
                )
            else:
                _validate_scalar(value)
    elif op == "in":
        if not isinstance(node["values"], list) or not node["values"]:
            raise ValueError("in requires a non-empty values list")
        for value in node["values"]:
            _validate_scalar(value)
    elif op != "is_null":
        _validate_scalar(node.get("value"))


def _validate_scalar(value: Any) -> None:
    if not isinstance(value, (str, int, float, bool, type(None))):
        raise TypeError("literal parameters must be JSON scalar values")
    if isinstance(value, float) and not math.isfinite(value):
        raise ValueError("non-finite numeric values are not supported")


def _schema_columns(schema: SchemaCatalog) -> dict[str, set[str]]:
    return {
        table.name: {column.name for column in table.columns} for table in schema.tables
    }


def _resolve_field(name: str, columns: dict[str, set[str]]) -> str:
    if not isinstance(name, str):
        raise TypeError("field name must be a string")
    if "." in name:
        table, column = name.split(".", 1)
        if column not in columns.get(table, set()):
            raise ValueError(f"unknown referenced field: {name}")
        return name
    owners = [table for table, names in columns.items() if name in names]
    if not owners:
        raise ValueError(f"unknown referenced field: {name}")
    if len(owners) > 1:
        raise ValueError(f"ambiguous referenced field {name!r}; use table.column")
    return name


def _quote_identifier(name: str) -> str:
    parts = name.split(".", 1)
    return ".".join('"' + part.replace('"', '""') + '"' for part in parts)


def _compile_node(node: dict[str, Any], params: list[Any]) -> str:
    op = node["op"]
    if op == "field":
        return _quote_identifier(node["field"])
    if op == "literal":
        params.append(node["value"])
        return "?"
    if op == "sum":
        return f"SUM({_compile_node(node['item'], params)})"
    if op == "count_distinct":
        return f"COUNT(DISTINCT {_quote_identifier(node['field'])})"
    if op == "count_rows":
        return "COUNT(*)"
    if op == "is_null":
        return f"{_quote_identifier(node['field'])} IS NULL"
    if op in {"eq", "ne"} and node["value"] is None:
        return (
            f"{_quote_identifier(node['field'])} IS {'NOT ' if op == 'ne' else ''}NULL"
        )
    if op in {"eq", "ne", "gt", "gte", "lt", "lte"}:
        params.append(node["value"])
        operator = {
            "eq": "=",
            "ne": "<>",
            "gt": ">",
            "gte": ">=",
            "lt": "<",
            "lte": "<=",
        }[op]
        return f"{_quote_identifier(node['field'])} {operator} ?"
    if op == "in":
        params.extend(node["values"])
        return f"{_quote_identifier(node['field'])} IN ({', '.join('?' for _ in node['values'])})"
    if op in {"and", "or"}:
        return (
            "("
            + f" {op.upper()} ".join(
                _compile_node(item, params) for item in node["items"]
            )
            + ")"
        )
    if op == "not":
        return f"NOT ({_compile_node(node['item'], params)})"
    symbols = {"add": "+", "sub": "-", "mul": "*", "div": "/"}
    left, right = node["left"], node["right"]
    left_sql = _compile_node(left, params) if isinstance(left, dict) else "?"
    if not isinstance(left, dict):
        params.append(left)
    right_sql = _compile_node(right, params) if isinstance(right, dict) else "?"
    if not isinstance(right, dict):
        params.append(right)
    if op == "div":
        return f"(1.0 * {left_sql} / NULLIF({right_sql}, 0))"
    return f"({left_sql} {symbols[op]} {right_sql})"
