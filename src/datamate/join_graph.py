"""Validated join paths and composite equijoin predicate compilation."""

from __future__ import annotations

from collections import deque

from datamate.contracts import JoinEdge, SchemaCatalog


class JoinGraphNavigator:
    """Expose only structurally validated edges to downstream SQL planning."""

    def find_path(
        self, catalog: SchemaCatalog, source: str, target: str
    ) -> tuple[JoinEdge, ...] | None:
        """Find a deterministic shortest path; None means no validated path yet."""
        names = {table.name for table in catalog.tables}
        if source not in names or target not in names:
            raise ValueError("join path endpoint is absent from the schema catalog")
        queue: deque[tuple[str, tuple[JoinEdge, ...]]] = deque([(source, ())])
        visited = {source}
        edges = sorted(
            (edge for edge in catalog.join_graph if edge.status == "validated"),
            key=lambda edge: (edge.left_table, edge.right_table, edge.key_pairs),
        )
        while queue:
            current, path = queue.popleft()
            if current == target:
                return path
            for edge in edges:
                neighbor = (
                    edge.right_table
                    if edge.left_table == current
                    else (edge.left_table if edge.right_table == current else None)
                )
                if neighbor is not None and neighbor not in visited:
                    visited.add(neighbor)
                    queue.append((neighbor, path + (edge,)))
        return None


class JoinPredicateCompiler:
    """Compile known validated edges, retaining all key pairs."""

    def compile(self, edge: JoinEdge, catalog: SchemaCatalog) -> str:
        """Return an equijoin predicate; aliases and full queries belong to the planner."""
        if edge not in catalog.join_graph or edge.status != "validated":
            raise ValueError("only catalog-owned validated edges can be compiled")
        columns = {
            table.name: {column.name for column in table.columns}
            for table in catalog.tables
        }
        for left, right in edge.key_pairs:
            if left not in columns.get(
                edge.left_table, set()
            ) or right not in columns.get(edge.right_table, set()):
                raise ValueError("join references an unknown table or column")
        return " AND ".join(
            f"{_quote(edge.left_table)}.{_quote(left)} = {_quote(edge.right_table)}.{_quote(right)}"
            for left, right in edge.key_pairs
        )


def _quote(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'
