"""Schema catalog and evidence-backed join candidate inference."""

from __future__ import annotations

import re
import unicodedata
from dataclasses import replace
from itertools import combinations, islice
from typing import Any

from .contracts import JoinEdge, KeyCandidate, SchemaCatalog, TableMetadata
from .relationship_evidence import trusted_relationship


class SchemaCatalogBuilder:
    """Build candidate keys and joins from Data Foundation table metadata."""

    def __init__(self, profile_provider=None) -> None:
        self.profile_provider = profile_provider

    def build(
        self,
        tables: list[TableMetadata],
        declared_edges: list[JoinEdge] | None = None,
        *,
        business_id: str | None = None,
    ) -> SchemaCatalog:
        """Analyze supplied tables; no source data is loaded or modified here."""
        names = [table.name for table in tables]
        if len(set(names)) != len(names):
            raise ValueError("table names must be unique")
        key_candidates: list[KeyCandidate] = []
        warnings: list[str] = []
        enriched_tables: list[TableMetadata] = []
        for table in tables:
            candidates = (
                self._sql_keys(table)
                if self.profile_provider
                else _infer_keys(table, warnings)
            )
            key_candidates.extend(candidates)
            proven = [key for key in candidates if key.status == "candidate"]
            if table.grain:
                evidence = table.grain_evidence or (
                    f"upstream grain declaration; source={table.provenance or 'unspecified'}",
                )
                table = replace(table, grain_evidence=evidence)
            elif len(proven) == 1:
                key = proven[0]
                table = replace(
                    table,
                    grain="row keyed by (" + ", ".join(key.columns) + ")",
                    grain_evidence=key.evidence
                    + (
                        "structural identity only; business meaning still requires documentation",
                    ),
                )
            else:
                warnings.append(
                    f"{table.name}: business grain unknown; no unambiguous key evidence"
                )
            enriched_tables.append(table)
        tables = enriched_tables
        edges: list[JoinEdge] = []
        table_by_name = {table.name: table for table in tables}
        value_profiles = {
            (table.name, column.name): _values(table.profile_rows, column.name)
            for table in tables
            for column in table.columns
        }
        value_lists = {
            (table.name, column.name): _values_list(table.profile_rows, column.name)
            for table in tables
            for column in table.columns
        }
        declarations = declared_edges or []
        conflicts: set[tuple] = set()
        shapes: dict[tuple, set[str]] = {}
        for edge in declarations:
            signature = _edge_signature(edge)
            shape = edge.cardinality
            if edge.left_table != signature[0]:
                shape = {
                    "one_to_many": "many_to_one",
                    "many_to_one": "one_to_many",
                }.get(shape, shape)
            shapes.setdefault(signature, set()).add(shape)
        conflicts = {sig for sig, values in shapes.items() if len(values) > 1}
        for edge in declarations:
            if len({left for left, _ in edge.key_pairs}) != len(edge.key_pairs) or len(
                {right for _, right in edge.key_pairs}
            ) != len(edge.key_pairs):
                warnings.append("declared relationship repeats a join key column")
                continue
            if (
                edge.left_table not in table_by_name
                or edge.right_table not in table_by_name
            ):
                warnings.append(
                    f"declared relationship references unknown table: {edge.left_table}/{edge.right_table}"
                )
                continue
            left_columns = {
                column.name for column in table_by_name[edge.left_table].columns
            }
            right_columns = {
                column.name for column in table_by_name[edge.right_table].columns
            }
            if any(
                left not in left_columns or right not in right_columns
                for left, right in edge.key_pairs
            ):
                warnings.append(
                    f"declared relationship references unknown column: {edge.left_table}.{edge.left_column}/{edge.right_table}.{edge.right_column}"
                )
                continue
            if _edge_signature(edge) in conflicts:
                edges.append(
                    replace(
                        edge,
                        status="invalid",
                        confidence=0.0,
                        fanout_warning=True,
                        evidence=edge.evidence
                        + ("conflicting cardinality declarations; review required",),
                    )
                )
                continue
            if self.profile_provider:
                checked = self.profile_provider.check_join(edge)
                if (
                    business_id
                    and not trusted_relationship(edge, business_id)
                    and checked.status == "validated"
                ):
                    checked = replace(
                        checked,
                        status="uncertain",
                        confidence=0.0,
                        evidence=checked.evidence
                        + ("wrong-scope relationship attestation",),
                    )
                edges.append(checked)
                continue
            left = table_by_name[edge.left_table]
            right = table_by_name[edge.right_table]
            status, confidence, observed_cardinality, checks = _check_declared_edge(
                edge, left, right, business_id
            )
            edges.append(
                replace(
                    edge,
                    cardinality=observed_cardinality,
                    status=status,
                    confidence=confidence,
                    evidence=edge.evidence + checks,
                    fanout_warning=edge.fanout_warning
                    or observed_cardinality != "one_to_one",
                )
            )
        if self.profile_provider:
            return self._sql_join_candidates(tables, key_candidates, edges, warnings)
        for left_index, left in enumerate(tables):
            for right in tables[left_index + 1 :]:
                for left_col in left.columns:
                    for right_col in right.columns:
                        left_values = value_profiles[(left.name, left_col.name)]
                        right_values = value_profiles[(right.name, right_col.name)]
                        if not left_values or not right_values:
                            continue
                        shared = left_values & right_values
                        left_coverage = len(shared) / len(left_values)
                        right_coverage = len(shared) / len(right_values)
                        coverage = max(left_coverage, right_coverage)
                        right_unique = len(right_values) == len(
                            value_lists[(right.name, right_col.name)]
                        )
                        left_unique = len(left_values) == len(
                            value_lists[(left.name, left_col.name)]
                        )
                        if coverage < 0.8:
                            continue
                        # Exact-value overlap is evidence for a candidate only; it never confirms a join.
                        cardinality = _cardinality(left_unique, right_unique)
                        confidence = min(0.75, round(0.35 + 0.4 * coverage, 3))
                        warnings_for_edge = (
                            "candidate inferred from value overlap; validate semantic relationship",
                        )
                        if left_col.name.casefold() != right_col.name.casefold():
                            warnings_for_edge += (
                                "column names differ; value overlap is the evidence",
                            )
                        if cardinality != "one_to_one":
                            warnings_for_edge += (
                                f"{cardinality} join may fan out measures from the one-side",
                            )
                        inferred = JoinEdge(
                            left_table=left.name,
                            left_column=left_col.name,
                            right_table=right.name,
                            right_column=right_col.name,
                            cardinality=cardinality,
                            status="uncertain",
                            confidence=confidence,
                            evidence=(
                                f"{len(shared)} shared non-null values; directional coverage={left_coverage:.3f}/{right_coverage:.3f}",
                                "value overlap and column names do not independently prove semantic relationship",
                                "cardinality is observed on supplied rows and is not a full-table constraint",
                            )
                            + warnings_for_edge,
                            fanout_warning=cardinality != "one_to_one",
                        )
                        signature = (
                            inferred.left_table,
                            inferred.right_table,
                            inferred.key_pairs,
                        )
                        if not any(
                            (item.left_table, item.right_table, item.key_pairs)
                            == signature
                            for item in edges
                        ):
                            edges.append(inferred)
                # Composite identities with matching column names provide bounded candidates.
                # Different names require an explicit mapping from upstream documentation.
                right_names = {column.name for column in right.columns}
                left_names = {column.name for column in left.columns}
                composite_keys = {
                    key.columns
                    for key in key_candidates
                    if len(key.columns) > 1
                    and (
                        (
                            key.table == left.name
                            and set(key.columns).issubset(right_names)
                        )
                        or (
                            key.table == right.name
                            and set(key.columns).issubset(left_names)
                        )
                    )
                }
                for key in sorted(composite_keys)[:64]:
                    inferred = _infer_composite_edge(left, right, key)
                    if inferred is not None and not any(
                        item.left_table == left.name
                        and item.right_table == right.name
                        and item.key_pairs == inferred.key_pairs
                        for item in edges
                    ):
                        edges.append(inferred)
        return SchemaCatalog(
            tuple(tables), tuple(key_candidates), tuple(edges), tuple(warnings)
        )

    def _sql_join_candidates(
        self,
        tables: list[TableMetadata],
        keys: list[KeyCandidate],
        declared: list[JoinEdge],
        warnings: list[str],
    ) -> SchemaCatalog:
        """Bound structural proposals first, then verify full SQL tuples, never samples."""
        edges = list(declared)
        signatures = {_edge_signature(edge) for edge in edges}
        unique = {(key.table, key.columns) for key in keys if key.status == "candidate"}
        budget = 1024
        for left, right in combinations(tables, 2):
            proposals: set[tuple[tuple[str, str], ...]] = set()
            for lcol in left.columns:
                for rcol in right.columns:
                    left_role = self.profile_provider.column_role(left.name, lcol.name)
                    right_role = self.profile_provider.column_role(
                        right.name, rcol.name
                    )
                    non_keys = {"money", "quantity", "date", "boolean", "status"}
                    if (
                        (
                            left_role == "identifier"
                            or right_role == "identifier"
                            or _identifier(lcol.name)
                            or _identifier(lcol.provenance or "")
                        )
                        and left_role not in non_keys
                        and right_role not in non_keys
                        and (_column_tokens(lcol) & _column_tokens(rcol))
                        and _compatible_types(lcol.data_type, rcol.data_type)
                    ):
                        if lcol.cardinality == rcol.cardinality == 1:
                            warning = "constant identifiers excluded from inferred JOINs; declare single-value relationships explicitly"
                            if warning not in warnings:
                                warnings.append(warning)
                            continue
                        proposals.add(((lcol.name, rcol.name),))
            for table, other in ((left, right), (right, left)):
                other_columns = {column.name: column for column in other.columns}
                for key in keys:
                    if (
                        key.table != table.name
                        or key.status != "candidate"
                        or len(key.columns) < 2
                    ):
                        continue
                    if not all(
                        _identifier(c) or c in {"so_thu_tu", "line_no", "seq"}
                        for c in key.columns
                    ):
                        continue
                    if set(key.columns).issubset(other_columns):
                        pairs = tuple((c, c) for c in key.columns)
                        if all(
                            _compatible_types(
                                next(
                                    c.data_type for c in table.columns if c.name == name
                                ),
                                other_columns[name].data_type,
                            )
                            for name in key.columns
                        ):
                            proposals.add(pairs)

            def priority(
                pairs: tuple[tuple[str, str], ...],
                left_name: str = left.name,
                right_name: str = right.name,
            ) -> tuple:
                parent_key = (left_name, tuple(a for a, _ in pairs)) in unique or (
                    right_name,
                    tuple(b for _, b in pairs),
                ) in unique
                return (not parent_key, -len(pairs), pairs)

            ordered = sorted(proposals, key=priority)
            if len(ordered) > 32:
                warnings.append(
                    f"{left.name}/{right.name}: JOIN search limited to 32 structural proposals"
                )
            for pairs in ordered[:32]:
                edge = JoinEdge(
                    left.name,
                    pairs[0][0],
                    right.name,
                    pairs[0][1],
                    "unknown",
                    "uncertain",
                    0.0,
                    (),
                    additional_key_pairs=pairs[1:],
                )
                signature = _edge_signature(edge)
                if signature in signatures:
                    continue
                if budget == 0:
                    warnings.append(
                        "JOIN search stopped at 1024 full-table SQL checks; declarations are not limited"
                    )
                    return SchemaCatalog(
                        tuple(tables), tuple(keys), tuple(edges), tuple(warnings)
                    )
                budget -= 1
                checked = self.profile_provider.check_join(edge)
                stats = checked.statistics
                if (
                    stats
                    and stats.matched_distinct
                    and max(stats.left_coverage, stats.right_coverage) >= 0.8
                ):
                    edges.append(checked)
                    signatures.add(signature)
        return SchemaCatalog(tuple(tables), tuple(keys), tuple(edges), tuple(warnings))

    def _sql_keys(self, table: TableMetadata) -> list[KeyCandidate]:
        columns = {c.name: c for c in table.columns}
        declared = {(c,) for c in table.primary_key_candidates} | set(
            table.composite_key_candidates
        )
        eligible = [
            c.name
            for c in table.columns
            if c.null_ratio == 0 and (c.cardinality or 0) > 1
        ]
        keys = [(c,) for c in eligible if columns[c].cardinality == table.row_count]
        keys += [
            pair
            for pair in islice(combinations(eligible, 2), 256)
            if (columns[pair[0]].cardinality or 0) * (columns[pair[1]].cardinality or 0)
            >= (table.row_count or 0)
        ]
        keys += sorted(declared - set(keys))
        found = []
        proven = []
        for key in keys:
            if not set(key).issubset(columns):
                continue
            if key not in declared and any(set(k).issubset(key) for k in proven):
                continue
            result = self.profile_provider.check_key(table, key)
            if result.status == "candidate":
                proven.append(key)
                found.append(result)
            elif key in declared:
                found.append(result)
        return found


