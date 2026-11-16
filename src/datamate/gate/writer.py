"""Submission Writer for B0.5 Basic Output Gate."""

import json
from pathlib import Path
from typing import Any, Dict, Iterable, Mapping, Optional, Sequence, Set

from .audit import AuditLogger
from .contracts import GateAction, GateOutcome
from .errors import OutputWriteError
from .finalizer import SubmissionFinalizer


class SubmissionWriter:
    """Manages persistent, atomic writing to submission.jsonl and per-question audit logs."""

    def __init__(self, result_dir: Path | str = "/result"):
        self.result_dir = Path(result_dir)
        self.result_dir.mkdir(parents=True, exist_ok=True)

        self.submission_path = self.result_dir / "submission.jsonl"
        self.audit_logger = AuditLogger(logs_dir=self.result_dir / "logs")

        self.seen_ids: Set[str] = set()
        self._load_existing_ids()

    def _load_existing_ids(self) -> None:
        """Scan existing submission.jsonl to populate seen_ids for resume/de-dup."""
        if self.submission_path.exists():
            try:
                with open(self.submission_path, "r", encoding="utf-8") as f:
                    for line in f:
                        line = line.strip()
                        if line:
                            data = json.loads(line)
                            if "id" in data:
                                self.seen_ids.add(str(data["id"]))
            except Exception as exc:
                raise OutputWriteError(f"Failed to read existing submission.jsonl: {exc}")

    def record_attempt(
        self,
        question_id: str,
        attempt: int,
        sql: str,
        execution_status: str,
        error_code: Optional[str] = None,
        execution_ms: Optional[float] = None,
        row_count: Optional[int] = None,
        thinking: Optional[str] = None,
        assumptions: Optional[ Any] = None,
        error_message: Optional[str] = None,
        llm_generation_ms: Optional[float] = None,
        generation_diagnostics: Optional[Dict[str, Any]] = None,
        batch_fallback_error: Optional[Dict[str, Any]] = None,
        candidate_id: Optional[int] = None,
        round_id: Optional[int] = None,
    ) -> None:
        """Record an attempt trace into audit logger history."""
        self.audit_logger.record_attempt(
            question_id=question_id,
            attempt=attempt,
            sql=sql,
            execution_status=execution_status,
            error_code=error_code,
            execution_ms=execution_ms,
            row_count=row_count,
            thinking=thinking,
            assumptions=list(assumptions) if assumptions is not None else None,
            error_message=error_message,
            llm_generation_ms=llm_generation_ms,
            generation_diagnostics=generation_diagnostics,
            batch_fallback_error=batch_fallback_error,
            candidate_id=candidate_id,
            round_id=round_id,
        )

    def record_grounding(
        self,
        question_id: str,
        grounding_data: Optional[Dict[str, Any]],
    ) -> None:
        """Record grounding trace into audit logger history."""
        self.audit_logger.record_grounding(question_id, grounding_data)

    def write_final(
        self,
        outcome: GateOutcome,
        trace_meta: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Write final answer to submission.jsonl and emit audit log.
        
        Guarantees:
        - Only writes when outcome.action == FINAL.
        - De-duplicates by question_id (max 1 submission line per question).
        - Flushes immediately to disk.
        """
        if outcome.action != GateAction.FINAL:
            # RETRY actions must never write to submission.jsonl
            return

        if outcome.final_answer is None:
            raise OutputWriteError("GateOutcome with action=FINAL must have final_answer")

        meta = trace_meta or {}
        q_id = outcome.question_id

        # De-duplicate check
        if q_id not in self.seen_ids:
            try:
                submission_dict = outcome.final_answer.to_submission_dict()
                line_str = json.dumps(submission_dict, ensure_ascii=False, allow_nan=False)

                with open(self.submission_path, "a", encoding="utf-8") as f:
                    f.write(line_str + "\n")
                    f.flush()

                self.seen_ids.add(q_id)
            except Exception as exc:
                raise OutputWriteError(f"Failed to write submission line for {q_id}: {exc}")

        # Always write audit log
        try:
            self.audit_logger.write_log(
                outcome=outcome,
                business_id=str(meta.get("business_id", "")),
                contract_version=str(meta.get("contract_version", "b05.v1")),
                total_elapsed_ms=meta.get("total_elapsed_ms"),
                model_version=str(meta.get("model_version", "default")),
                prompt_version=str(meta.get("prompt_version", "default")),
                grounding=meta.get("grounding"),
            )
        except Exception as exc:
            raise OutputWriteError(f"Failed to write audit log for {q_id}: {exc}")

    def finalize(
        self,
        outcomes: Iterable[GateOutcome],
        *,
        expected_ids: Sequence[str],
        reference_records: Sequence[Mapping] | None = None,
    ) -> Dict[str, Any]:
        """Replace the append journal with a validated canonical artifact."""
        manifest = SubmissionFinalizer(self.result_dir).finalize(
            outcomes,
            expected_ids=expected_ids,
            reference_records=reference_records,
        )
        self.seen_ids = set(str(question_id) for question_id in expected_ids)
        return manifest
