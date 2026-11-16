"""Runtime boundary exposing one Business Context to Planner and Grounding."""

from __future__ import annotations

from dataclasses import dataclass
import json
import logging
from pathlib import Path
import time
from typing import Any, Mapping, Sequence

from datamate.grounding.adapters import B02ContextAdapter
from datamate.grounding.protocols import BusinessContextProtocol

CONTEXT_FILE_MISSING = "CONTEXT_FILE_MISSING"
CONTEXT_JSON_INVALID = "CONTEXT_JSON_INVALID"
CONTEXT_CONTRACT_INVALID = "CONTEXT_CONTRACT_INVALID"
BUSINESS_ID_MISMATCH = "BUSINESS_ID_MISMATCH"

_SUPPORTED_CONTRACT_VERSIONS = frozenset({"1.0", "1.1"})
_MAX_JOIN_PAIR_CHECKS = 300
_JOIN_DISCOVERY_BUDGET_SEC = 20.0

logger = logging.getLogger(__name__)


def _quote_identifier(identifier: str) -> str:
    return '"' + str(identifier).replace('"', '""') + '"'


def sync_unit_conversions_to_bundle(
    database_path: Path,
    ctx_dict: dict[str, Any],
    unit_conversions: Sequence[Mapping[str, Any]],
) -> None:
    """Materialize unit_conversions into DuckDB and ensure schema_catalog lists it."""
    if not unit_conversions:
        return
    import duckdb

    with duckdb.connect(str(database_path)) as con:
        con.execute(
            "CREATE TABLE IF NOT EXISTS main.unit_conversions "
            "(item_name VARCHAR, from_unit VARCHAR, to_unit VARCHAR, factor DECIMAL(38,12))"
        )
        con.execute("DELETE FROM main.unit_conversions")
        for u in unit_conversions:
            con.execute(
                "INSERT INTO main.unit_conversions VALUES (?, ?, ?, ?)",
                [
                    str(u.get("item_name")),
                    str(u.get("from_unit")),
                    str(u.get("to_unit")),
                    float(u.get("factor", 1.0)),
                ],
            )
    schema_cat = ctx_dict.setdefault("schema_catalog", {})
    tables = list(schema_cat.get("tables") or [])
    if all(t.get("name") != "unit_conversions" for t in tables):
        tables.append(
            {
                "name": "unit_conversions",
                "columns": [
                    {"name": "item_name", "data_type": "VARCHAR", "nullable": False},
                    {"name": "from_unit", "data_type": "VARCHAR", "nullable": False},
                    {"name": "to_unit", "data_type": "VARCHAR", "nullable": False},
                    {"name": "factor", "data_type": "DECIMAL(38,12)", "nullable": False},
                ],
                "row_count": len(unit_conversions),
                "grain": "Quy đổi đơn vị tính (1 from_unit = factor to_unit)",
                "provenance": "B02 semantic unit conversions",
            }
        )
    schema_cat["tables"] = tables


