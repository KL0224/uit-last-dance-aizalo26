"""Contract tests for the additive B0.5 v2 proof boundary."""

import pytest

from datamate.gate.adapters import adapt_gate_request
from datamate.gate.contracts import (
    CapabilityStatus,
    PolicyMode,
    ProofStatus,
)
from datamate.gate.errors import ContractError


def _request_v2() -> dict:
    return {
        "contract_version": "b05.v2",
        "policy_mode": "enforce",
        "question": {
            "id": "q_v2",
            "business_id": "biz",
            "question": "Có bao nhiêu đơn?",
            "as_of_date": "2026-03-04",
        },
        "generation": {
            "answer_type": "number",
            "expected_answer_type": "number",
            "plan_id": "plan-001",
            "metric_id": "orders.count",
            "sql": "SELECT COUNT(*) FROM orders",
            "answer_semantics": {"numeric_kind": "count"},
        },
        "capability_proof": {
            "status": "supported",
            "capability_ids": ["orders.count"],
            "checked_source_ids": ["orders"],
            "catalog_version": "catalog-7",
            "proof_hash": "sha256:abc",
        },
        "semantic_proof": {
            "status": "pass",
            "plan_id": "plan-001",
            "checks": [
                {
                    "check_id": "metric_projection",
                    "status": "pass",
                    "source_id": "b04",
                    "details": "COUNT(*) conforms",
                }
            ],
            "schema_version": "schema-3",
            "rule_version": "rules-2",
        },
        "execution": {
            "status": "success",
            "columns": ["count"],
            "rows": [[10]],
            "row_count": 1,
        },
        "attempt": 0,
    }


def test_v2_contract_preserves_plan_and_proof_provenance():
    request = adapt_gate_request(_request_v2())

    assert request.policy_mode == PolicyMode.ENFORCE
    assert request.generation.plan_id == "plan-001"
    assert request.generation.metric_id == "orders.count"
    assert request.generation.expected_answer_type == "number"
    assert request.capability_proof.status == CapabilityStatus.SUPPORTED
    assert request.capability_proof.checked_source_ids == ["orders"]
    assert request.semantic_proof.status == ProofStatus.PASS
    assert request.semantic_proof.checks[0].check_id == "metric_projection"


def test_v2_missing_proofs_are_unknown_and_default_to_shadow():
    raw = _request_v2()
    raw.pop("policy_mode")
    raw.pop("capability_proof")
    raw.pop("semantic_proof")

    request = adapt_gate_request(raw)

    assert request.policy_mode == PolicyMode.SHADOW
    assert request.capability_proof.status == CapabilityStatus.UNKNOWN
    assert request.semantic_proof.status == ProofStatus.UNKNOWN


@pytest.mark.parametrize(
    ("path", "value"),
    [
        (("policy_mode",), "sometimes"),
        (("capability_proof", "status"), "maybe"),
        (("semantic_proof", "status"), "successful"),
    ],
)
def test_v2_rejects_unknown_enums(path: tuple[str, ...], value: str):
    raw = _request_v2()
    target = raw
    for key in path[:-1]:
        target = target[key]
    target[path[-1]] = value

    with pytest.raises(ContractError):
        adapt_gate_request(raw)


def test_v2_rejects_generation_without_plan_identity():
    raw = _request_v2()
    raw["generation"].pop("plan_id")

    with pytest.raises(ContractError, match="plan_id"):
        adapt_gate_request(raw)


def test_v2_rejects_partial_supported_capability_proof():
    raw = _request_v2()
    raw["capability_proof"].pop("proof_hash")

    with pytest.raises(ContractError, match="proof_hash"):
        adapt_gate_request(raw)


def test_v2_rejects_partial_passed_semantic_proof():
    raw = _request_v2()
    raw["semantic_proof"].pop("rule_version")

    with pytest.raises(ContractError, match="rule_version"):
        adapt_gate_request(raw)


def test_v1_remains_legacy_without_v2_fields():
    raw = _request_v2()
    raw["contract_version"] = "b05.v1"
    raw.pop("policy_mode")
    raw["generation"].pop("plan_id")
    raw["generation"].pop("metric_id")
    raw["generation"].pop("expected_answer_type")
    raw.pop("capability_proof")
    raw.pop("semantic_proof")

    request = adapt_gate_request(raw)

    assert request.policy_mode == PolicyMode.LEGACY
    assert request.generation.plan_id is None