def _hashable(value: Any) -> Any:
    try:
        hash(value)
        return value
    except TypeError:
        return repr(value)


def _edge_signature(edge: JoinEdge) -> tuple:
    forward = (edge.left_table, edge.right_table, tuple(sorted(edge.key_pairs)))
    backward = (
        edge.right_table,
        edge.left_table,
        tuple(sorted((b, a) for a, b in edge.key_pairs)),
    )
    return min(forward, backward)


def _token(value: str) -> str:
    text = unicodedata.normalize("NFD", value.lower().replace("đ", "d"))
    return re.sub(
        r"[^a-z0-9]", "", "".join(c for c in text if not unicodedata.combining(c))
    )


def _column_tokens(column: Any) -> set[str]:
    return {_token(value) for value in (column.name, column.provenance) if value}


def _identifier(value: str) -> bool:
    token = _token(value)
    return (
        value.lower().startswith(("ma_", "mã ", "ma "))
        or (value.startswith("Ma") and len(value) > 2 and value[2].isupper())
        or value.lower().endswith("_id")
        or value.endswith(("Id", "ID"))
        or token in {"id", "sku", "code"}
    )


def _compatible_types(left: str, right: str) -> bool:
    def family(kind: str) -> str:
        upper = kind.upper()
        if any(t in upper for t in ("INT", "DECIMAL", "NUMERIC", "FLOAT", "DOUBLE")):
            return "number"
        if upper in {"VARCHAR", "TEXT", "STRING", "UNKNOWN"}:
            return "text"
        return upper

    return family(left) == family(right)


