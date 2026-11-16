"""Helpers for balanced multi-GPU sharding and crash-safe abstain-first submissions."""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Mapping, Sequence
from contextlib import contextmanager
import fcntl
import hashlib
import json
from pathlib import Path
import shutil
import tempfile
from typing import Any, Iterator

from .contracts import AnswerType, FinalAnswer
from .finalizer import SubmissionFinalizer


@contextmanager
def _submission_lock(target_dir: Path) -> Iterator[None]:
    """Serialize read-modify-write updates without polluting output_dir (/result)."""
    target_dir.mkdir(parents=True, exist_ok=True)
    digest = hashlib.sha256(str(target_dir.resolve()).encode("utf-8")).hexdigest()[:12]
    lock_path = Path(tempfile.gettempdir()) / f"datamate_sub_{digest}.lock"
    with lock_path.open("a+", encoding="utf-8") as lock_file:
        fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
        try:
            yield
        finally:
            fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)


def _question_id(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("id", ""))
    return str(getattr(item, "id", ""))


def _business_id(item: Any) -> str:
    if isinstance(item, Mapping):
        return str(item.get("business_id", ""))
    return str(getattr(item, "business_id", ""))


def partition_questions_by_business(
    questions: Sequence[Mapping[str, Any]],
    *,
    num_shards: int,
    shard_index: int,
) -> tuple[list[dict[str, Any]], list[str]]:
    """Assign each business_id greedily to balance question counts across shards.

    Keeping all questions of a business on the same shard avoids concurrent writes
    to shared DuckDB/context bundles and preserves KV prefix cache locality.
    """
    if num_shards < 1:
        raise ValueError(f"num_shards must be >= 1, got {num_shards}")
    if not (0 <= shard_index < num_shards):
        raise ValueError(f"shard_index must be in [0, {num_shards - 1}], got {shard_index}")

    if num_shards == 1:
        q_list = [dict(q) for q in questions]
        biz_list = sorted({_business_id(q) for q in q_list if _business_id(q)})
        return q_list, biz_list

    by_business: dict[str, list[dict[str, Any]]] = defaultdict(list)
    unassigned: list[dict[str, Any]] = []
    for item in questions:
        q_dict = dict(item)
        biz = _business_id(q_dict)
        if biz:
            by_business[biz].append(q_dict)
        else:
            unassigned.append(q_dict)

    shard_loads = [0] * num_shards
    biz_to_shard: dict[str, int] = {}
    for biz, biz_qs in sorted(by_business.items(), key=lambda kv: (-len(kv[1]), kv[0])):
        chosen = min(range(num_shards), key=lambda idx: (shard_loads[idx], idx))
        biz_to_shard[biz] = chosen
        shard_loads[chosen] += len(biz_qs)

    unassigned_shards: dict[str, int] = {}
    for q_dict in unassigned:
        chosen = min(range(num_shards), key=lambda idx: (shard_loads[idx], idx))
        unassigned_shards[_question_id(q_dict)] = chosen
        shard_loads[chosen] += 1

    shard_questions: list[dict[str, Any]] = []
    for item in questions:
        q_dict = dict(item)
        biz = _business_id(q_dict)
        assigned = biz_to_shard[biz] if biz else unassigned_shards[_question_id(q_dict)]
        if assigned == shard_index:
            shard_questions.append(q_dict)

    shard_businesses = sorted(biz for biz, idx in biz_to_shard.items() if idx == shard_index)
    return shard_questions, shard_businesses


