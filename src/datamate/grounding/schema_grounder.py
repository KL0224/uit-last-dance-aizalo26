"""C3: Schema Grounder — table/column ranking and safe join path discovery."""

from __future__ import annotations

import unicodedata
from collections import deque

from .contracts import (
    CandidateJoinPath,
    QuestionIntent,
    SchemaCandidate,
    SelectedSchema,
)
from .protocols import BusinessContextProtocol, JoinSpec, TableSpec


class SchemaGrounder:
    """Rank candidate tables, select relevant columns, and resolve join paths from JoinGraph."""

    def __init__(self, top_k_tables: int = 4) -> None:
        self._top_k_tables = top_k_tables

    def _find_shortest_join_path(
        self,
        start_table: str,
        target_table: str,
        edges: list[JoinSpec],
    ) -> list[JoinSpec]:
        """BFS over join graph to find shortest path between start_table and target_table."""
        if start_table == target_table:
            return []

        queue: deque[tuple[str, list[JoinSpec]]] = deque([(start_table, [])])
        visited = {start_table}

        while queue:
            curr, path = queue.popleft()
            for edge in edges:
                if edge.left_table == curr and edge.right_table not in visited:
                    new_path = path + [edge]
                    if edge.right_table == target_table:
                        return new_path
                    visited.add(edge.right_table)
                    queue.append((edge.right_table, new_path))
                elif edge.right_table == curr and edge.left_table not in visited:
                    rev_edge = JoinSpec(
                        left_table=edge.right_table,
                        left_column=edge.right_column,
                        right_table=edge.left_table,
                        right_column=edge.left_column,
                        cardinality=(
                            "one_to_many"
                            if edge.cardinality == "many_to_one"
                            else "many_to_one"
                        ),
                        fanout_warning=(edge.cardinality == "many_to_one"),
                        confidence=edge.confidence,
                    )
                    new_path = path + [rev_edge]
                    if rev_edge.right_table == target_table:
                        return new_path
                    visited.add(rev_edge.right_table)
                    queue.append((rev_edge.right_table, new_path))
        return []

    def _select_relevant_columns(
        self,
        table: TableSpec,
        q_norm: str,
        intent: QuestionIntent,
        required_metric_cols: set[str],
        join_cols: set[str],
    ) -> tuple[str, ...]:
        """Pick columns relevant to the question, metrics, filters, and joins."""
        selected: list[str] = []
        entity_lowers = [e.lower() for e in intent.entities]

        for col in table.columns:
            include = False
            if col.name in required_metric_cols or col.name in join_cols:
                include = True
            elif col.role in {"id", "date", "money", "quantity", "name", "category"}:
                include = True
            elif col.name.lower() in q_norm or any(a.lower() in q_norm for a in col.aliases):
                include = True
            elif any(
                any(ent in str(sv).lower() for ent in entity_lowers)
                for sv in col.sample_values
            ):
                include = True

            if include and col.name not in selected:
                selected.append(col.name)

        if not selected:
            selected = [c.name for c in table.columns]
        return tuple(selected)

    def ground(
        self,
        question: str,
        intent: QuestionIntent,
        context: BusinessContextProtocol,
    ) -> SelectedSchema:
        """Rank tables, resolve required join paths, and flag fanout risks."""
        q_norm = unicodedata.normalize("NFC", question).lower()
        tables = list(context.get_tables())
        if not tables:
            return SelectedSchema(primary_table=None)

        table_map = {t.name: t for t in tables}
        scores: dict[str, float] = {t.name: 0.05 for t in tables}
        rationales: dict[str, list[str]] = {t.name: [] for t in tables}
        required_metric_cols_by_table: dict[str, set[str]] = {t.name: set() for t in tables}

        # 1. Score by target metrics in MetricRegistry (Fact table takes precedence)
        metrics_map = {m.metric_id: m for m in context.get_metrics()}
        for m_id in intent.target_metrics:
            if m_id in metrics_map:
                m_spec = metrics_map[m_id]
                if m_spec.preferred_table in scores:
                    scores[m_spec.preferred_table] += 0.85
                    rationales[m_spec.preferred_table].append(
                        f"Bảng chuẩn của metric {m_id}"
                    )
                    required_metric_cols_by_table[m_spec.preferred_table].update(
                        m_spec.required_columns
                    )

        # 2. Score by value aliases matched in question/entities
        value_aliases = context.get_value_aliases()
        for ent in intent.entities:
            ent_l = ent.lower()
            if ent_l in value_aliases:
                tbl_name, col_name, _ = value_aliases[ent_l]
                if tbl_name in scores:
                    scores[tbl_name] += 0.30
                    rationales[tbl_name].append(f"Chứa điều kiện lọc {ent!r} ({col_name})")
                    required_metric_cols_by_table[tbl_name].add(col_name)

        # 3. Score by group_by dimensions and lexical matches
        for tbl in tables:
            if any(alias.lower() in q_norm for alias in tbl.aliases):
                scores[tbl.name] += 0.25
                rationales[tbl.name].append("Khớp tên/alias bảng trong câu hỏi")

            if "customer" in intent.group_by and (
                tbl.grain == "customer" or "customer" in tbl.name.lower()
            ):
                scores[tbl.name] += 0.45
                rationales[tbl.name].append("Cung cấp định danh/tên khách hàng cho group_by")

            if "product" in intent.group_by and any(
                c.role == "name" and "product" in c.name.lower() for c in tbl.columns
            ):
                scores[tbl.name] += 0.35
                rationales[tbl.name].append("Cung cấp tên sản phẩm cho group_by")

            for col in tbl.columns:
                if any(a.lower() in q_norm for a in col.aliases):
                    scores[tbl.name] += 0.15
                    required_metric_cols_by_table[tbl.name].add(col.name)

        ranked_names = sorted(scores.keys(), key=lambda k: scores[k], reverse=True)
        primary_table = ranked_names[0]

        # 4. Determine secondary tables that must be joined (e.g., group_by or filter tables)
        needed_tables = [primary_table]
        for t_name in ranked_names[1:]:
            if scores[t_name] >= 0.35 and len(needed_tables) < self._top_k_tables:
                needed_tables.append(t_name)

        # 5. Connect needed_tables via JoinGraph
        edges = list(context.get_join_edges())
        candidate_joins: list[CandidateJoinPath] = []
        join_cols_by_table: dict[str, set[str]] = {t.name: set() for t in tables}
        seen_edge_pairs: set[tuple[str, str, str, str]] = set()

        for target_tbl in list(needed_tables[1:]):
            path_edges = self._find_shortest_join_path(primary_table, target_tbl, edges)
            for pe in path_edges:
                if pe.left_table not in needed_tables:
                    needed_tables.append(pe.left_table)
                if pe.right_table not in needed_tables:
                    needed_tables.append(pe.right_table)
                join_cols_by_table[pe.left_table].add(pe.left_column)
                join_cols_by_table[pe.right_table].add(pe.right_column)
                edge_key = (pe.left_table, pe.left_column, pe.right_table, pe.right_column)
                if edge_key not in seen_edge_pairs:
                    seen_edge_pairs.add(edge_key)
                    candidate_joins.append(
                        CandidateJoinPath(
                            left_table=pe.left_table,
                            left_column=pe.left_column,
                            right_table=pe.right_table,
                            right_column=pe.right_column,
                            cardinality=pe.cardinality,
                            fanout_warning=pe.fanout_warning,
                            confidence=pe.confidence,
                        )
                    )

        # 6. Build SchemaCandidate objects
        schema_candidates: list[SchemaCandidate] = []
        for t_name in needed_tables:
            t_spec = table_map[t_name]
            rel_cols = self._select_relevant_columns(
                table=t_spec,
                q_norm=q_norm,
                intent=intent,
                required_metric_cols=required_metric_cols_by_table[t_name],
                join_cols=join_cols_by_table[t_name],
            )
            reason_str = "; ".join(rationales[t_name]) or "Bảng liên quan qua join path"
            schema_candidates.append(
                SchemaCandidate(
                    table_name=t_name,
                    relevant_columns=rel_cols,
                    grain=t_spec.grain,
                    score=round(min(1.0, scores[t_name]), 2),
                    rationale=reason_str,
                )
            )

        has_fanout = any(j.fanout_warning for j in candidate_joins)
        warnings: list[str] = []
        if has_fanout:
            warnings.append(
                "Cảnh báo nhân dòng (fanout_warning): Đang nối cạnh one-to-many, cần aggregate trước khi join."
            )

        return SelectedSchema(
            primary_table=primary_table,
            tables=tuple(schema_candidates),
            join_paths=tuple(candidate_joins),
            fanout_warning=has_fanout,
            warnings=tuple(warnings),
        )


__all__ = ["SchemaGrounder"]