def enrich_context_from_duckdb(payload: dict[str, Any], database_path: Path) -> None:
    """Add runtime-only samples and conservative join candidates in place."""
    import duckdb

    with duckdb.connect(str(database_path), read_only=True) as connection:
        categorical_samples: dict[str, dict[str, list[Any]]] = {}
        tables = [row[0] for row in connection.execute("SHOW TABLES").fetchall()]
        columns_by_table: dict[str, list[str]] = {}
        for table_name in tables:
            categorical_samples[table_name] = {}
            columns = connection.execute(
                f"DESCRIBE {_quote_identifier(table_name)}"
            ).fetchall()
            columns_by_table[table_name] = [column[0] for column in columns]
            for column_name, column_type, *_ in columns:
                if column_name.startswith("__dm_"):
                    continue
                if column_type in {"VARCHAR", "BOOLEAN"} or "INT" in column_type:
                    try:
                        distinct_count = connection.execute(
                            f"SELECT COUNT(DISTINCT {_quote_identifier(column_name)}) "
                            f"FROM {_quote_identifier(table_name)}"
                        ).fetchone()[0]
                        if 0 < distinct_count <= 12:
                            values = connection.execute(
                                f"SELECT DISTINCT {_quote_identifier(column_name)} "
                                f"FROM {_quote_identifier(table_name)} "
                                f"WHERE {_quote_identifier(column_name)} IS NOT NULL LIMIT 12"
                            ).fetchall()
                            categorical_samples[table_name][column_name] = [
                                row[0] for row in values
                            ]
                    except Exception as exc:
                        logger.debug(
                            "categorical sample skipped for %s.%s: %s",
                            table_name,
                            column_name,
                            exc,
                        )
        payload["categorical_samples"] = categorical_samples

        schema_catalog = payload.setdefault("schema_catalog", {})
        existing_edges = (
            schema_catalog.get("join_graph")
            or schema_catalog.get("join_edges")
            or []
        )
        if existing_edges:
            return

        id_keywords = ("id", "ma_", "so_", "sku", "code", "hd")
        discovered_edges: list[tuple[int, dict[str, Any]]] = []
        checks = 0
        deadline = time.perf_counter() + _JOIN_DISCOVERY_BUDGET_SEC
        for index, left_table in enumerate(tables):
            for left_column in columns_by_table[left_table]:
                if left_column.startswith("__dm_") or not any(
                    key in left_column.lower() for key in id_keywords
                ):
                    continue
                for right_table in tables[index + 1 :]:
                    for right_column in columns_by_table[right_table]:
                        if right_column.startswith("__dm_") or not any(
                            key in right_column.lower() for key in id_keywords
                        ):
                            continue
                        if (
                            checks >= _MAX_JOIN_PAIR_CHECKS
                            or time.perf_counter() > deadline
                        ):
                            logger.warning(
                                "context enrichment stopped at join discovery budget"
                            )
                            schema_catalog["join_graph"] = [
                                edge
                                for _, edge in sorted(
                                    discovered_edges, key=lambda item: -item[0]
                                )
                            ]
                            return
                        checks += 1
                        try:
                            overlap = connection.execute(
                                f"SELECT COUNT(*) FROM ("
                                f"SELECT DISTINCT {_quote_identifier(left_column)} AS v "
                                f"FROM {_quote_identifier(left_table)} "
                                f"WHERE {_quote_identifier(left_column)} IS NOT NULL"
                                f") candidate WHERE candidate.v IN ("
                                f"SELECT {_quote_identifier(right_column)} "
                                f"FROM {_quote_identifier(right_table)} "
                                f"WHERE {_quote_identifier(right_column)} IS NOT NULL)"
                            ).fetchone()[0]
                        except Exception as exc:
                            logger.debug(
                                "join check skipped %s.%s~%s.%s: %s",
                                left_table,
                                left_column,
                                right_table,
                                right_column,
                                exc,
                            )
                            continue
                        if overlap > 0:
                            discovered_edges.append(
                                (
                                    overlap,
                                    {
                                        "left_table": left_table,
                                        "left_column": left_column,
                                        "right_table": right_table,
                                        "right_column": right_column,
                                        "cardinality": "unknown",
                                        "status": "candidate",
                                        "confidence": 0.5,
                                        "evidence": [
                                            f"runtime value overlap: {overlap} distinct keys"
                                        ],
                                    },
                                )
                            )
        schema_catalog["join_graph"] = [
            edge for _, edge in sorted(discovered_edges, key=lambda item: -item[0])
        ]


class BusinessContextRuntimeError(RuntimeError):
    """Report a stable context-boundary error without exposing payload data."""

    def __init__(self, *, code: str, bundle_dir: Path, message: str) -> None:
        self.code = code
        self.bundle_dir = bundle_dir
        super().__init__(f"{code}: {message} (bundle={bundle_dir})")


@dataclass(frozen=True)
class BusinessRuntimeContext:
    """Planner and Grounding views derived from the same validated payload."""

    business_id: str
    bundle_dir: Path
    planner_context: dict[str, Any]
    grounding_context: BusinessContextProtocol