def _values(rows: tuple[dict[str, Any], ...], column: str) -> set[Any]:
    return {_hashable(row[column]) for row in rows if row.get(column) is not None}


def _values_list(rows: tuple[dict[str, Any], ...], column: str) -> list[Any]:
    return [row[column] for row in rows if row.get(column) is not None]


def _cardinality(left_unique: bool, right_unique: bool) -> str:
    if left_unique and right_unique:
        return "one_to_one"
    if left_unique:
        return "one_to_many"
    if right_unique:
        return "many_to_one"
    return "many_to_many"


def _infer_keys(table: TableMetadata, warnings: list[str]) -> list[KeyCandidate]:
    """Check declared keys and bounded minimal pairs without dropping null rows."""
    names = tuple(column.name for column in table.columns)
    declared = {(name,) for name in table.primary_key_candidates}
    declared.update(table.composite_key_candidates)
    valid_declared: set[tuple[str, ...]] = set()
    for key in sorted(declared):
        if not key or len(set(key)) != len(key) or not set(key).issubset(names):
            warnings.append(f"{table.name}: invalid declared key candidate {key!r}")
        else:
            valid_declared.add(key)
    keys = [(name,) for name in names]
    # Limit automatic pair exploration; wider keys can be declared by upstream.
    pairs = list(islice(combinations(names, 2), 256))
    if len(names) * (len(names) - 1) // 2 > 256:
        warnings.append(
            f"{table.name}: automatic composite key search limited to 256 pairs"
        )
    keys.extend(pairs)
    keys.extend(sorted(valid_declared - set(keys)))
    found: list[KeyCandidate] = []
    minimal_unique: list[set[str]] = []
    for key in keys:
        if key not in valid_declared and any(
            item.issubset(key) for item in minimal_unique
        ):
            continue
        rows = table.profile_rows
        values = [tuple(_hashable(row.get(column)) for column in key) for row in rows]
        has_null = any(any(value is None for value in row) for row in values)
        unique = bool(values) and not has_null and len(set(values)) == len(values)
        complete_rows = (
            table.profile_is_complete
            and bool(rows)
            and (table.row_count is None or table.row_count == len(rows))
        )
        # Aggregate statistics can verify a single column if no row sample is supplied.
        stats_unique = False
        if (
            len(key) == 1
            and not rows
            and table.profile_is_complete
            and (table.row_count or 0) > 0
        ):
            column = next(column for column in table.columns if column.name == key[0])
            stats_unique = (
                column.null_ratio == 0 and column.cardinality == table.row_count
            )
        proven = (unique and complete_rows) or stats_unique
        if not unique and not stats_unique and key not in valid_declared:
            continue
        if unique or stats_unique:
            minimal_unique.append(set(key))
        if proven:
            evidence = (f"complete profile verifies non-null uniqueness of {key!r}",)
        elif unique:
            evidence = (
                f"sample-only uniqueness of {key!r}; full-table uniqueness is unproven",
            )
        else:
            evidence = (
                f"{key!r} fails uniqueness/null checks or has no profile evidence",
            )
        found.append(
            KeyCandidate(
                table=table.name,
                columns=key,
                key_type="primary",
                status="candidate" if proven else "uncertain",
                confidence=1.0 if proven else (0.55 if unique else 0.2),
                evidence=evidence,
            )
        )
    return found


