#!/usr/bin/env python3
"""Replay B0.5 policies from local artifacts; never calls a model or Modal."""

from __future__ import annotations

import argparse
import json
import unicodedata
from pathlib import Path
from typing import Any, Iterable


def load_jsonl(path: Path) -> list[dict[str, Any]]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def _norm_string(value: str) -> str:
    cleaned = "".join(
        character if unicodedata.category(character)[0] in {"L", "M", "N"} else " "
        for character in value.lower()
    )
    return " ".join(cleaned.split())


def _scalar_equal(predicted: Any, expected: Any, aliases: Iterable[Any] = ()) -> bool:
    for candidate in [expected, *aliases]:
        if predicted == candidate:
            return True
        if (
            isinstance(predicted, (int, float))
            and not isinstance(predicted, bool)
            and isinstance(candidate, (int, float))
            and not isinstance(candidate, bool)
            and abs(float(predicted) - float(candidate)) <= 1e-6
        ):
            return True
        if isinstance(predicted, str) and isinstance(candidate, str):
            if _norm_string(predicted) == _norm_string(candidate):
                return True
    return False


def answers_match(prediction: dict[str, Any], gold: dict[str, Any]) -> bool:
    answer_type = gold.get("type")
    if prediction.get("type") != answer_type:
        return False
    if answer_type in {"unanswerable", "abstain"}:
        return True
    predicted = prediction.get("answer")
    expected = gold.get("answer")
    aliases = list(gold.get("alias") or [])
    if answer_type in {"number", "percent", "string", "date", "boolean"}:
        return _scalar_equal(predicted, expected, aliases)
    if answer_type == "list":
        if not isinstance(predicted, list) or not isinstance(expected, list) or len(predicted) != len(expected):
            return False
        return all(
            _scalar_equal(
                predicted[index],
                expected[index],
                aliases[index] if index < len(aliases) and isinstance(aliases[index], list) else (),
            )
            for index in range(len(expected))
        )
    if answer_type == "table":
        if not isinstance(predicted, dict) or not isinstance(expected, dict):
            return False
        predicted_columns = list(predicted.get("columns") or [])
        expected_columns = list(expected.get("columns") or [])
        predicted_rows = list(predicted.get("rows") or [])
        expected_rows = list(expected.get("rows") or [])
        if len(predicted_columns) != len(expected_columns) or len(predicted_rows) != len(expected_rows):
            return False
        predicted_names = [str(column).strip().lower() for column in predicted_columns]
        expected_names = [str(column).strip().lower() for column in expected_columns]
        mapping = (
            [predicted_names.index(column) for column in expected_names]
            if set(predicted_names) == set(expected_names) and len(set(predicted_names)) == len(expected_names)
            else list(range(len(expected_columns)))
        )
        reordered = []
        for row in predicted_rows:
            if not isinstance(row, list) or len(row) != len(predicted_columns):
                return False
            reordered.append([row[index] for index in mapping])
        used: set[int] = set()
        for expected_index, expected_row in enumerate(expected_rows):
            row_aliases = aliases[expected_index] if expected_index < len(aliases) and isinstance(aliases[expected_index], list) else []
            for predicted_index, predicted_row in enumerate(reordered):
                if predicted_index in used or len(predicted_row) != len(expected_row):
                    continue
                if _scalar_equal(predicted_row[0], expected_row[0], row_aliases) and all(
                    _scalar_equal(predicted_row[column], expected_row[column])
                    for column in range(1, len(expected_row))
                ):
                    used.add(predicted_index)
                    break
            else:
                return False
        return True
    return predicted == expected


def _classify(predictions: dict[str, dict], gold: dict[str, dict]) -> dict[str, set[str]]:
    groups = {"correct_ids": set(), "wrong_ids": set(), "abstain_ids": set()}
    for question_id, expected in gold.items():
        prediction = predictions.get(question_id, {"id": question_id, "type": "abstain"})
        if prediction.get("type") == "abstain":
            groups["abstain_ids"].add(question_id)
        elif answers_match(prediction, expected):
            groups["correct_ids"].add(question_id)
        else:
            groups["wrong_ids"].add(question_id)
    return groups


def evaluate_records(predictions: dict[str, dict], gold: dict[str, dict]) -> dict[str, int | float]:
    groups = _classify(predictions, gold)
    correct = len(groups["correct_ids"])
    wrong = len(groups["wrong_ids"])
    total = len(gold)
    return {
        "total": total,
        "correct": correct,
        "wrong": wrong,
        "abstain": len(groups["abstain_ids"]),
        "score": (correct - wrong) / total if total else 0.0,
    }


def policy_delta(baseline: dict[str, set[str]], candidate: dict[str, set[str]]) -> dict[str, int]:
    return {
        "correct_lost": len(baseline["correct_ids"] - candidate["correct_ids"]),
        "wrong_removed": len(baseline["wrong_ids"] - candidate["wrong_ids"]),
    }


def _index(records: Iterable[dict[str, Any]]) -> dict[str, dict[str, Any]]:
    return {str(record["id"]): record for record in records}


def build_replay_report(ground_truth: Path, submission: Path, detailed_logs: Path) -> dict[str, Any]:
    gold = _index(load_jsonl(ground_truth))
    submitted = _index(load_jsonl(submission))
    detailed = load_jsonl(detailed_logs)
    canonical = {
        str(record["id"]): record.get("final_answer") or {"id": record["id"], "type": "abstain"}
        for record in detailed
    }
    policies = {
        "submission": submitted,
        "canonical": canonical,
        "canonical_without_table": {
            question_id: ({"id": question_id, "type": "abstain"} if answer.get("type") == "table" else answer)
            for question_id, answer in canonical.items()
        },
        "canonical_without_table_or_retry_answer": {
            str(record["id"]): (
                {"id": record["id"], "type": "abstain"}
                if (record.get("final_answer") or {}).get("type") == "table"
                or (record.get("retry_count", 0) >= 1 and record.get("decision") == "answer")
                else (record.get("final_answer") or {"id": record["id"], "type": "abstain"})
            )
            for record in detailed
        },
        "proof_enforce_on_legacy_artifacts": {
            question_id: {"id": question_id, "type": "abstain"} for question_id in gold
        },
    }
    baseline_groups = _classify(submitted, gold)
    report: dict[str, Any] = {"policies": {}}
    baseline_score = evaluate_records(submitted, gold)["score"]
    for name, predictions in policies.items():
        metrics = evaluate_records(predictions, gold)
        metrics.update(policy_delta(baseline_groups, _classify(predictions, gold)))
        metrics["score_delta"] = metrics["score"] - baseline_score
        report["policies"][name] = metrics
    return report


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ground-truth", type=Path, required=True)
    parser.add_argument("--submission", type=Path, required=True)
    parser.add_argument("--detailed-logs", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    report = build_replay_report(args.ground_truth, args.submission, args.detailed_logs)
    rendered = json.dumps(report, ensure_ascii=False, indent=2)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)


if __name__ == "__main__":
    main()
