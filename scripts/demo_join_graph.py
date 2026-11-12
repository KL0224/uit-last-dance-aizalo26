"""Read a prepared contract and optionally count rows along a validated JOIN path.

This is a downstream example, not a question planner or a general SQL executor.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

import duckdb

from datamate.ingestion.contracts import SchemaCatalog
from datamate.context.contracts import BusinessRule, ContractBuilder, RuleCatalog
from datamate.ingestion.join_graph import JoinGraphNavigator, JoinPredicateCompiler
from datamate.ingestion.metadata_adapter import BusinessContextSchemaReader
from datamate.context.rule_compiler import BusinessRuleCompiler
from datamate.context.rule_resolver import RuleResolver


def resolve_table(
    connection: duckdb.DuckDBPyConnection, catalog: SchemaCatalog, name: str
) -> str:
    """Accept an exact SQL name or an unambiguous original SQLite/XLSX table name."""
    if name in {table.name for table in catalog.tables}:
        return name
    matches = connection.execute(
        "SELECT DISTINCT normalized_table FROM meta.source_mapping WHERE sheet=?",
        [name],
    ).fetchall()
    if len(matches) != 1:
        raise ValueError(
            f"missing or ambiguous table: {name}; use an exact catalog name"
        )
    return matches[0][0]


def read_rule_catalog(payload: dict[str, Any], schema: SchemaCatalog) -> RuleCatalog:
    """Rehydrate producer-owned rules for the sample, without changing validation."""
    obj = payload["rule_catalog"]
    rules = []
    tuple_fields = {
        "required_fields",
        "validation_messages",
        "requirements",
        "binding_evidence",
    }
    for value in obj["rules"]:
        value = dict(value)
        for name in tuple_fields & value.keys():
            if not isinstance(value[name], list) or any(
                not isinstance(item, str) for item in value[name]
            ):
                raise ValueError(f"rule {name} must be an array of strings")
            value[name] = tuple(value[name])
        rules.append(BusinessRule(**value))
    catalog = RuleCatalog(
        tuple(rules), tuple(obj.get("warnings", [])), obj.get("business_id")
    )
    ContractBuilder().build(payload["business_id"], schema, catalog)
    return catalog


def run_demo(
    bundle: Path,
    source: str,
    target: str,
    *,
    count_rows: bool = False,
    rule_topic: str | None = None,
    industry: str | None = None,
) -> dict[str, Any]:
    """Count a structural path; report B02 execution prerequisites separately."""
    payload = json.loads((bundle / "business_context.json").read_text(encoding="utf-8"))
    if payload.get("normalized_data_handle") != {
        "engine": "duckdb",
        "sql_dialect": "duckdb",
        "database": "data.duckdb",
        "schema": "main",
    }:
        raise ValueError("example requires a prepared DuckDB bundle")
    catalog = BusinessContextSchemaReader().read(payload)
    with duckdb.connect(str(bundle / "data.duckdb"), read_only=True) as connection:
        connection.execute("SET threads=2")
        connection.execute("SET memory_limit='512MB'")
        source = resolve_table(connection, catalog, source)
        target = resolve_table(connection, catalog, target)
        result = JoinGraphNavigator().describe_path(catalog, source, target)
        output = {
            "status": result.status,
            "warnings": result.warnings,
            "path": [],
            "sql": None,
        }
        if result.status == "validated_path":
            current = source
            sql = 'SELECT COUNT(*) FROM "' + source.replace('"', '""') + '"'
            for edge in result.path:
                neighbor = (
                    edge.right_table if current == edge.left_table else edge.left_table
                )
                predicate = JoinPredicateCompiler().compile(edge, catalog)
                sql += ' JOIN "' + neighbor.replace('"', '""') + '" ON ' + predicate
                output["path"].append(
                    {
                        "from": current,
                        "to": neighbor,
                        "predicate": predicate,
                        "cardinality": edge.cardinality,
                        "fanout_warning": edge.fanout_warning,
                    }
                )
                current = neighbor
            output["sql"] = sql
            if count_rows:
                output["joined_row_count"] = connection.execute(sql).fetchone()[0]
        if rule_topic is not None:
            rules = read_rule_catalog(payload, catalog)
            resolved = RuleResolver().resolve(
                rules, payload["business_id"], industry=industry
            )
            matching = [rule for rule in resolved.rules if rule.topic == rule_topic]
            decision = {
                "status": "no_selected_rule",
                "sql_fragment": None,
                "warnings": resolved.warnings,
                "blocked_topics": resolved.blocked_topics,
            }
            if len(matching) == 1:
                rule = matching[0]
                decision.update(
                    rule_id=rule.rule_id,
                    source=rule.source,
                    rule_status=rule.status,
                    status="missing_binding_or_evidence",
                    reason="A descriptive rule needs caller-reviewed bindings and semantic evidence.",
                )
                if rule.status == "validated" and rule.expression is not None:
                    fragment, parameters = BusinessRuleCompiler().compile_rule(
                        rule, catalog
                    )
                    decision.update(
                        status="compiled_fragment_only",
                        sql_fragment=fragment,
                        parameters=parameters,
                        reason="Caller still owns filters, grain and execution; COUNT above is structural only.",
                    )
            output["business_rule"] = decision
        return output


def main() -> None:
    """Read an existing DuckDB bundle, preserving statuses and business data."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--bundle", type=Path, required=True)
    parser.add_argument("--source", required=True)
    parser.add_argument("--target", required=True)
    parser.add_argument("--count-rows", action="store_true")
    parser.add_argument(
        "--rule-topic", help="Resolve one B02 topic from the persisted rule catalog"
    )
    parser.add_argument("--industry")
    args = parser.parse_args()
    result = run_demo(
        args.bundle,
        args.source,
        args.target,
        count_rows=args.count_rows,
        rule_topic=args.rule_topic,
        industry=args.industry,
    )
    print(json.dumps(result, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
