"""Reviewed relationship manifests mapped from physical sources to SQL names."""

from __future__ import annotations

import hashlib
import json
from dataclasses import replace
from pathlib import Path
from typing import Any

from datamate.ingestion.contracts import JoinEdge, RelationshipEvidence
from datamate.ingestion.ingestion.models import SourceTable
from datamate.ingestion.relationship_evidence import relationship_fingerprint


class ReviewedRelationships:
    """Validate review documents before they can participate in preparation/cache."""

    def __init__(self, path: str | Path, business_id: str) -> None:
        self.path = Path(path).resolve(strict=True)
        content = self.path.read_bytes()
        self.input_hashes = {str(self.path): hashlib.sha256(content).hexdigest()}
        payload = json.loads(content.decode("utf-8"))
        if not isinstance(payload, dict) or set(payload) != {
            "version",
            "business_id",
            "relationships",
        }:
            raise ValueError(
                "relationship manifest requires version, business_id and relationships"
            )
        if payload["version"] != "1.0" or payload["business_id"] != business_id:
            raise ValueError("relationship manifest version/business scope mismatch")
        self.business_id = business_id
        self.items = payload["relationships"]
        if not isinstance(self.items, list):
            raise TypeError("relationships must be a list")
        self.dependencies = [self.path]
        self.proofs: list[tuple[Path, str, str]] = []
        seen = set()
        for item in self.items:
            if not isinstance(item, dict) or set(item) != {
                "id",
                "left",
                "right",
                "cardinality",
                "review",
            }:
                raise ValueError("unsupported reviewed relationship fields")
            identity = self._text(item["id"])
            if identity in seen:
                raise ValueError("duplicate reviewed relationship id")
            seen.add(identity)
            if item["cardinality"] not in {"many_to_one", "one_to_many", "one_to_one"}:
                raise ValueError(
                    "reviewed relationships require explicit supported cardinality"
                )
            for side in (item["left"], item["right"]):
                if not isinstance(side, dict) or set(side) != {
                    "file",
                    "table",
                    "columns",
                }:
                    raise ValueError(
                        "relationship endpoint requires file/table/columns"
                    )
                self._text(side["file"])
                if side["table"] is not None:
                    self._text(side["table"])
                if not isinstance(side["columns"], list) or not side["columns"]:
                    raise ValueError("relationship columns must be a nonempty list")
                for column in side["columns"]:
                    self._text(column)
                if len(set(side["columns"])) != len(side["columns"]):
                    raise ValueError("repeated reviewed key columns")
            if len(item["left"]["columns"]) != len(item["right"]["columns"]):
                raise ValueError("relationship key widths must match")
            review = item["review"]
            if not isinstance(review, dict) or set(review) != {
                "status",
                "reviewed_by",
                "evidence",
            }:
                raise ValueError("review requires status/reviewed_by/evidence")
            if review["status"] not in {"approved", "pending", "rejected"}:
                raise ValueError("unsupported review status")
            self._text(review["reviewed_by"])
            evidence = review["evidence"]
            if not isinstance(evidence, dict) or set(evidence) != {
                "path",
                "sha256",
                "quote",
            }:
                raise ValueError("review evidence requires path/sha256/quote")
            resource = (self.path.parent / self._text(evidence["path"])).resolve(
                strict=True
            )
            content = resource.read_bytes()
            digest = hashlib.sha256(content).hexdigest()
            self.input_hashes[str(resource)] = digest
            quote = self._text(evidence["quote"])
            if digest != evidence["sha256"] or quote not in content.decode("utf-8"):
                raise ValueError("review evidence hash/quote does not match its source")
            self.dependencies.append(resource)
            self.proofs.append((resource, digest, quote))

    @staticmethod
    def _text(value: Any) -> str:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("review fields must contain nonempty text")
        return value

    def resolve(
        self, sources: list[SourceTable], mapping: dict[str, Any]
    ) -> tuple[JoinEdge, ...]:
        """Require each source reference to resolve uniquely; never guess a mapping."""
        result = []
        for item, (resource, digest, quote) in zip(
            self.items, self.proofs, strict=True
        ):
            endpoints = []
            for side in (item["left"], item["right"]):
                found = [
                    s
                    for s in sources
                    if s.relative_path == side["file"] and s.sheet == side["table"]
                ]
                if len(found) != 1:
                    raise ValueError(
                        f"review endpoint is missing or ambiguous: {side['file']}#{side['table']}"
                    )
                targets = [
                    (name, data)
                    for name, data in mapping.items()
                    if found[0].source_id in data["source_ids"]
                ]
                if len(targets) != 1:
                    raise ValueError("review endpoint has ambiguous normalized mapping")
                name, data = targets[0]
                columns = []
                for original in side["columns"]:
                    choices = [
                        col
                        for col, meta in data["columns"].items()
                        if meta["original_name"] == original
                    ]
                    if len(choices) != 1:
                        raise ValueError(
                            f"review column is missing or ambiguous: {original}"
                        )
                    columns.append(choices[0])
                endpoints.append((name, columns))
            (left, lcols), (right, rcols) = endpoints
            pairs = tuple(zip(lcols, rcols, strict=True))
            edge = JoinEdge(
                left,
                pairs[0][0],
                right,
                pairs[0][1],
                item["cardinality"],
                "candidate",
                0.0,
                (f"reviewed relationship: {self.path}#{item['id']}",),
                additional_key_pairs=pairs[1:],
            )
            proof = RelationshipEvidence(
                "reviewed_relationship",
                self.business_id,
                str(resource),
                digest,
                quote,
                item["review"]["status"],
                item["review"]["reviewed_by"],
                relationship_fingerprint(edge, self.business_id),
            )
            result.append(replace(edge, relationship_evidence=proof))
        return tuple(result)