class BusinessContextRuntimeLoader:
    """Load and validate one prepared business bundle for runtime consumers."""

    def __init__(self) -> None:
        self._cache: dict[Path, BusinessRuntimeContext] = {}

    def load(
        self,
        bundle_dir: str | Path,
        *,
        expected_business_id: str | None = None,
    ) -> BusinessRuntimeContext:
        """Return Planner/Grounding views or raise a classified boundary error."""
        resolved_bundle = Path(bundle_dir).resolve()
        cached = self._cache.get(resolved_bundle)
        if cached is not None:
            self._validate_expected_business_id(
                cached.business_id,
                bundle_dir=resolved_bundle,
                expected_business_id=expected_business_id,
            )
            return cached

        payload = self._read_payload(resolved_bundle)
        business_id = self._validate_identity(
            payload,
            bundle_dir=resolved_bundle,
            expected_business_id=expected_business_id,
        )
        database_path = resolved_bundle / "data.duckdb"
        if database_path.is_file():
            try:
                enrich_context_from_duckdb(payload, database_path)
            except Exception as exc:
                logger.warning(
                    "business context: bỏ qua enrichment từ %s: %s",
                    database_path,
                    exc,
                )

        try:
            grounding_context = B02ContextAdapter.from_dict(payload)
        except (KeyError, TypeError, ValueError) as exc:
            raise BusinessContextRuntimeError(
                code=CONTEXT_CONTRACT_INVALID,
                bundle_dir=resolved_bundle,
                message=f"Business Context adapter rejected the contract: {exc}",
            ) from exc

        if (
            not isinstance(grounding_context, BusinessContextProtocol)
            or grounding_context.business_id != business_id
        ):
            raise BusinessContextRuntimeError(
                code=CONTEXT_CONTRACT_INVALID,
                bundle_dir=resolved_bundle,
                message="Grounding view does not match the Business Context contract",
            )

        runtime = BusinessRuntimeContext(
            business_id=business_id,
            bundle_dir=resolved_bundle,
            planner_context=payload,
            grounding_context=grounding_context,
        )
        self._cache[resolved_bundle] = runtime
        return runtime

    @staticmethod
    def _read_payload(bundle_dir: Path) -> dict[str, Any]:
        context_path = bundle_dir / "business_context.json"
        if not context_path.is_file():
            raise BusinessContextRuntimeError(
                code=CONTEXT_FILE_MISSING,
                bundle_dir=bundle_dir,
                message="business_context.json is missing",
            )
        try:
            raw_content = context_path.read_text(encoding="utf-8")
        except UnicodeError as exc:
            raise BusinessContextRuntimeError(
                code=CONTEXT_JSON_INVALID,
                bundle_dir=bundle_dir,
                message=f"business_context.json is not valid UTF-8: {exc}",
            ) from exc
        except OSError as exc:
            raise BusinessContextRuntimeError(
                code=CONTEXT_FILE_MISSING,
                bundle_dir=bundle_dir,
                message=f"business_context.json cannot be read: {exc}",
            ) from exc
        try:
            payload = json.loads(raw_content)
        except json.JSONDecodeError as exc:
            raise BusinessContextRuntimeError(
                code=CONTEXT_JSON_INVALID,
                bundle_dir=bundle_dir,
                message=f"business_context.json is not valid UTF-8 JSON: {exc}",
            ) from exc
        if not isinstance(payload, dict):
            raise BusinessContextRuntimeError(
                code=CONTEXT_CONTRACT_INVALID,
                bundle_dir=bundle_dir,
                message="Business Context JSON root must be an object",
            )
        return payload

    @staticmethod
    def _validate_identity(
        payload: dict[str, Any],
        *,
        bundle_dir: Path,
        expected_business_id: str | None,
    ) -> str:
        contract_version = payload.get("contract_version")
        if contract_version not in _SUPPORTED_CONTRACT_VERSIONS:
            raise BusinessContextRuntimeError(
                code=CONTEXT_CONTRACT_INVALID,
                bundle_dir=bundle_dir,
                message="contract_version must be '1.0' or '1.1'",
            )
        business_id = payload.get("business_id")
        if not isinstance(business_id, str) or not business_id.strip():
            raise BusinessContextRuntimeError(
                code=CONTEXT_CONTRACT_INVALID,
                bundle_dir=bundle_dir,
                message="business_id must be a non-empty string",
            )
        if expected_business_id is not None and business_id != expected_business_id:
            raise BusinessContextRuntimeError(
                code=BUSINESS_ID_MISMATCH,
                bundle_dir=bundle_dir,
                message=f"expected business_id {expected_business_id!r}, got {business_id!r}",
            )
        return business_id

    @staticmethod
    def _validate_expected_business_id(
        business_id: str,
        *,
        bundle_dir: Path,
        expected_business_id: str | None,
    ) -> None:
        if expected_business_id is not None and business_id != expected_business_id:
            raise BusinessContextRuntimeError(
                code=BUSINESS_ID_MISMATCH,
                bundle_dir=bundle_dir,
                message=f"expected business_id {expected_business_id!r}, got {business_id!r}",
            )


__all__ = [
    "BUSINESS_ID_MISMATCH",
    "CONTEXT_CONTRACT_INVALID",
    "CONTEXT_FILE_MISSING",
    "CONTEXT_JSON_INVALID",
    "BusinessContextRuntimeError",
    "BusinessContextRuntimeLoader",
    "BusinessRuntimeContext",
    "enrich_context_from_duckdb",
    "sync_unit_conversions_to_bundle",
]