def _has_complete_rows(table: TableMetadata) -> bool:
    return (
        table.profile_is_complete
        and bool(table.profile_rows)
        and (table.row_count is None or table.row_count == len(table.profile_rows))
    )


def _check_declared_edge(
    edge: JoinEdge,
    left: TableMetadata,
    right: TableMetadata,
    business_id: str | None = None,
) -> tuple[str, float, str, tuple[str, ...]]:
    """Check referential coverage only for declared, documented relationships."""
    if (
        not trusted_relationship(edge, business_id)
        or not _has_complete_rows(left)
        or not _has_complete_rows(right)
    ):
        return (
            "candidate",
            min(edge.confidence, 0.85),
            edge.cardinality,
            (
                "declaration requires trusted attestation and complete profiles at both ends for validation",
            ),
        )
    left_rows = _join_values(
        left.profile_rows, tuple(pair[0] for pair in edge.key_pairs)
    )
    right_rows = _join_values(
        right.profile_rows, tuple(pair[1] for pair in edge.key_pairs)
    )
    left_values, right_values = set(left_rows), set(right_rows)
    if not left_values or not right_values:
        return (
            "uncertain",
            0.2,
            "unknown",
            ("no non-null join values; relation cannot be verified",),
        )
    overlap = left_values & right_values
    left_coverage = len(overlap) / len(left_values)
    right_coverage = len(overlap) / len(right_values)
    observed = _cardinality(
        len(left_values) == len(left_rows),
        len(right_values) == len(right_rows),
    )
    evidence = (
        f"full-profile directional referential coverage={left_coverage:.6f}/{right_coverage:.6f}",
        f"observed cardinality={observed}; declared cardinality={edge.cardinality}",
    )
    coverage_ok = {
        "many_to_one": left_coverage == 1,
        "one_to_many": right_coverage == 1,
        "one_to_one": left_coverage == 1 and right_coverage == 1,
    }.get(edge.cardinality)
    if coverage_ok is None:
        return (
            "candidate",
            min(edge.confidence, 0.85),
            observed,
            evidence
            + (
                "unknown or many-to-many declaration requires explicit semantic review",
            ),
        )
    compatible = {
        "many_to_one": {"many_to_one", "one_to_one"},
        "one_to_many": {"one_to_many", "one_to_one"},
        "one_to_one": {"one_to_one"},
    }[edge.cardinality]
    if (
        edge.cardinality == "one_to_one"
        and observed == "one_to_one"
        and not coverage_ok
    ):
        return (
            "uncertain",
            0.5,
            observed,
            evidence
            + (
                "partial one-to-one mapping; mandatory/optional direction is not specified",
            ),
        )
    if observed not in compatible or not coverage_ok:
        return (
            "invalid",
            0.0,
            observed,
            evidence
            + ("declared relation fails cardinality or referential coverage checks",),
        )
    return (
        "validated",
        0.95,
        edge.cardinality,
        evidence
        + (
            "declared relationship passes structural checks; aggregate grain must still be respected",
        ),
    )


