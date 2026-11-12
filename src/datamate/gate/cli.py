"""CLI Runner for B0.5 Basic Output Gate (DataMate 2026)."""

import argparse
import copy
import json
from pathlib import Path
import sys
import time
from typing import Any, Dict

from .adapters import adapt_gate_request
from .contracts import AnswerType, Decision, FinalAnswer, GateAction, GateOutcome
from .gate import evaluate_gate
from .writer import SubmissionWriter


def run_pipeline(fixtures_path: Path, result_dir: Path) -> Dict[str, Any]:
    """Run standalone B0.5 gate evaluation over JSONL fixtures."""
    writer = SubmissionWriter(result_dir=result_dir)

    start_time = time.monotonic()
    counts = {
        "total": 0,
        "answer": 0,
        "unanswerable": 0,
        "abstain": 0,
        "retry_attempts": 0,
    }
    final_outcomes: list[GateOutcome] = []
    expected_ids: list[str] = []

    if not fixtures_path.exists():
        print(f"Error: Fixtures file not found at {fixtures_path}", file=sys.stderr)
        sys.exit(1)

    with open(fixtures_path, "r", encoding="utf-8") as f:
        for line_num, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue

            counts["total"] += 1
            raw_record = json.loads(line)

            try:
                req = adapt_gate_request(raw_record)
            except Exception as c_err:
                # Contract error fallback to abstain
                q_id = str(raw_record.get("question", {}).get("id") or f"unknown_{line_num}")
                expected_ids.append(q_id)
                counts["abstain"] += 1
                outcome = GateOutcome(
                    action=GateAction.FINAL,
                    question_id=q_id,
                    decision=Decision.ABSTAIN,
                    final_answer=FinalAnswer(id=q_id, type=AnswerType.ABSTAIN),
                    reason_code="CONTRACT_ERROR",
                    validation={"passed": False, "errors": ["CONTRACT_ERROR"], "warnings": [str(c_err)]},
                    retry_count=0,
                )
                writer.write_final(outcome, trace_meta={"business_id": "", "contract_version": "b05.v1"})
                final_outcomes.append(outcome)
                continue

            # Record attempt 0 trace
            q_id = req.question.id
            expected_ids.append(q_id)
            sql_attempt0 = req.generation.sql if req.generation else ""
            status_attempt0 = req.execution.status
            err_code0 = req.execution.error.type if req.execution.error else None
            elapsed_ms0 = req.execution.elapsed_ms

            writer.record_attempt(
                question_id=q_id,
                attempt=req.attempt,
                sql=sql_attempt0,
                execution_status=status_attempt0,
                error_code=err_code0,
                execution_ms=elapsed_ms0,
                row_count=req.execution.row_count,
            )

            outcome = evaluate_gate(req)

            # If action is RETRY, simulate bounded repair attempt
            if outcome.action == GateAction.RETRY:
                counts["retry_attempts"] += 1

                # Check if simulated mock repair can succeed or if it's exhausted
                simulated_success = raw_record.get("_simulate_retry_success", False)
                corrected_rows = raw_record.get("_simulate_corrected_rows", [[125]])

                raw_attempt1 = copy.deepcopy(raw_record)
                raw_attempt1["attempt"] = 1
                if req.contract_version == "b05.v2" and outcome.repair_request:
                    raw_attempt1["repair_origin"] = {
                        "plan_id": outcome.repair_request.plan_id,
                        "metric_id": outcome.repair_request.metric_id,
                        "expected_answer_type": outcome.repair_request.expected_answer_type,
                    }

                if simulated_success:
                    raw_attempt1["execution"] = {
                        "status": "success",
                        "columns": ["result"],
                        "rows": corrected_rows,
                        "row_count": len(corrected_rows),
                        "truncated": False,
                        "elapsed_ms": 12.0,
                    }
                    if req.generation:
                        raw_attempt1["generation"] = copy.deepcopy(raw_record["generation"])
                        raw_attempt1["generation"]["sql"] = "SELECT ... -- repaired"
                else:
                    # Still failing
                    pass

                req1 = adapt_gate_request(raw_attempt1)
                writer.record_attempt(
                    question_id=q_id,
                    attempt=1,
                    sql=req1.generation.sql if req1.generation else "",
                    execution_status=req1.execution.status,
                    error_code=req1.execution.error.type if req1.execution.error else None,
                    execution_ms=req1.execution.elapsed_ms,
                    row_count=req1.execution.row_count,
                )
                outcome = evaluate_gate(req1)

            # Record decision count
            if outcome.decision == Decision.ANSWER:
                counts["answer"] += 1
            elif outcome.decision == Decision.UNANSWERABLE:
                counts["unanswerable"] += 1
            else:
                counts["abstain"] += 1

            meta = {
                "business_id": req.question.business_id,
                "contract_version": req.contract_version,
                "total_elapsed_ms": (time.monotonic() - start_time) * 1000.0,
            }
            writer.write_final(outcome, trace_meta=meta)
            final_outcomes.append(outcome)

    total_time_s = time.monotonic() - start_time
    counts["total_time_seconds"] = round(total_time_s, 3)
    counts["submission_manifest"] = writer.finalize(
        final_outcomes,
        expected_ids=expected_ids,
    )

    return counts


def main():
    parser = argparse.ArgumentParser(description="DataMate B0.5 Basic Output Gate Standalone Runner")
    parser.add_argument("--fixtures", type=str, required=True, help="Path to JSONL fixtures file")
    parser.add_argument("--result-dir", type=str, default="/result", help="Output directory for submission.jsonl and logs")

    args = parser.parse_args()
    fixtures_path = Path(args.fixtures)
    result_dir = Path(args.result_dir)

    print(f"[B0.5 Gate CLI] Reading fixtures from: {fixtures_path}")
    print(f"[B0.5 Gate CLI] Result output dir:    {result_dir}")

    summary = run_pipeline(fixtures_path, result_dir)

    print("\n--- Execution Summary ---")
    print(f"Total Questions Evaluated: {summary['total']}")
    print(f"Answers Emitted:           {summary['answer']}")
    print(f"Unanswerable Emitted:      {summary['unanswerable']}")
    print(f"Abstain Emitted:           {summary['abstain']}")
    print(f"Bounded Retries Run:       {summary['retry_attempts']}")
    print(f"Elapsed Time:              {summary['total_time_seconds']}s")
    print(f"Submission saved to:       {result_dir / 'submission.jsonl'}")


if __name__ == "__main__":
    main()
