"""Tests for Evidence-Based Answerability Decision."""

import pytest
from datamate.b05.adapters import adapt_gate_request
from datamate.b05.answerability import evaluate_answerability


def test_confirmed_unanswerable_with_trusted_proof():
    raw = {
        "contract_version": "b05.v1",
        "question": {"id": "q_ua", "business_id": "biz", "question": "Lợi nhuận gộp?", "as_of_date": "2026-03-04"},
        "generation": {"answer_type": "unanswerable", "sql": "", "tables_used": []},
        "execution": {"status": "not_executed", "columns": [], "rows": []},
        "evidence": {
            "capability_status": "unsupported",
            "checked_all_sources": True,
            "required_fields": ["revenue", "cost_at_sale"],
            "available_fields": ["revenue"],
            "missing_fields": ["cost_at_sale"],
            "source_kind": "catalog_verified",
            "proof": [{"check": "missing_required_metric_source", "result": True}]
        },
        "attempt": 0
    }
    req = adapt_gate_request(raw)
    is_ua, reason = evaluate_answerability(req)
    assert is_ua is True
    assert reason is not None
    assert "cost_at_sale" in reason


def test_untrusted_unanswerable_claim_rejected():
    # LLM claims unanswerable but no independent catalog_verified proof
    raw = {
        "contract_version": "b05.v1",
        "question": {"id": "q_claim", "business_id": "biz", "question": "Lợi nhuận gộp?", "as_of_date": "2026-03-04"},
        "generation": {"answer_type": "unanswerable", "sql": "", "tables_used": []},
        "execution": {"status": "not_executed", "columns": [], "rows": []},
        "evidence": {
            "capability_status": "unsupported",
            "source_kind": "llm_self_claim"  # NOT trusted!
        },
        "attempt": 0
    }
    req = adapt_gate_request(raw)
    is_ua, reason = evaluate_answerability(req)
    assert is_ua is False

