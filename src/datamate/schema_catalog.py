"""Schema catalog and evidence-backed join candidate inference."""

from __future__ import annotations

from dataclasses import replace
from itertools import combinations, islice
from typing import Any

from datamate.contracts import JoinEdge, KeyCandidate, SchemaCatalog, TableMetadata


class SchemaCatalogBuilder:
    """Build candidate keys and joins from Data Foundation table metadata."""

    def build(
        self, tables: list[TableMetadata], declared_edges: list[JoinEdge] | None = None
    ) -> SchemaCatalog:
        """Analyze supplied tables; no source data is loaded or modified here."""
        names = [table.name for table in tables]
        if len(set(names)) != len(names):
            raise ValueError("table names must be unique")
        key_candidates: list[KeyCandidate] = []
        warnings: list[str] = []
        enriched_tables: list[TableMetadata] = []
        for table in tables:
            candidates = _infer_keys(table, warnings)
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
        for edge in declared_edges or []:
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
            left = table_by_name[edge.left_table]
            right = table_by_name[edge.right_table]
            status, confidence, observed_cardinality, checks = _check_declared_edge(
                edge, left, right
            )
            edges.append(
                JoinEdge(
                    left_table=edge.left_table,
                    left_column=edge.left_column,
                    right_table=edge.right_table,
                    right_column=edge.right_column,
                    cardinality=observed_cardinality,
                    status=status,
                    confidence=confidence,
                    evidence=edge.evidence + checks,
                    fanout_warning=edge.fanout_warning
                    or observed_cardinality != "one_to_one",
                    additional_key_pairs=edge.additional_key_pairs,
                )
            )
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


def _hashable(value: Any) -> Any:
    try:
        hash(value)
        return value
    except TypeError:
        return repr(value)


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
) -> tuple[str, float, str, tuple[str, ...]]:
    """Check referential coverage only for declared, documented relationships."""
    if (
        not edge.evidence
        or not _has_complete_rows(left)
        or not _has_complete_rows(right)
    ):
        return (
            "candidate",
            min(edge.confidence, 0.85),
            edge.cardinality,
            (
                "declaration requires source evidence and complete profiles at both ends for validation",
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