def _join_values(
    rows: tuple[dict[str, Any], ...], keys: tuple[str, ...]
) -> list[tuple[Any, ...]]:
    """Compare complete key tuples; partial NULL keys never match in an equijoin."""
    return [
        tuple(_hashable(row[key]) for key in keys)
        for row in rows
        if all(row.get(key) is not None for key in keys)
    ]


def _infer_composite_edge(
    left: TableMetadata, right: TableMetadata, keys: tuple[str, ...]
) -> JoinEdge | None:
    left_rows = _join_values(left.profile_rows, keys)
    right_rows = _join_values(right.profile_rows, keys)
    left_values, right_values = set(left_rows), set(right_rows)
    if not left_values or not right_values:
        return None
    shared = left_values & right_values
    coverage = max(len(shared) / len(left_values), len(shared) / len(right_values))
    if coverage < 0.8:
        return None
    cardinality = _cardinality(
        len(left_values) == len(left_rows), len(right_values) == len(right_rows)
    )
    return JoinEdge(
        left.name,
        keys[0],
        right.name,
        keys[0],
        cardinality,
        "uncertain",
        0.75,
        (
            f"tuple overlap on {keys!r}: {len(shared)} shared keys; coverage={coverage:.6f}",
            "matching names and tuples are candidates only; validate documentation before use",
        ),
        fanout_warning=cardinality != "one_to_one",
        additional_key_pairs=tuple((key, key) for key in keys[1:]),
    )
