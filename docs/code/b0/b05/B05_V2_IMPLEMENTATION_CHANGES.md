# B0.5 v2 — Báo cáo thay đổi code và kết quả local

**Ngày:** 2026-11-09
**Phạm vi:** `src/datamate/b0/b05`, replay script và test trực tiếp
**Không thực hiện:** sửa B01–B04, gọi model, chạy Modal hoặc bật enforce trong pipeline production

## 1. Kết quả bàn giao

Kế hoạch trong `docs/improvement/B05_IMPROVEMENT_PLAN_AND_RETROSPECTIVE.md` đã được triển khai thành một B0.5 proof-driven, fail-closed và tương thích v1.

Các khả năng mới:

- contract `b05.v2` có plan identity, capability proof và semantic proof;
- rollout `legacy → shadow → enforce`;
- policy deterministic `b05-risk.v1`;
- strict output không mutate/rescue answer type;
- capability proof bắt buộc cho `unanswerable`;
- repair khóa plan/metric/type và vẫn giới hạn một retry;
- audit có legacy/shadow/risk decision;
- canonical finalizer ghi atomic và sinh SHA-256;
- replay local tái lập baseline/counterfactual mà không chạy Modal.

## 2. Thay đổi theo file

| File | Thay đổi chính |
|---|---|
| `contracts.py` | thêm enum policy/proof/release; `CapabilityProof`, `SemanticProof`, `RepairOrigin`, `RiskAssessment`; mở rộng request/outcome/repair |
| `adapters.py` | parse v1/v2; v2 bắt buộc plan identity; validate enum và provenance; missing proof được biểu diễn `unknown` |
| `risk_policy.py` | policy pure deterministic, completeness checks, repair invariant checks, blocking reason |
| `gate.py` | dispatcher legacy/shadow/enforce; enforce fail closed; strict formatting; counterfactual shadow fields |
| `answerability.py` | v2 chỉ tin `unsupported` capability proof có provenance; v1 giữ logic cũ |
| `validators.py` | bỏ mutation scalar nhiều dòng thành list |
| `retry.py` | phân loại mismatch/proof failure là repairable ở attempt 0; chuyển plan invariants vào repair request |
| `errors.py` | thêm reason codes v2 và artifact integrity |
| `audit.py` | ghi policy mode/version, release status, legacy/shadow decision và risk signals |
| `finalizer.py` | validate whole run, deterministic serialization, atomic replace, checksum manifest |
| `writer.py` | thêm API `finalize()` nhưng giữ `write_final()` tương thích |
| `cli.py` | thu canonical outcomes và bắt buộc finalization ở cuối standalone run |
| `__init__.py` | export contract/risk/finalizer public API mới |
| `scripts/analyze_b05_replay.py` | evaluator/replay local độc lập runtime và Modal |

## 3. Behavior trước và sau

| Tình huống | B0.5 cũ | B0.5 v2 enforce |
|---|---|---|
| scalar plan nhưng SQL trả nhiều dòng có `LIMIT > 1` | có thể mutate thành list | retry/abstain, type giữ nguyên |
| number candidate là text/date | formatter có thể đổi string/date | retry/abstain, không rescue |
| query chạy thành công nhưng thiếu semantic proof | answer nếu shape hợp lệ | abstain `SEMANTIC_PROOF_MISSING` |
| model tự khai missing field | có thể tạo unanswerable qua evidence v1 | không đủ; cần capability taxonomy/provenance |
| repair đổi metric/type | có thể vẫn answer nếu execution pass | abstain `REPAIR_SEMANTICS_CHANGED` |
| submission có duplicate/missing/type typo | append file không kiểm toàn tập | finalizer fail trước artifact mới |

## 4. TDD và verification

Implementation được chia thành các lát cắt contract, decision engine, finalizer và replay. Mỗi lát cắt có test RED trước implementation rồi focused GREEN.

| Lát cắt | RED đã quan sát | GREEN |
|---|---|---|
| Contract v2 | import thiếu `CapabilityStatus`; sau đó thiếu strict provenance | 9 contract v2 tests pass |
| Decision v2 | 9 test fail do chưa có risk/shadow/strict behavior | 11 decision/audit tests pass |
| Finalizer | module chưa tồn tại; sau đó enum normalization fail | 6 finalizer tests pass |
| Replay | module chưa tồn tại | 2 replay tests pass và số liệu full run khớp |

