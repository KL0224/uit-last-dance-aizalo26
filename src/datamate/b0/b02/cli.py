"""Build Business Context JSON from producer metadata and active documents."""

from __future__ import annotations

import argparse
import json
import sys

from datamate.b0.b01.metadata_adapter import JSONMetadataProvider
from datamate.b0.b01.schema_catalog import SchemaCatalogBuilder
from datamate.b0.b02.context_service import BusinessContextService
from datamate.b0.b02.contracts import ContractBuilder
from datamate.b0.b02.rule_compiler import BusinessRuleCompiler


def main(argv: list[str] | None = None) -> int:
    """Read metadata, build the contract, and write JSON to stdout."""
    if (argv if argv is not None else sys.argv[1:])[:1] == ["prepare"]:
        return prepare_main((argv if argv is not None else sys.argv[1:])[1:])
    parser = argparse.ArgumentParser(
        description="Prepare B01/B02 Business Context JSON"
    )
    parser.add_argument(
        "--metadata", required=True, help="Data Foundation metadata JSON v1.0"
    )
    parser.add_argument("--business-id", required=True)
    parser.add_argument(
        "--document",
        action="append",
        default=[],
        help="Active rulebook/README; repeat for each document",
    )
    args = parser.parse_args(argv)
    service = BusinessContextService(
        JSONMetadataProvider(args.metadata),
        SchemaCatalogBuilder(),
        BusinessRuleCompiler(),
        ContractBuilder(),
    )
    try:
        context = service.prepare(args.business_id, args.document)
        payload = json.dumps(context.to_dict(), ensure_ascii=False, allow_nan=False)
    except (OSError, TypeError, ValueError) as exc:
        sys.stderr.write(f"DataMate metadata error: {exc}\n")
        return 1
    sys.stdout.write(payload + "\n")
    return 0


def prepare_main(argv: list[str]) -> int:
    from datamate.b0.b01.ingestion import PreparationConfig, prepare_business

    parser = argparse.ArgumentParser(
        description="Prepare raw business files into DuckDB and context JSON"
    )
    parser.add_argument("--business-dir", required=True)
    parser.add_argument("--output-dir", required=True)
    parser.add_argument("--rulebook")
    parser.add_argument("--calendar")
    parser.add_argument(
        "--config", help="JSON PreparationConfig, including source_overrides"
    )
    args = parser.parse_args(argv)
    try:
        from pathlib import Path

        config = (
            PreparationConfig(**json.loads(Path(args.config).read_text()))
            if args.config
            else None
        )
        result = prepare_business(
            args.business_dir,
            args.output_dir,
            rulebook=args.rulebook,
            calendar=args.calendar,
            config=config,
        )
        print(json.dumps(result.to_dict(), ensure_ascii=False))
    except (OSError, TypeError, ValueError) as exc:
        sys.stderr.write(f"DataMate preparation error: {exc}\n")
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

