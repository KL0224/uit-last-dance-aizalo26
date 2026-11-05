"""Build Business Context JSON from producer metadata and active documents."""

from __future__ import annotations

import argparse
import json
import sys

from datamate.context_service import BusinessContextService
from datamate.contracts import ContractBuilder
from datamate.metadata_adapter import JSONMetadataProvider
from datamate.rule_compiler import BusinessRuleCompiler
from datamate.schema_catalog import SchemaCatalogBuilder


def main(argv: list[str] | None = None) -> int:
    """Read metadata, build the contract, and write JSON to stdout."""
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


if __name__ == "__main__":
    raise SystemExit(main())