Full local suite:

```text
248 passed, 3 skipped, 11 subtests passed in 7.57s
```

Các lệnh xác minh chính:

```bash
uv run --extra dev pytest tests/test_b05_contract_v2.py -q
uv run --extra dev pytest tests/test_b05_decision_v2.py -q
uv run --extra dev pytest tests/test_b05_finalizer.py -q
uv run --extra dev pytest tests/test_b05_replay.py -q
uv run --extra dev pytest -q
```

## 5. Replay run public test cũ

Lệnh local đã chạy:

```bash
uv run python scripts/analyze_b05_replay.py \
  --ground-truth temp/gt/public_test_GT.jsonl \
  --submission artifacts/runs/public_test_full/submission.jsonl \
  --detailed-logs artifacts/runs/public_test_full/detailed_logs.jsonl
```

| Policy replay | Đúng | Sai | Abstain | Score | Delta so submission |
|---|---:|---:|---:|---:|---:|
| Submission đã nộp | 266 | 481 | 253 | -0,215 | — |
| Canonical final outcome | 267 | 479 | 254 | -0,212 | +0,003 |
| Canonical, chặn table | 267 | 441 | 292 | -0,174 | +0,041 |
| Canonical, chặn table và retry answer | 230 | 391 | 379 | -0,161 | +0,054 |
| Enforce proof trên artifact cũ thiếu proof | 0 | 0 | 1.000 | 0,000 | +0,215 |

Chỉ cải thiện `-0,215 → -0,212` từ canonical finalizer là lợi ích integrity có thể khẳng định trực tiếp. Các policy chặn theo type/retry là counterfactual hồi cứu, không được hard-code vào runtime. Enforce trên artifact cũ abstain toàn bộ vì artifact chưa có proof; đây là safe fallback, không phải mục tiêu coverage.

## 6. API sử dụng

### V2 shadow mặc định

```python
request = adapt_gate_request(raw_v2)  # không truyền policy_mode -> shadow
outcome = evaluate_gate(request)

assert outcome.legacy_decision is not None
assert outcome.shadow_decision is not None
assert outcome.risk_assessment.policy_version == "b05-risk.v1"
```

### Enforce

Request phải đặt `policy_mode="enforce"`, có plan identity và proof đầy đủ. `unknown` không được answer.

### Finalize artifact

```python
manifest = writer.finalize(
    canonical_outcomes,
    expected_ids=question_manifest,
    reference_records=optional_gate_records,
)
```

Kết quả gồm `submission.jsonl` và `submission.manifest.json` với `record_count` và `sha256`.

## 7. Compatibility và migration

- `b05.v1` tiếp tục chạy legacy và 36 fixture cũ vẫn pass.
- `b05.v2` mặc định shadow, nên không vô tình bật fail-closed ở rollout đầu.
- Field mới là additive; pipeline hiện tại chưa bị buộc chuyển ngay.
- Standalone CLI finalizes output ở cuối run.
- Pipeline B0 chính cần gọi finalizer bằng toàn bộ canonical outcomes và expected IDs khi owner tích hợp v2.

Migration đề xuất:

1. B0.2–B0.4 phát field v2 nhưng chạy shadow;
2. đo proof coverage, false block và unsafe release trên holdout;
3. đạt release targets rồi mới bật enforce local;
4. human review trước khi chạy Modal/submission mới.

## 8. Hạn chế còn lại

- B0.5 không thể sửa SQL/metric sai; chất lượng enforce phụ thuộc semantic proof upstream.
- Artifact cũ không chứa proof nên không thể replay precision của policy v2 thực tế.
- Pipeline chính hiện vẫn xây `b05.v1`; code này cung cấp boundary nhưng không tự thay ownership của B03/B04.
- Chưa chạy Modal theo yêu cầu.
- Không commit thay đổi; worktree giữ nguyên các tài liệu/report chưa tracked của người dùng.

## 9. File test mới

| Test | Phạm vi |
|---|---|
| `tests/test_b05_contract_v2.py` | parsing, enum, plan identity, proof provenance, v1 compatibility |
| `tests/test_b05_decision_v2.py` | safe/unknown/unsafe, shadow, strict type, UA proof, repair invariants |
| `tests/test_b05_finalizer.py` | determinism, SHA-256, duplicate/missing/extra/type/artifact mismatch |
| `tests/test_b05_replay.py` | scoring và policy delta |
