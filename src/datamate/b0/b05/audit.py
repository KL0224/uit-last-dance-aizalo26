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
    ) -> None:
        """Record attempt trace in history."""
        if question_id not in self._history:
            self._history[question_id] = []

        self._history[question_id].append({
            "attempt": attempt,
            "sql": sql,
            "execution_status": execution_status,
            "error_code": error_code,
            "execution_ms": execution_ms,
            "result_row_count": row_count,
        })

    def write_log(
        self,
        outcome: GateOutcome,
        business_id: str = "",
        contract_version: str = "b05.v1",
        total_elapsed_ms: Optional[float] = None,
        model_version: str = "default",
        prompt_version: str = "default",
    ) -> Path:
        """Write complete audit log for question to JSON file."""
        q_id = outcome.question_id
        filepath = self.logs_dir / self._safe_filename(q_id)

        attempts = self._history.get(q_id, [])

        final_ans_dict = None
        if outcome.final_answer:
            final_ans_dict = outcome.final_answer.to_submission_dict()

        log_payload = {
            "id": q_id,
            "business_id": business_id,
            "contract_version": contract_version,
            "final_decision": outcome.decision,
            "reason_code": outcome.reason_code,
            "final_answer": final_ans_dict,
            "attempts": attempts,
            "checks": outcome.validation.get("errors", []),
            "warnings": outcome.validation.get("warnings", []),
            "total_elapsed_ms": total_elapsed_ms,
            "model_version": model_version,
            "prompt_version": prompt_version,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(log_payload, f, ensure_ascii=False, indent=2)

        return filepath

