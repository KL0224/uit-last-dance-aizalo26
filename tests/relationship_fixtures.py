"""Explicit reviewed producer attestations for synthetic legacy fixtures."""

from dataclasses import replace
from hashlib import sha256

from datamate.b0.b01.contracts import JoinEdge, RelationshipEvidence
from datamate.b0.b01.relationship_evidence import relationship_fingerprint


def reviewed_edge(edge: JoinEdge, business_id: str = "fixture") -> JoinEdge:
    """Synthetic producer proof, not a claim that a physical README was checked."""
    statement = "Synthetic fixture review: " + repr(edge.key_pairs)
    proof = RelationshipEvidence(
        "reviewed_relationship",
        business_id,
        "synthetic fixture specification",
        sha256(statement.encode()).hexdigest(),
        statement,
        "approved",
        "unit test fixture author",
        relationship_fingerprint(edge, business_id),
    )
    return replace(edge, relationship_evidence=proof)
