"""Tests for the local-only B0.5 replay evaluator."""

from scripts.analyze_b05_replay import evaluate_records, policy_delta


def test_replay_scores_answers_and_abstentions():
    gold = {
        "q1": {"id": "q1", "type": "number", "answer": 10},
        "q2": {"id": "q2", "type": "string", "answer": "Cà phê"},
        "q3": {"id": "q3", "type": "boolean", "answer": True},
    }
    predictions = {
        "q1": {"id": "q1", "type": "number", "answer": 10},
        "q2": {"id": "q2", "type": "string", "answer": "Trà"},
        "q3": {"id": "q3", "type": "abstain"},
    }

    report = evaluate_records(predictions, gold)

    assert report == {"total": 3, "correct": 1, "wrong": 1, "abstain": 1, "score": 0.0}


def test_policy_delta_reports_correct_lost_and_wrong_removed():
    baseline = {"correct_ids": {"q1", "q2"}, "wrong_ids": {"q3", "q4"}}
    candidate = {"correct_ids": {"q1"}, "wrong_ids": {"q4"}}

    delta = policy_delta(baseline, candidate)

    assert delta == {"correct_lost": 1, "wrong_removed": 1}
