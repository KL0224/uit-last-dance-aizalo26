"""Data contracts for B0.2 Context & Business Rules (DataMate 2026)."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from datamate.b0.b01.contracts import (
    ColumnMetadata,
    JoinEdge,
    JoinStatistics,
    KeyCandidate,
    RelationshipEvidence,
    SchemaCatalog,
    TableMetadata,
)

CONTRACT_VERSION = "1.0"


@dataclass(frozen=True)
class BusinessRule:
    """Business rule specification with provenance, scope, expression, and validation state."""

    rule_id: str
    text: str
    source: str
    scope: str
    precedence: int
    status: str = "descriptive"
    required_fields: tuple[str, ...] = ()
    expression: dict[str, Any] | None = None
    validation_messages: tuple[str, ...] = ()
    topic: str | None = None
    industry: str | None = None
    question_id: str | None = None
    requirements: tuple[str, ...] = ()
    binding_evidence: tuple[str, ...] = ()


@dataclass(frozen=True)
class RuleCatalog:
    """Catalog of extracted or parsed business rules."""

    rules: tuple[BusinessRule, ...]
    warnings: tuple[str, ...] = ()
    business_id: str | None = None


@dataclass(frozen=True)
class BusinessContext:
    """Complete Business Context contract packaging Schema Catalog and Rule Catalog."""

    contract_version: str
    business_id: str
    schema_catalog: SchemaCatalog
    rule_catalog: RuleCatalog
    data_profiling: dict[str, Any] | None = None
    business_metadata: dict[str, Any] | None = None
    answerability_constraints: dict[str, Any] | None = None

    normalized_data_handle: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-serializable contract with explicit contract version."""
        payload = asdict(self)
        # Internal samples used for inference must never be copied into the downstream contract.
        for table in payload["schema_catalog"]["tables"]:
            table.pop("profile_rows", None)
        for edge in payload["schema_catalog"]["join_graph"]:
            for optional in ("statistics", "relationship_evidence"):
                if edge[optional] is None:
                    edge.pop(optional)
        if self.normalized_data_handle is None:
            payload.pop("normalized_data_handle", None)
        return payload


class ContractBuilder:
    """Validate and combine B01/B02 outputs without inventing absent metadata."""

    def build(
        self,
        business_id: str,
        schema_catalog: SchemaCatalog,
        rule_catalog: RuleCatalog,
        data_profiling: dict[str, Any] | None = None,
        business_metadata: dict[str, Any] | None = None,
        answerability_constraints: dict[str, Any] | None = None,
        normalized_data_handle: dict[str, Any] | None = None,
    ) -> BusinessContext:
        """Build a business-scoped context and validate its internal references."""
        if not business_id.strip():
            raise ValueError("business_id must be non-empty")
        if (
            rule_catalog.business_id is not None
            and rule_catalog.business_id != business_id
        ):
            raise ValueError("rule_catalog business_id does not match BusinessContext")
        table_names = {table.name for table in schema_catalog.tables}
        if len(table_names) != len(schema_catalog.tables):
            raise ValueError("schema_catalog contains duplicate table names")
        columns_by_table = {
            table.name: {column.name for column in table.columns}
            for table in schema_catalog.tables
        }
        for table in schema_catalog.tables:
            if not table.name.strip() or len(columns_by_table[table.name]) != len(
                table.columns
            ):
                raise ValueError(
                    f"table {table.name!r} has an empty name or duplicate columns"
                )
            if table.row_count is not None and table.row_count < 0:
                raise ValueError(f"table {table.name} has negative row_count")
            for column in table.columns:
                if not column.name.strip():
                    raise ValueError(f"table {table.name} has an empty column name")
                if column.null_ratio is not None and not 0 <= column.null_ratio <= 1:
                    raise ValueError(
                        f"column {table.name}.{column.name} has invalid null_ratio"
                    )
                if column.cardinality is not None and column.cardinality < 0:
                    raise ValueError(
                        f"column {table.name}.{column.name} has negative cardinality"
                    )
        for edge in schema_catalog.join_graph:
            if (
                edge.left_table not in table_names
                or edge.right_table not in table_names
            ):
                raise ValueError(f"join edge references unknown table: {edge}")
            if any(
                left not in columns_by_table[edge.left_table]
                or right not in columns_by_table[edge.right_table]
                for left, right in edge.key_pairs
            ):
                raise ValueError(f"join edge references unknown column: {edge}")
            if len({left for left, _ in edge.key_pairs}) != len(edge.key_pairs) or len(
                {right for _, right in edge.key_pairs}
            ) != len(edge.key_pairs):
                raise ValueError("join key columns cannot be repeated")
            if not 0 <= edge.confidence <= 1:
                raise ValueError(f"join edge has invalid confidence: {edge}")
        all_columns = (
            set().union(*columns_by_table.values()) if columns_by_table else set()
        )
        column_owners: dict[str, set[str]] = {}
        for table_name, columns in columns_by_table.items():
            for column_name in columns:
                column_owners.setdefault(column_name, set()).add(table_name)
        rule_ids = [rule.rule_id for rule in rule_catalog.rules]
        if len(set(rule_ids)) != len(rule_ids):
            raise ValueError("rule_catalog contains duplicate rule IDs")
        for rule in rule_catalog.rules:
            if rule.expression is not None:
                for field_name in rule.required_fields:
                    if "." in field_name:
                        table_name, column_name = field_name.split(".", 1)
                        valid = column_name in columns_by_table.get(table_name, set())
                    else:
                        valid = (
                            field_name in all_columns
                            and len(column_owners[field_name]) == 1
                        )
                    if not valid:
                        raise ValueError(
                            f"structured rule {rule.rule_id} references missing or ambiguous field {field_name!r}"
                        )
        return BusinessContext(
            contract_version="1.1" if normalized_data_handle else CONTRACT_VERSION,
            business_id=business_id,
            schema_catalog=schema_catalog,
            rule_catalog=rule_catalog,
            data_profiling=data_profiling,
            business_metadata=business_metadata,
            answerability_constraints=answerability_constraints,
            normalized_data_handle=normalized_data_handle,
        )


__all__ = [
    "CONTRACT_VERSION",
    "BusinessRule",
    "RuleCatalog",
    "BusinessContext",
    "ContractBuilder",
    # re-export B01 schema contracts for unified access
    "ColumnMetadata",
    "TableMetadata",
    "KeyCandidate",
    "JoinEdge",
    "JoinStatistics",
    "RelationshipEvidence",
    "SchemaCatalog",
]

