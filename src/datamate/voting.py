"""Two-round execution-result voting, shared by single and batch entrypoints."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, replace
from decimal import Decimal
import json
import math
import time
from typing import Any, Literal

from datamate.gate.contracts import Decision, GateAction
from datamate.gate.errors import ErrorCode
from datamate.planner.diagnostics import diagnostics_dict
from datamate.planner.types import GenerationOptions


_THINKING_MODES = frozenset({"two_round", "always_off", "always_on", "inherit"})


@dataclass(frozen=True)
class VotingConfig:
    enabled: bool = False
    initial_candidates: int = 4
    threshold: float = 0.5
    temperature: float = 0.7
    top_p: float = 0.8
    top_k: int = 20
    rounds: int = 2
    thinking_mode: Literal["two_round", "always_off", "always_on", "inherit"] = "two_round"

    def __post_init__(self) -> None:
        if type(self.enabled) is not bool:
            raise ValueError("enabled must be bool")
        if type(self.initial_candidates) is not int or self.initial_candidates not in (4, 8):
            raise ValueError("initial_candidates must be 4 or 8")
        if type(self.rounds) is not int or self.rounds not in (1, 2):
            raise ValueError("rounds must be 1 or 2")
        if self.thinking_mode not in _THINKING_MODES:
            raise ValueError(f"thinking_mode must be one of {sorted(_THINKING_MODES)}")
        if isinstance(self.threshold, bool) or not math.isfinite(self.threshold) or not 0 <= self.threshold < 1:
            raise ValueError("threshold must be finite and in [0, 1)")
        GenerationOptions(temperature=self.temperature, top_p=self.top_p, top_k=self.top_k)
        if not math.isfinite(self.temperature) or self.temperature <= 0:
            raise ValueError("Voting requires a finite temperature > 0")

    def options(self, base: GenerationOptions, round_id: int) -> GenerationOptions:
        mode_map: dict[str, bool | None] = {
            "two_round": round_id == 2,
            "always_off": False,
            "always_on": True,
            "inherit": base.enable_thinking,
        }
        enable_thinking = mode_map[self.thinking_mode]
        budget = None if enable_thinking is False else base.thinking_token_budget
        return replace(
            base,
            temperature=self.temperature,
            top_p=self.top_p,
            top_k=self.top_k,
            seed=base.seed + (round_id - 1) * 100000 if base.seed is not None else None,
            enable_thinking=enable_thinking,
            thinking_token_budget=budget,
        )


def _canonical(value: Any) -> Any:
    """Typed numeric equivalence, preserving sequence order and exact strings."""
    if isinstance(value, bool):
        return ["bool", value]
    if isinstance(value, (int, float, Decimal)):
        number = Decimal(str(value))
        if not number.is_finite():
            raise ValueError("Nonfinite voting result")
        text = format(number, "f")
        if "." in text:
            text = text.rstrip("0").rstrip(".")
        return ["number", "0" if number == 0 else text]
    if isinstance(value, dict):
        return ["object", [[k, _canonical(v)] for k, v in sorted(value.items())]]
    if isinstance(value, (list, tuple)):
        return ["array", [_canonical(v) for v in value]]
    return [type(value).__name__, value]


def vote(candidates: list[dict], threshold: float) -> tuple[Any, dict]:
    groups: dict[str, list[dict]] = defaultdict(list)
    for candidate in candidates:
        outcome = candidate["outcome"]
        if outcome.decision == Decision.UNANSWERABLE:
            key = "unanswerable"
        elif outcome.decision == Decision.ANSWER and outcome.final_answer is not None:
            key = json.dumps([outcome.final_answer.type, _canonical(outcome.final_answer.answer)],
                             ensure_ascii=False, sort_keys=True)
        else:
            continue
        groups[key].append(candidate)
    ranked = sorted(groups.items(), key=lambda item: (-len(item[1]), item[0]))
    total = len(candidates)
    winner = None
    if ranked and (len(ranked) == 1 or len(ranked[0][1]) > len(ranked[1][1])):
        if Decimal(len(ranked[0][1])) >= Decimal(str(threshold)) * total:
            winner = min(ranked[0][1], key=lambda c: c["candidate_id"])
    summary = {
        "total_candidates": total, "threshold": threshold,
        "groups": [{"key": key, "votes": len(items), "ratio": len(items) / total,
                    "candidate_ids": [c["candidate_id"] for c in items]} for key, items in ranked],
        "winner_candidate_id": winner["candidate_id"] if winner else None,
    }
    return winner["outcome"] if winner else None, summary


def _infer(pipeline, items: list[dict], options, repair: bool):
    """Preserve item identity on batch failure, including short batch replies."""
    batch = pipeline.generator.repair_batch if repair else pipeline.generator.generate_batch
    single = pipeline.generator.repair if repair else pipeline.generator.generate
    start = time.perf_counter()
    fallback = None
    try:
        results = list(batch(items, options=options))
        if len(results) != len(items):
            raise RuntimeError(f"Expected {len(items)} batch replies, got {len(results)}")
    except Exception as exc:
        fallback = diagnostics_dict(exc)
        results = []
        for index, item in enumerate(items):
            try:
                individual_options = replace(options, seed=options.seed + index) if options.seed is not None else options
                results.append(single(**item, options=individual_options))
            except Exception as error:
                results.append(error)
    return results, (time.perf_counter() - start) * 1000 / len(items), fallback


def run_voting(pipeline, entries: list[dict], writer=None) -> None:
    """Populate entry outcomes; batch candidates across questions, then repairs by depth."""
    config = pipeline.voting
    base = pipeline.options or getattr(getattr(pipeline.generator, "model", None), "default_options", None) or GenerationOptions()
    active = entries
    for entry in active:
        entry["voting_candidates"] = []
        entry["voting_rounds"] = []
    round_plan = ((1, config.initial_candidates),) if config.rounds == 1 else ((1, config.initial_candidates), (2, 4))
    for round_id, count in round_plan:
        if not active:
            break
        options = config.options(base, round_id)
        pending = []
        for entry in active:
            q = entry["q_meta"]
            for _ in range(count):
                candidate = {"candidate_id": len(entry["voting_candidates"]), "round_id": round_id,
                             "entry": entry, "tokens": {"input": 0, "output": 0}, "repairs": 0, "llm_ms": 0.0, "evaluation_ms": 0.0, "tokens_complete": True}
                candidate["input"] = dict(context=entry["context"], question=q.question,
                                          as_of_date=q.as_of_date, industry=entry.get("industry"),
                                          grounded_hint=entry.get("grounded_hint"))
                entry["voting_candidates"].append(candidate)
                pending.append(candidate)
        for attempt in range(3):
            if not pending:
                break
            results, llm_ms, fallback = _infer(pipeline, [c["input"] for c in pending], options, attempt > 0)
            next_pending = []
            for candidate, result in zip(pending, results):
                entry = candidate["entry"]
                q = entry["q_meta"]
                candidate["repairs"] = attempt
                candidate["llm_ms"] += llm_ms
                diagnostic = diagnostics_dict(result)
                if fallback is not None or diagnostic is None or any(
                    diagnostic.get(name + "_tokens") is None for name in ("input", "output")
                ):
                    candidate["tokens_complete"] = False
                for name in ("input", "output"):
                    candidate["tokens"][name] += (diagnostic or {}).get(name + "_tokens") or 0
                if isinstance(result, Exception):
                    outcome = pipeline._abstain_outcome(q.id, str(result), attempt,
                                                        code=ErrorCode.GENERATION_INVALID if attempt < 2 else ErrorCode.RETRY_EXHAUSTED)
                    if writer:
                        writer.record_attempt(question_id=q.id, attempt=attempt, sql="", execution_status="error",
                                              error_code=ErrorCode.GENERATION_INVALID, error_message=str(result),
                                              generation_diagnostics=diagnostic, llm_generation_ms=llm_ms,
                                              batch_fallback_error=fallback, candidate_id=candidate["candidate_id"],
                                              round_id=round_id)
                    feedback, previous_sql = str(result), candidate["input"].get("previous_sql", "")
                    previous_plan = candidate["input"].get("previous_plan")
                    error_code = ErrorCode.GENERATION_INVALID
                    failed_checks = [ErrorCode.GENERATION_INVALID]
                    retry = attempt < 2
                else:
                    evaluation_start = time.perf_counter()
                    outcome = pipeline._evaluate_attempt(
                        q_meta=q, bundle_path=entry["bundle_path"], context=entry["context"],
                        gen_res=result, attempt=attempt, max_retries=2, grounded=entry.get("grounded"),
                        writer=writer, llm_generation_ms=llm_ms, batch_fallback_error=fallback,
                        candidate_id=candidate["candidate_id"], round_id=round_id)
                    candidate["evaluation_ms"] += (time.perf_counter() - evaluation_start) * 1000
                    repair = outcome.repair_request
                    retry = outcome.action == GateAction.RETRY and repair is not None and attempt < 2
                    feedback = f"[{repair.error_type}] {repair.error_message}\n{repair.instruction}" if retry else ""
                    previous_sql = (repair.failed_sql or result.sql or "") if retry else ""
                    previous_plan = result.structured_plan if retry else None
                    error_code = (repair.error_code or outcome.reason_code) if retry else None
                    failed_checks = list(outcome.validation.get("errors", [])) if retry else []
                candidate["outcome"] = outcome
                if retry:
                    candidate["input"].update(
                        previous_sql=previous_sql,
                        error_message=feedback,
                        previous_plan=previous_plan,
                        error_code=error_code,
                        failed_checks=failed_checks,
                    )
                    next_pending.append(candidate)
            pending = next_pending
        still_active = []
        has_next_round = round_id < config.rounds
        for entry in active:
            winner, summary = vote(entry["voting_candidates"], config.threshold)
            next_action = (
                "answer"
                if winner
                else ("thinking_round" if has_next_round and config.thinking_mode == "two_round" else ("round_2" if has_next_round else "abstain"))
            )
            summary.update(
                round_id=round_id,
                thinking_enabled=options.enable_thinking,
                next_action=next_action,
            )
            entry["voting_rounds"].append(summary)
            if winner is None and has_next_round:
                still_active.append(entry)
                continue
            outcome = replace(winner) if winner else pipeline._abstain_outcome(
                entry["q_meta"].id, "No unique result met voting threshold", 0,
                code="VOTING_THRESHOLD_NOT_MET")
            candidates = entry["voting_candidates"]
            outcome.voting = {"rounds": entry["voting_rounds"],
                              "total_repairs": sum(c["repairs"] for c in candidates),
                              "llm_generation_ms": sum(c["llm_ms"] for c in candidates),
                              "evaluation_ms": sum(c["evaluation_ms"] for c in candidates),
                              "tokens_complete": all(c["tokens_complete"] for c in candidates),
                              "input_tokens": sum(c["tokens"]["input"] for c in candidates),
                              "output_tokens": sum(c["tokens"]["output"] for c in candidates),
                              "candidates": [{"candidate_id": c["candidate_id"], "round_id": c["round_id"],
                                              "decision": c["outcome"].decision,
                                              "reason_code": c["outcome"].reason_code,
                                              "repairs": c["repairs"]} for c in candidates]}
            entry["outcome"] = outcome
        active = still_active
