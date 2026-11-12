"""Trust policy for relationship attestations, separate from SQL statistics.

Preparation verifies source files before issuing attestations. Metadata/API callers
are trusted producers of these records, not cryptographically authenticated users.
"""

from __future__ import annotations

import hashlib
import json
import re

from datamate.ingestion.contracts import JoinEdge, RelationshipEvidence


def relationship_fingerprint(edge: JoinEdge, business_id: str) -> str:
    """Bind an attestation to scope, ordered mapping and declared cardinality."""
    payload = [
        business_id,
        edge.left_table,
        edge.right_table,
        edge.key_pairs,
        edge.cardinality,
    ]
    return hashlib.sha256(json.dumps(payload, ensure_ascii=False).encode()).hexdigest()


def trusted_relationship(edge: JoinEdge, business_id: str | None = None) -> bool:
    """Require structured provenance; a free-form evidence string is insufficient."""
    proof = edge.relationship_evidence
    if not isinstance(proof, RelationshipEvidence) or not all(
        isinstance(getattr(proof, name), str) and getattr(proof, name).strip()
        for name in RelationshipEvidence.__dataclass_fields__
    ):
        return False
    if business_id is not None and proof.business_id != business_id:
        return False
    if not re.fullmatch(r"[0-9a-f]{64}", proof.source_sha256):
        return False
    if (proof.origin, proof.review_status) not in {
        ("sqlite_foreign_key", "source_declared"),
        ("reviewed_relationship", "approved"),
    }:
        return False
    return proof.relationship_sha256 == relationship_fingerprint(
        edge, proof.business_id
    )