def _write_canonical_submission(
    target_dir: Path,
    records: Mapping[str, Mapping[str, Any]],
    expected_ids: Sequence[str],
) -> dict[str, Any]:
    lines = [
        json.dumps(
            records.get(qid) or FinalAnswer(id=qid, type=AnswerType.ABSTAIN).to_submission_dict(),
            ensure_ascii=False,
            allow_nan=False,
            separators=(",", ":"),
        )
        for qid in expected_ids
    ]
    payload = (("\n".join(lines) + "\n") if lines else "").encode("utf-8")
    digest = hashlib.sha256(payload).hexdigest()
    manifest = {
        "artifact": "submission.jsonl",
        "record_count": len(lines),
        "sha256": digest,
    }
    manifest_payload = (
        json.dumps(manifest, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n"
    ).encode("utf-8")

    SubmissionFinalizer._atomic_write(target_dir / "submission.jsonl", payload, "submission.jsonl.tmp")
    SubmissionFinalizer._atomic_write(
        target_dir / "submission.manifest.json", manifest_payload, "submission.manifest.json.tmp"
    )
    return manifest


def seed_abstain_submission(
    result_dir: Path | str,
    questions: Sequence[Any],
) -> dict[str, Any]:
    """Pre-create submission.jsonl and manifest with abstain placeholders for every question."""
    target_dir = Path(result_dir)
    expected_ids = [_question_id(q) for q in questions]
    records = {
        qid: FinalAnswer(id=qid, type=AnswerType.ABSTAIN).to_submission_dict()
        for qid in expected_ids
    }
    with _submission_lock(target_dir):
        return _write_canonical_submission(target_dir, records, expected_ids)


def _read_jsonl_records(path: Path) -> dict[str, dict[str, Any]]:
    records: dict[str, dict[str, Any]] = {}
    if not path.is_file():
        return records
    with path.open("r", encoding="utf-8") as handle:
        for line in handle:
            if line.strip():
                rec = json.loads(line)
                if "id" in rec:
                    records[str(rec["id"])] = rec
    return records


def upsert_submission_records(
    target_dir: Path | str,
    updated_records: Mapping[str, Mapping[str, Any]],
    *,
    expected_ids: Sequence[str],
) -> dict[str, Any]:
    """Atomically overlay completed shard records onto an abstain-seeded submission.jsonl."""
    dest = Path(target_dir)
    expected = [str(qid) for qid in expected_ids]
    with _submission_lock(dest):
        current = _read_jsonl_records(dest / "submission.jsonl")
        for qid in expected:
            if qid not in current:
                current[qid] = FinalAnswer(id=qid, type=AnswerType.ABSTAIN).to_submission_dict()
        for qid, rec in updated_records.items():
            key = str(qid)
            if key in current or not expected:
                current[key] = dict(rec)
        return _write_canonical_submission(dest, current, expected or list(current))


def _merge_jsonl_by_key(
    target_path: Path,
    source_paths: Sequence[Path],
    *,
    id_field: str,
    expected_ids: Sequence[str],
) -> None:
    if not any(src.is_file() for src in source_paths):
        return
    collected: dict[str, dict[str, Any]] = {}
    extra: list[dict[str, Any]] = []
    expected_set = {str(qid) for qid in expected_ids}
    for src in source_paths:
        if not src.is_file():
            continue
        with src.open("r", encoding="utf-8") as handle:
            for line in handle:
                if not line.strip():
                    continue
                rec = json.loads(line)
                qid = str(rec.get(id_field, ""))
                if qid and qid in expected_set:
                    collected[qid] = rec
                else:
                    extra.append(rec)

    ordered: list[dict[str, Any]] = [collected[qid] for qid in expected_ids if qid in collected]
    ordered.extend(extra)
    content = "\n".join(json.dumps(item, ensure_ascii=False) for item in ordered)
    if ordered:
        content += "\n"
    SubmissionFinalizer._atomic_write(target_path, content.encode("utf-8"), f"{target_path.name}.tmp")


def merge_shard_artifacts(
    output_dir: Path | str,
    shard_dirs: Sequence[Path | str],
    *,
    expected_ids: Sequence[str],
) -> dict[str, Any]:
    """Merge shard submissions, trace logs, and per-question audit files into output_dir."""
    dest = Path(output_dir)
    dest.mkdir(parents=True, exist_ok=True)
    shards = [Path(s) for s in shard_dirs]
    expected = [str(qid) for qid in expected_ids]

    merged_records: dict[str, dict[str, Any]] = {}
    for shard in shards:
        merged_records.update(_read_jsonl_records(shard / "submission.jsonl"))
    manifest = upsert_submission_records(dest, merged_records, expected_ids=expected)

    _merge_jsonl_by_key(
        dest / "detailed_logs.jsonl",
        [s / "detailed_logs.jsonl" for s in shards],
        id_field="id",
        expected_ids=expected,
    )
    _merge_jsonl_by_key(
        dest / "gate_trace.jsonl",
        [s / "gate_trace.jsonl" for s in shards],
        id_field="id",
        expected_ids=expected,
    )
    _merge_jsonl_by_key(
        dest / "grounding_trace.jsonl",
        [s / "grounding_trace.jsonl" for s in shards],
        id_field="question_id",
        expected_ids=expected,
    )

    dest_logs = dest / "logs"
    dest_logs.mkdir(parents=True, exist_ok=True)
    for shard in shards:
        shard_logs = shard / "logs"
        if not shard_logs.is_dir():
            continue
        for item in shard_logs.iterdir():
            if item.is_file():
                shutil.copy2(item, dest_logs / item.name)

    return manifest


__all__ = [
    "merge_shard_artifacts",
    "partition_questions_by_business",
    "seed_abstain_submission",
    "upsert_submission_records",
]
