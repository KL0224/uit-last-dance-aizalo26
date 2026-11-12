"""Canonical submission builder with whole-run integrity checks."""

import hashlib
import json
import os
from pathlib import Path
from typing import Iterable, Mapping, Sequence

from .contracts import AnswerType, GateAction, GateOutcome
from .errors import OutputWriteError


class SubmissionFinalizer:
    """Build the upload artifact from canonical final outcomes, not append order."""

    def __init__(self, result_dir: Path | str):
        self.result_dir = Path(result_dir)
        self.result_dir.mkdir(parents=True, exist_ok=True)
        self.submission_path = self.result_dir / "submission.jsonl"
        self.manifest_path = self.result_dir / "submission.manifest.json"

    @staticmethod
    def _canonical_records(outcomes: Iterable[GateOutcome]) -> dict[str, dict]:
        records: dict[str, dict] = {}
        valid_types = {answer_type.value for answer_type in AnswerType}
        for outcome in outcomes:
            question_id = str(outcome.question_id)
            if question_id in records:
                raise OutputWriteError(f"Duplicate canonical outcome ID: {question_id}")
            if outcome.action != GateAction.FINAL or outcome.final_answer is None:
                raise OutputWriteError(f"Outcome {question_id} is not a final answer")
            if outcome.final_answer.id != question_id:
                raise OutputWriteError(f"Outcome/final answer ID mismatch for {question_id}")
            answer_type = (
                outcome.final_answer.type.value
                if isinstance(outcome.final_answer.type, AnswerType)
                else str(outcome.final_answer.type)
            )
            if answer_type not in valid_types:
                raise OutputWriteError(f"Invalid answer type '{answer_type}' for {question_id}")
            record = outcome.final_answer.to_submission_dict()
            record["type"] = answer_type
            try:
                json.dumps(record, ensure_ascii=False, allow_nan=False)
            except (TypeError, ValueError) as exc:
                raise OutputWriteError(f"Invalid JSON value for {question_id}: {exc}") from exc
            records[question_id] = record
        return records

    @staticmethod
    def _reference_map(reference_records: Sequence[Mapping]) -> dict[str, dict]:
        mapped: dict[str, dict] = {}
        for record in reference_records:
            question_id = str(record.get("id", ""))
            if not question_id or question_id in mapped:
                raise OutputWriteError("Reference artifact has missing or duplicate ID")
            mapped[question_id] = dict(record)
        return mapped

    @staticmethod
    def _atomic_write(path: Path, payload: bytes, temp_name: str) -> None:
        temp_path = path.parent / temp_name
        try:
            with open(temp_path, "wb") as stream:
                stream.write(payload)
                stream.flush()
                os.fsync(stream.fileno())
            os.replace(temp_path, path)
            if os.name != "nt":
                try:
                    directory_fd = os.open(path.parent, os.O_RDONLY)
                    try:
                        os.fsync(directory_fd)
                    finally:
                        os.close(directory_fd)
                except OSError:
                    pass
        finally:
            if temp_path.exists():
                temp_path.unlink()

    def finalize(
        self,
        outcomes: Iterable[GateOutcome],
        *,
        expected_ids: Sequence[str],
        reference_records: Sequence[Mapping] | None = None,
    ) -> dict:
        expected = [str(question_id) for question_id in expected_ids]
        if len(expected) != len(set(expected)):
            raise OutputWriteError("Expected question manifest contains duplicate IDs")

        records = self._canonical_records(outcomes)
        expected_set = set(expected)
        actual_set = set(records)
        missing = sorted(expected_set - actual_set)
        extra = sorted(actual_set - expected_set)
        if missing:
            raise OutputWriteError(f"Canonical outcomes are missing IDs: {missing}")
        if extra:
            raise OutputWriteError(f"Canonical outcomes contain extra IDs: {extra}")

        if reference_records is not None:
            reference = self._reference_map(reference_records)
            if reference != records:
                raise OutputWriteError("Artifact mismatch between canonical outcomes and reference records")

        lines = [
            json.dumps(records[question_id], ensure_ascii=False, allow_nan=False, separators=(",", ":"))
            for question_id in expected
        ]
        payload = (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
        digest = hashlib.sha256(payload).hexdigest()
        manifest = {
            "artifact": self.submission_path.name,
            "record_count": len(lines),
            "sha256": digest,
        }
        manifest_payload = (
            json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
        ).encode("utf-8")

        self._atomic_write(self.submission_path, payload, "submission.jsonl.tmp")
        self._atomic_write(self.manifest_path, manifest_payload, "submission.manifest.json.tmp")
        return manifest
