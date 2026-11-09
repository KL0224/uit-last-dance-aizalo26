"""Decision tests for strict, proof-driven B0.5 v2 behavior."""

import copy
import json
from pathlib import Path

from datamate.b0.b05.adapters import adapt_gate_request
from datamate.b0.b05.contracts import Decision, GateAction, ReleaseStatus
from datamate.b0.b05.errors import ErrorCode
from datamate.b0.b05.gate import evaluate_gate
from datamate.b0.b05.writer import SubmissionWriter


def _raw_v2(*, mode: str = "enforce", attempt: int = 0) -> dict:
    raw = {
        "contract_version": "b05.v2",
        "policy_mode": mode,
        "question": {
            "id": "q_v2_gate",
            "business_id": "biz",
            "question": "Có bao nhiêu đơn?",
            "as_of_date": "2026-03-04",
        },
        "generation": {
            "answer_type": "number",
            "expected_answer_type": "number",
            "plan_id": "plan-count",
            "metric_id": "orders.count",
            "sql": "SELECT COUNT(*) FROM orders",
            "answer_semantics": {"numeric_kind": "count"},
        },
        "capability_proof": {
            "status": "supported",
            "capability_ids": ["orders.count"],
            "checked_source_ids": ["orders"],
            "catalog_version": "catalog-1",
            "proof_hash": "sha256:supported",
        },
        "semantic_proof": {
            "status": "pass",
            "plan_id": "plan-count",
            "checks": [
                {
                    "check_id": "metric_projection",
                    "status": "pass",
                    "source_id": "b04",
                }
            ],
            "schema_version": "schema-1",
            "rule_version": "rules-1",
        },
        "execution": {
            "status": "success",
            "columns": ["count"],
            "rows": [[10]],
            "row_count": 1,
        },
        "attempt": attempt,
    }
    if attempt == 1:
        raw["repair_origin"] = {
            "plan_id": "plan-count",
            "metric_id": "orders.count",
            "expected_answer_type": "number",
        }
    return raw


def test_enforce_answers_only_when_proofs_are_safe():
    outcome = evaluate_gate(adapt_gate_request(_raw_v2()))

    assert outcome.decision == Decision.ANSWER
    assert outcome.final_answer.answer == 10
    assert outcome.risk_assessment.release_status == ReleaseStatus.SAFE
    assert outcome.risk_assessment.policy_version == "b05-risk.v1"


def test_shadow_preserves_legacy_output_and_records_counterfactual_abstain():
    raw = _raw_v2(mode="shadow")
    raw.pop("semantic_proof")

    outcome = evaluate_gate(adapt_gate_request(raw))

    assert outcome.decision == Decision.ANSWER
    assert outcome.legacy_decision == Decision.ANSWER
    assert outcome.shadow_decision == Decision.ABSTAIN
    assert outcome.risk_assessment.release_status == ReleaseStatus.UNKNOWN


def test_enforce_abstains_when_semantic_proof_is_missing():
    raw = _raw_v2()
    raw.pop("semantic_proof")

    outcome = evaluate_gate(adapt_gate_request(raw))

    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.SEMANTIC_PROOF_MISSING


def test_answer_type_mismatch_retries_without_mutating_request():
    raw = _raw_v2()
    raw["generation"]["answer_type"] = "string"
    raw["execution"]["rows"] = [["ten"]]
    request = adapt_gate_request(raw)
    before = copy.deepcopy(request)

    first = evaluate_gate(request)
    second = evaluate_gate(request)

    assert first.action == GateAction.RETRY
    assert first.reason_code == ErrorCode.ANSWER_TYPE_MISMATCH
    assert second == first
    assert request == before


def test_scalar_multiple_rows_never_changes_type_to_list():
    raw = _raw_v2()
    raw["generation"]["sql"] = "SELECT total FROM orders LIMIT 5"
    raw["execution"]["rows"] = [[1], [2]]
    raw["execution"]["row_count"] = 2
    request = adapt_gate_request(raw)

    outcome = evaluate_gate(request)

    assert outcome.action == GateAction.RETRY
    assert outcome.reason_code == ErrorCode.SCALAR_SHAPE_MISMATCH
    assert request.generation.answer_type == "number"


def test_formatting_failure_does_not_rescue_number_as_string_in_v2():
    raw = _raw_v2()
    raw["execution"]["rows"] = [["not a number"]]

    outcome = evaluate_gate(adapt_gate_request(raw))

    assert outcome.action == GateAction.RETRY
    assert outcome.reason_code == ErrorCode.OUTPUT_TYPE_ERROR


def test_valid_unsupported_capability_emits_unanswerable():
    raw = _raw_v2()
    raw["generation"]["answer_type"] = "unanswerable"
    raw["generation"]["expected_answer_type"] = "unanswerable"
    raw["capability_proof"] = {
        "status": "unsupported",
        "capability_ids": ["profit.gross"],
        "missing_requirement_ids": ["cost_at_sale"],
        "checked_source_ids": ["orders", "products"],
        "catalog_version": "catalog-1",
        "proof_hash": "sha256:unsupported",
    }
    raw.pop("semantic_proof")
    raw["execution"] = {"status": "not_executed", "rows": [], "columns": []}

    outcome = evaluate_gate(adapt_gate_request(raw))

    assert outcome.decision == Decision.UNANSWERABLE
    assert outcome.reason_code == ErrorCode.CONFIRMED_MISSING_EVIDENCE
    assert "cost_at_sale" in outcome.final_answer.reason


def test_freeform_legacy_evidence_cannot_prove_v2_unanswerable():
    raw = _raw_v2()
    raw["generation"]["answer_type"] = "unanswerable"
    raw["generation"]["expected_answer_type"] = "unanswerable"
    raw["capability_proof"] = {"status": "unknown"}
    raw["evidence"] = {
        "source_kind": "catalog_verified",
        "capability_status": "unsupported",
        "checked_all_sources": True,
        "missing_fields": ["cost_at_sale"],
    }

    outcome = evaluate_gate(adapt_gate_request(raw))

    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.CAPABILITY_PROOF_MISSING


def test_attempt_one_rejects_changed_metric_even_if_execution_succeeds():
    raw = _raw_v2(attempt=1)
    raw["generation"]["metric_id"] = "orders.revenue"

    outcome = evaluate_gate(adapt_gate_request(raw))

    assert outcome.decision == Decision.ABSTAIN
    assert outcome.reason_code == ErrorCode.REPAIR_SEMANTICS_CHANGED


def test_attempt_one_with_preserved_origin_and_passed_proof_answers():
    outcome = evaluate_gate(adapt_gate_request(_raw_v2(attempt=1)))

    assert outcome.decision == Decision.ANSWER
    assert outcome.reason_code == ErrorCode.VALID_RESULT_AFTER_RETRY


def test_shadow_audit_records_legacy_counterfactual_and_risk(tmp_path: Path):
    raw = _raw_v2(mode="shadow")
    raw.pop("semantic_proof")
    outcome = evaluate_gate(adapt_gate_request(raw))

    SubmissionWriter(tmp_path).write_final(
        outcome,
        trace_meta={"contract_version": "b05.v2"},
    )
    audit_path = next((tmp_path / "logs").glob("*.json"))
    audit = json.loads(audit_path.read_text(encoding="utf-8"))

    assert audit["legacy_decision"] == "answer"
    assert audit["shadow_decision"] == "abstain"
    assert audit["risk_assessment"]["policy_version"] == "b05-risk.v1"
    assert audit["risk_assessment"]["release_status"] == "unknown"
