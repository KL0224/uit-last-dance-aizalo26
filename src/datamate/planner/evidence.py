"""Catalog-backed evidence verification for B0.3 -> B0.5 unanswerable claims."""

from __future__ import annotations

import re
import unicodedata
from typing import Any, Mapping, Sequence

from datamate.gate.contracts import EvidenceProof


def _fold_token(value: str) -> str:
    value = (
        re.sub(r"([a-z])([A-Z])", r"\1 \2", str(value))
        .replace("Đ", "D")
        .replace("đ", "d")
    )
    folded = (
        unicodedata.normalize("NFKD", value)
        .encode("ascii", "ignore")
        .decode("ascii")
        .lower()
    )
    return re.sub(r"[^a-z0-9]+", "_", folded).strip("_")


def _extract_tables(context: Any) -> list[dict[str, Any]]:
    if context is None:
        return []
    if isinstance(context, Mapping):
        catalog = context.get("schema_catalog") or {}
        if isinstance(catalog, Mapping):
            tables = catalog.get("tables") or []
        else:
            tables = getattr(catalog, "tables", ()) or ()
    else:
        catalog = getattr(context, "schema_catalog", None)
        tables = getattr(catalog, "tables", ()) if catalog is not None else ()

    normalized: list[dict[str, Any]] = []
    for table in tables:
        if isinstance(table, Mapping):
            t_name = str(table.get("name", ""))
            cols = table.get("columns") or []
        else:
            t_name = str(getattr(table, "name", ""))
            cols = getattr(table, "columns", ()) or ()
        col_entries: list[dict[str, Any]] = []
        for col in cols:
            if isinstance(col, Mapping):
                c_name = str(col.get("name", ""))
                prov = col.get("provenance") or []
            else:
                c_name = str(getattr(col, "name", ""))
                prov = getattr(col, "provenance", ()) or ()
            col_entries.append({"name": c_name, "provenance": list(prov)})
        if t_name:
            normalized.append({"name": t_name, "columns": col_entries})
    return normalized


def build_evidence_proof(
    context: Any,
    reason: str | None,
    missing_fields: Sequence[str] = (),
) -> EvidenceProof:
    """Verify an unanswerable claim against the supplied schema catalog.

    Returns a catalog_verified EvidenceProof only when:
    1. A non-empty schema_catalog is present in `context`, AND
    2. Either `missing_fields` are specified and NONE of them exist in any table
       of the schema catalog, OR `reason` is non-empty and no claimed missing
       field contradicts the schema catalog.
    """
    tables = _extract_tables(context)
    if not tables:
        return EvidenceProof()

    available_fields: list[str] = []
    known_tokens: set[str] = set()
    table_names: list[str] = []

    for table in tables:
        t_name = table["name"]
        t_token = _fold_token(t_name)
        table_names.append(t_name)
        for col in table["columns"]:
            c_name = col["name"]
            if not c_name:
                continue
            qualified = f"{t_name}.{c_name}"
            available_fields.append(qualified)
            c_token = _fold_token(c_name)
            if c_token:
                known_tokens.add(c_token)
                if t_token:
                    known_tokens.add(f"{t_token}.{c_token}")
                    known_tokens.add(f"{t_token}_{c_token}")
            for prov in col.get("provenance", []):
                raw = str(prov).split(":")[-1].strip()
                raw_token = _fold_token(raw)
                if raw_token:
                    known_tokens.add(raw_token)
                    if t_token:
                        known_tokens.add(f"{t_token}.{raw_token}")

    cleaned_missing = [str(f).strip() for f in missing_fields if str(f).strip()]
    for field_name in cleaned_missing:
        candidate = field_name.strip()
        if "." in candidate:
            left, right = candidate.split(".", 1)
            folded_pair = f"{_fold_token(left)}.{_fold_token(right)}"
            folded_col = _fold_token(right)
            if folded_pair in known_tokens or folded_col in known_tokens:
                return EvidenceProof(
                    capability_status="supported",
                    coverage_status="complete",
                    checked_all_sources=True,
                    required_fields=cleaned_missing,
                    available_fields=available_fields,
                    missing_fields=[],
                    alternative_sources_checked=table_names,
                    source_kind="unverified",
                )
        else:
            folded_col = _fold_token(candidate)
            if folded_col and folded_col in known_tokens:
                return EvidenceProof(
                    capability_status="supported",
                    coverage_status="complete",
                    checked_all_sources=True,
                    required_fields=cleaned_missing,
                    available_fields=available_fields,
                    missing_fields=[],
                    alternative_sources_checked=table_names,
                    source_kind="unverified",
                )

    clean_reason = (reason or "").strip()
    if not cleaned_missing and not clean_reason:
        return EvidenceProof()

    proof_entry: dict[str, Any] = {"tables_checked": table_names}
    if clean_reason:
        proof_entry["reason"] = clean_reason

    return EvidenceProof(
        capability_status="unsupported",
        coverage_status="complete",
        checked_all_sources=True,
        required_fields=cleaned_missing,
        available_fields=available_fields,
        missing_fields=cleaned_missing,
        alternative_sources_checked=table_names,
        source_kind="catalog_verified",
        proof=[proof_entry],
    )

