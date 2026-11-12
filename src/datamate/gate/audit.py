"""Per-Question Audit Logger for B0.5 Basic Output Gate."""

import hashlib
import json
from pathlib import Path
import re
from typing import Any, Dict, List, Optional

from .contracts import GateOutcome


class AuditLogger:
    """Logs detailed per-question audit traces to disk."""

    def __init__(self, logs_dir: Path):
        self.logs_dir = Path(logs_dir)
        self.logs_dir.mkdir(parents=True, exist_ok=True)
        # In-memory attempts history to merge across retry attempts
        self._history: Dict[str, List[Dict[str, Any]]] = {}
        # In-memory grounding results per question
        self._grounding: Dict[str, Optional[Dict[str, Any]]] = {}

    def get_history(self, question_id: str) -> List[Dict[str, Any]]:
        """Trả về bản sao danh sách các attempt đã ghi cho một câu hỏi."""
        return list(self._history.get(question_id, []))

    def record_grounding(self, question_id: str, grounding_data: Optional[Dict[str, Any]]) -> None:
        """Lưu vết kết quả grounding cho câu hỏi."""
        self._grounding[question_id] = grounding_data

    def get_grounding(self, question_id: str) -> Optional[Dict[str, Any]]:
        """Trả về kết quả grounding đã lưu cho câu hỏi."""
        return self._grounding.get(question_id)

    def _safe_filename(self, question_id: str) -> str:
        """Generate safe, collision-resistant filename without path traversal."""
        slug = re.sub(r"[^a-zA-Z0-9_-]", "_", question_id)
        q_hash = hashlib.sha256(question_id.encode("utf-8")).hexdigest()[:8]
        return f"{slug}_{q_hash}.json"

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
        assumptions: Optional[List[str]] = None,
        error_message: Optional[str] = None,
        llm_generation_ms: Optional[float] = None,
        generation_diagnostics: Optional[Dict[str, Any]] = None,
        batch_fallback_error: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Record attempt trace in history (including LLM thinking and assumptions)."""
        if question_id not in self._history:
            self._history[question_id] = []

        entry: Dict[str, Any] = {
            "attempt": attempt,
            "sql": sql,
            "execution_status": execution_status,
            "error_code": error_code,
            "execution_ms": execution_ms,
            "result_row_count": row_count,
        }
        if llm_generation_ms is not None:
            entry["llm_generation_ms"] = llm_generation_ms
        if thinking is not None:
            entry["thinking"] = thinking
        if assumptions is not None:
            entry["assumptions"] = list(assumptions)
        if error_message is not None:
            entry["error_message"] = error_message
        if generation_diagnostics is not None:
            entry["generation_diagnostics"] = generation_diagnostics
        if batch_fallback_error is not None:
            entry["batch_fallback_error"] = batch_fallback_error
        self._history[question_id].append(entry)

    def write_log(
        self,
        outcome: GateOutcome,
        business_id: str = "",
        contract_version: str = "b05.v1",
        total_elapsed_ms: Optional[float] = None,
        model_version: str = "default",
        prompt_version: str = "default",
        grounding: Optional[Dict[str, Any]] = None,
    ) -> Path:
        """Write complete audit log for question to JSON file."""
        q_id = outcome.question_id
        filepath = self.logs_dir / self._safe_filename(q_id)

        attempts = self._history.get(q_id, [])
        grounding_data = grounding if grounding is not None else self._grounding.get(q_id)

        final_ans_dict = None
        if outcome.final_answer:
            final_ans_dict = outcome.final_answer.to_submission_dict()

        # BTC Guidelines Section 3.3 required fields: id, answer, elapsed_ms, thinking, code, output
        thinking_val: Optional[Any] = None
        code_val: Optional[str] = None
        output_val: Optional[Any] = None
        if attempts:
            thinkings = [a.get("thinking") for a in attempts if a.get("thinking")]
            if len(thinkings) == 1:
                thinking_val = thinkings[0]
            elif len(thinkings) > 1:
                thinking_val = thinkings
            last_attempt = attempts[-1]
            code_val = last_attempt.get("sql")
            output_val = last_attempt.get("result_sample") or (final_ans_dict.get("answer") if final_ans_dict else None)

        log_payload = {
            "id": q_id,
            "answer": final_ans_dict,
            "elapsed_ms": int(round(total_elapsed_ms or 0)),
            "thinking": thinking_val,
            "code": code_val,
            "output": output_val,
            "business_id": business_id,
            "contract_version": contract_version,
            "final_decision": outcome.decision,
            "reason_code": outcome.reason_code,
            "final_answer": final_ans_dict,
            "grounding": grounding_data,
            "attempts": attempts,
            "checks": outcome.validation.get("errors", []),
            "warnings": outcome.validation.get("warnings", []),
            "total_elapsed_ms": total_elapsed_ms,
            "model_version": model_version,
            "prompt_version": prompt_version,
            "legacy_decision": outcome.legacy_decision,
            "shadow_decision": outcome.shadow_decision,
            "shadow_reason_code": outcome.shadow_reason_code,
            "risk_assessment": (
                {
                    "policy_version": outcome.risk_assessment.policy_version,
                    "policy_mode": outcome.risk_assessment.policy_mode,
                    "hard_failures": outcome.risk_assessment.hard_failures,
                    "warnings": outcome.risk_assessment.warnings,
                    "release_status": outcome.risk_assessment.release_status,
                }
                if outcome.risk_assessment
                else None
            ),
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(log_payload, f, ensure_ascii=False, indent=2)

        return filepath
