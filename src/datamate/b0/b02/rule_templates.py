"""Bind a small approved rulebook formula library to explicit schema roles.

This library recognizes exact reviewed source clauses, never topic names alone.
New split rules and overrides remain descriptive until separately reviewed.
"""

from __future__ import annotations

import unicodedata
from dataclasses import replace
from typing import Any

from .contracts import BusinessRule, SchemaCatalog
from .rule_compiler import BusinessRuleCompiler

# These are split-default business clauses, not business-specific schema mappings.
_APPROVED_TEXT = {
    "revenue": "Doanh thu một đơn | tổng **thành tiền các dòng hàng** (đã trừ giảm giá trên từng dòng). **Không** trừ giảm giá trên cả đơn (khuyến mãi theo tổng tiền đơn, voucher shop), **không** cộng thuế VAT, **không** gồm phí giao hàng. **Tiền hàng**, **tiền bán** của đơn bán cùng nghĩa với doanh thu",
    "gross_profit": "Lãi gộp | doanh thu (§1) trừ giá vốn của hàng đã bán. Giá vốn của mỗi dòng bán bằng số lượng nhân với **giá vốn ghi trên dòng bán** (cho **một đơn vị bán**, cùng đơn vị với đơn giá). Không tự tính lại giá vốn từ phiếu nhập hay từ lô",
    "sold_qty_base": "Bán chạy | theo **số lượng quy về đơn vị cơ bản**, không theo số dòng hay số tiền; bỏ đơn huỷ, trả. Mặt hàng khác đơn vị cơ bản vẫn xếp chung theo số đó. **Bán nhiều nhất**, **bán được nhiều nhất**, **hot nhất** cùng nghĩa với **bán chạy nhất**",
}
_ROLES = {
    "revenue": {"line_amount"},
    "gross_profit": {"line_amount", "quantity", "unit_cost"},
    "sold_qty_base": {"base_quantity"},
}
_SALES_REQUIREMENTS = (
    "valid_revenue_orders",  # Whole returned orders excluded, including partial returns.
    "order_date_scope",  # Caller applied the period using the order date/as_of_date.
    "sales_line_grain",  # No duplicate export lines or join fanout.
)
_REVENUE_REQUIREMENTS = (
    "line_amount_after_line_discount",
    "line_amount_excludes_order_discount_vat_shipping",
)
_REQUIREMENTS = {
    "revenue": _SALES_REQUIREMENTS + _REVENUE_REQUIREMENTS,
    "gross_profit": _SALES_REQUIREMENTS
    + _REVENUE_REQUIREMENTS
    + (
        "unit_cost_recorded_at_sale",
        "quantity_and_cost_same_selling_unit",
    ),
    "sold_qty_base": _SALES_REQUIREMENTS
    + ("quantity_in_base_unit", "exclude_service_fee_items"),
}


class RuleTemplateBinder:
    """Compile reviewed formulas only after explicit upstream evidence is supplied."""

    def requirements(self, template: str) -> tuple[str, ...]:
        """Expose requirements so the caller can collect evidence instead of guessing."""
        if template not in _REQUIREMENTS:
            raise ValueError(f"unsupported rule template: {template}")
        return _REQUIREMENTS[template]

    def bind(
        self,
        rule: BusinessRule,
        template: str,
        bindings: dict[str, str],
        schema: SchemaCatalog,
        evidence: dict[str, str],
    ) -> BusinessRule:
        """Return a bound or invalid rule; never silently satisfy preconditions.

        Evidence maps each required guarantee to a non-empty upstream trace/source.
        Formula validation alone does not prove the caller applied a filter correctly.
        The caller must pass a rule selected by RuleResolver and execute its planned
        filtered relation without fanout. This component emits only a SQL fragment.
        """
        requirements = self.requirements(template)
        if rule.status not in {"descriptive", "validated"}:
            raise ValueError("invalid or conflicting source rule cannot be bound")
        if not rule.source or _normalize(rule.text) != _normalize(
            _APPROVED_TEXT[template]
        ):
            raise ValueError(
                "source clause differs from the reviewed formula; keep it descriptive"
            )
        if set(bindings) != _ROLES[template]:
            raise ValueError(
                f"template {template} requires exactly these roles: {sorted(_ROLES[template])}"
            )
        qualified = _qualify_bindings(bindings, schema)
        expression = _expression(template, qualified)
        # Reuse field/DSL validation and never accept arbitrary SQL from bindings.
        BusinessRuleCompiler().compile_expression(expression, schema)
        missing = [
            key
            for key in requirements
            if not isinstance(evidence.get(key), str) or not evidence[key].strip()
        ]
        fields = tuple(sorted(set(qualified.values())))
        return replace(
            rule,
            expression=expression,
            required_fields=fields,
            status="invalid" if missing else "validated",
            requirements=requirements,
            binding_evidence=tuple(
                f"{key}: {evidence[key]}" for key in requirements if key not in missing
            ),
            validation_messages=tuple(
                f"missing semantic evidence: {key}" for key in missing
            ),
        )


def _normalize(text: str) -> str:
    return " ".join(unicodedata.normalize("NFC", text).split())


def _qualify_bindings(
    bindings: dict[str, str], schema: SchemaCatalog
) -> dict[str, str]:
    columns = {
        table.name: {column.name for column in table.columns} for table in schema.tables
    }
    result: dict[str, str] = {}
    tables: set[str] = set()
    for role, field in bindings.items():
        if not isinstance(field, str):
            raise TypeError("schema role bindings must be field names")
        if "." in field:
            table, column = field.split(".", 1)
            if column not in columns.get(table, set()):
                raise ValueError(f"unknown field binding: {field}")
        else:
            owners = [name for name, names in columns.items() if field in names]
            if len(owners) != 1:
                raise ValueError(f"missing or ambiguous field binding: {field}")
            table, column = owners[0], field
        tables.add(table)
        result[role] = f"{table}.{column}"
    if len(tables) != 1:
        raise ValueError(
            "formula roles must share one sales-line relation; plan joins upstream"
        )
    return result


def _expression(template: str, bindings: dict[str, str]) -> dict[str, Any]:
    fields = {role: {"op": "field", "field": name} for role, name in bindings.items()}
    if template == "revenue":
        item = fields["line_amount"]
    elif template == "sold_qty_base":
        item = fields["base_quantity"]
    else:
        item = {
            "op": "sub",
            "left": fields["line_amount"],
            "right": {
                "op": "mul",
                "left": fields["quantity"],
                "right": fields["unit_cost"],
            },
        }
    return {"op": "sum", "item": item}
