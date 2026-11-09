# Kế hoạch cải tiến B0.5 và phân tích hồi cứu Public Test

**Trạng thái:** Implemented locally — full test suite pass, chưa chạy Modal
**Ngày lập kế hoạch:** 2026-11-09
**Phạm vi sở hữu:** `src/datamate/b0/b05` và các test/CLI trực tiếp của B0.5
**Nguồn đánh giá:** `artifacts/runs/public_test_full`, `temp/gt/public_test_GT.jsonl`
**Báo cáo liên quan:** [PUBLIC_TEST_BASELINE_B01_EVALUATION.md](../review/PUBLIC_TEST_BASELINE_B01_EVALUATION.md), [B0_B01_B05_IMPROVEMENT_PLAN.md](../review/B0_B01_B05_IMPROVEMENT_PLAN.md)

**Tài liệu sau triển khai:** [Kiến trúc proof-driven B0.5](../architecture/b0/B0_5_PROOF_DRIVEN_GATE_ARCHITECTURE.md), [Báo cáo thay đổi code B0.5 v2](../code/b0/b05/B05_V2_IMPLEMENTATION_CHANGES.md)

> Theo yêu cầu, toàn bộ plan và task checklist được đặt trong một tài liệu này. `tasks/plan.md` hiện chứa checklist cũ của lần xây dựng B0.5 ban đầu và chưa được đánh dấu hoàn thành; tài liệu đó không bị ghi đè.

## 1. Kết luận điều hành

B0.5 hiện làm tốt việc kiểm tra execution status, shape, kiểu dữ liệu, null/non-finite và bounded retry. Tuy nhiên, nó đang là **output gate**, chưa phải **correctness/risk gate**:

- 606 câu có `VALID_RESULT` nhưng chỉ 208 câu đúng, precision 34,3%.
- 92 câu `VALID_RESULT_AFTER_RETRY` chỉ có 37 câu đúng, precision 40,2%.
- 391 lỗi của canonical output có đúng answer type nhưng sai nội dung.
- B0.5 đang tự đổi type trong validator/formatter để “cứu” output, làm che giấu mismatch upstream.
- `unanswerable` canonical có 22 đúng và 26 sai, precision 45,8%.
- writer ghi append từng dòng nhưng chưa có bước finalization atomic và đối chiếu toàn bộ artifact.

B0.5 không thể sửa một SQL sai thành đáp án đúng nếu không gọi lại B0.3/B0.4. Giá trị chính của phần bạn sở hữu là:

1. không phát hành đáp án khi proof chưa đủ;
2. phân biệt chính xác `answer`, `unanswerable`, `retry`, `abstain`;
3. không tự sửa answer type sau execution;
4. bảo đảm submission canonical và không thể bị corrupt âm thầm;
5. tạo shadow mode để đo tác động trước khi enforce.

Thiết kế đề xuất là B0.5 v2 theo hướng **proof-driven, fail-closed, backward-compatible**. B0.5 nhận semantic/capability proof từ các tầng khác, kiểm proof và đưa ra quyết định cuối; B0.5 không tự triển khai lại planner hay semantic SQL parser của B0.3/B0.4.

## 2. Baseline hồi cứu

### 2.1. Kết quả chính thức và canonical gate

| Phiên bản output | Đúng | Sai | Abstain | Answered precision | Score |
|---|---:|---:|---:|---:|---:|
| Submission đã nộp | 266 | 481 | 253 | 35,6% | **-0,215** |
| Canonical từ `detailed_logs.jsonl` | 267 | 479 | 254 | 35,8% | **-0,212** |

Chênh lệch `+0,003` đến hoàn toàn từ hai artifact mismatch:

- `q_fa1084dc1d3f`: canonical đúng `unanswerable`, submission thành `ubstain`;
- `q_fb290d8944ec`: canonical `abstain`, submission thành `ananswerable` và mang nhầm reason.

Đây là phần cải thiện **đo được và thuộc hoàn toàn B0.5 writer/finalizer**.

### 2.2. Chất lượng theo output type của canonical gate

| Type B0.5 phát hành | Đúng | Sai | Precision | Điểm ròng |
|---|---:|---:|---:|---:|
| `boolean` | 6 | 2 | 75,0% | +4 |
| `date` | 9 | 5 | 64,3% | +4 |
| `number` | 167 | 262 | 38,9% | -95 |
| `percent` | 42 | 91 | 31,6% | -49 |
| `list` | 8 | 25 | 24,2% | -17 |
| `string` | 13 | 30 | 30,2% | -17 |
| `table` | 0 | 38 | 0,0% | -38 |
| `unanswerable` | 22 | 26 | 45,8% | -4 |

Không được biến bảng này thành rule kiểu “luôn chặn list/table” trong production. Các tỷ lệ được tính trên Public GT và dễ overfit. Bảng chỉ cho thấy B0.5 hiện chưa có tín hiệu đủ mạnh để phân biệt output an toàn trong các nhóm lớn.

### 2.3. Kết quả theo retry

| Nhóm | Đúng | Sai | Abstain | Precision trên answer |
|---|---:|---:|---:|---:|
| Attempt 0 | 230 | 424 | 211 | 35,2% |
| Attempt 1 | 37 | 55 | 43 | 40,2% |

Retry hiện giúp query chạy/đúng shape, nhưng chưa chứng minh repair giữ nguyên metric, thời gian và answer type. Vì thế B0.5 v2 phải kiểm `plan_id` và semantic proof sau repair, không chỉ kiểm execution success.

### 2.4. Các counterfactual có thể replay từ artifact cũ

Các dòng dưới đây là **phân tích hồi cứu**, không phải kết quả đã đạt sau implementation:

| Policy hồi cứu | Đúng | Sai | Abstain | Score | Chênh so với submission |
|---|---:|---:|---:|---:|---:|
| Submission hiện tại | 266 | 481 | 253 | -0,215 | — |
| Chỉ dùng canonical finalizer | 267 | 479 | 254 | -0,212 | +0,003 |
| Canonical + chặn toàn bộ `table` | 267 | 441 | 292 | -0,174 | +0,041 |
| Canonical + chặn `table` và mọi answer sau retry | 230 | 391 | 379 | -0,161 | +0,054 |
| Enforce proof nhưng artifact cũ không có proof → abstain toàn bộ | 0 | 0 | 1.000 | 0,000 | +0,215 |
| Oracle B0.5 giữ mọi đáp án đúng, chặn mọi đáp án sai | 267 | 0 | 733 | +0,267 | +0,482 |

Diễn giải:

- `-0,212` là cải thiện chắc chắn từ integrity, không cần model mới.
- `-0,174` và `-0,161` chứng minh risk filtering có giá trị, nhưng policy dựa trên type/retry của chính Public Test không đủ căn cứ để deploy.
- `0,000` là safe fallback có thể bảo đảm nếu B0.5 abstain khi thiếu proof, nhưng coverage bằng 0 nên chỉ phù hợp như emergency mode.
- `+0,267` là upper bound lý thuyết của B0.5 nếu chỉ được giữ/chặn các candidate hiện có; B0.5 không thể vượt số câu đúng sẵn có nếu không nhận answer mới từ upstream.

### 2.5. Điều kiện để B0.5 đưa score từ âm sang dương

Với canonical score thô `267 - 479 = -212`, nếu B0.5 chuyển một số answer thành abstain:

```text
new_raw_score = -212 + wrong_removed - correct_lost
```

Muốn score dương:

```text
wrong_removed - correct_lost >= 213
```

Shape/type validation hiện tại không đủ đạt điều kiện này vì 391/479 lỗi canonical vẫn có đúng type. B0.5 cần semantic proof từ B0.3/B0.4 hoặc phải chọn emergency policy abstain gần như toàn bộ.

## 3. Mục tiêu và giới hạn trách nhiệm

### 3.1. B0.5 chịu trách nhiệm

- Validate `GateRequest` và proof contract.
- Quyết định `answer`, `unanswerable`, `retry`, `abstain`.
- Kiểm output shape/type/value một cách strict và không mutate input.
- Kiểm repair không thay đổi question semantics.
- Áp dụng risk policy đã version hóa.
- Ghi audit decision có thể replay.
- Finalize submission canonical, atomic, đủ ID, không trùng và có checksum.

### 3.2. B0.5 không chịu trách nhiệm

- Suy table grain hoặc join cardinality: B0.1.
- Xây capability taxonomy và metric definition: B0.2.
- Lập `QuestionPlan`, xác định metric/answer type và sinh SQL: B0.3.
- Parse SQL AST, kiểm grain/join/metric conformance và thực thi query: B0.4.
- Sửa SQL trực tiếp trong B0.5.
- Dùng Public GT trong runtime hoặc hard-code policy theo business/question ID.

### 3.3. Handoff cần yêu cầu từ các thành viên khác

| Owner | B0.5 cần nhận | Nếu thiếu trong `enforce` |
|---|---|---|
| B0.1/B0.2 | `catalog_version`, `rule_version`, capability ID và nguồn đã kiểm | `abstain: CAPABILITY_PROOF_MISSING` |
| B0.3 | `plan_id`, `expected_answer_type`, `metric_id`, generation telemetry | `abstain` hoặc contract retry |
| B0.4 | `SemanticProof`, invariant checks, execution diagnostics | `abstain: SEMANTIC_PROOF_MISSING` |
| Pipeline | policy mode và danh sách expected question IDs khi finalize | không sinh submission cuối |

Mọi field mới phải additive. `b05.v1` tiếp tục chạy ở `legacy` mode trong giai đoạn chuyển đổi.

## 4. Quyết định kiến trúc đề xuất

### 4.1. B0.5 v2 là proof consumer, không phải semantic SQL validator

**Chọn:** B0.4 phát `SemanticProof`; B0.5 kiểm status, provenance, version và quyết định release.
**Không chọn:** parse lại SQL trong B0.5.

Lý do là tránh hai semantic validator khác nhau giữa B0.4 và B0.5. B0.5 chỉ được có một số compatibility checks đơn giản cho v1/shadow, không biến chúng thành nguồn sự thật mới.

### 4.2. Answer type bất biến sau planning

`expected_answer_type` đến từ `QuestionPlan`. B0.5 chỉ kiểm result có conform hay không. Không còn:

- tự đổi scalar nhiều dòng thành `list`;
- tự đổi `number` thành `date/string` sau formatting error.

Mismatch ở attempt 0 có thể tạo repair request; mismatch ở attempt 1 phải abstain.

### 4.3. Fail closed theo ba trạng thái proof

Mỗi proof có `pass`, `fail`, `unknown`:

- `pass`: có thể tiếp tục;
- `fail`: retry nếu lỗi có khả năng repair và còn attempt, ngược lại abstain;
- `unknown`: shadow chỉ log; enforce phải abstain.

Không suy `pass` từ việc SQL chạy thành công.

### 4.4. Rollout theo `legacy → shadow → enforce`

```text
legacy   : B0.5 v1 quyết định output như hiện tại
shadow   : v1 vẫn phát output; v2 tính counterfactual decision và ghi audit
enforce  : v2 quyết định output thật; unknown/fail không được answer
```

Default khi bắt đầu implementation là `shadow`. Chỉ chuyển `enforce` sau khi đạt release gates trên validation split không dùng để thiết kế rule.

### 4.5. Submission được dựng lại từ canonical outcomes

File append trong lúc chạy là journal, không phải artifact cuối. Finalizer phải dựng lại `submission.jsonl` theo question manifest, validate toàn tập, ghi file tạm, `fsync`, atomic rename và sinh checksum.

## 5. Contract B0.5 v2 tối thiểu

Không cần một framework policy tổng quát. Contract nhỏ nhất đủ cho bài toán:

```text
GateRequestV2
├── question
├── generation
│   ├── plan_id
│   ├── metric_id
│   ├── expected_answer_type
│   └── answer_semantics
├── capability_proof
│   ├── status: supported | unsupported | ambiguous | unknown
│   ├── capability_ids[]
│   ├── missing_requirement_ids[]
│   ├── checked_source_ids[]
│   ├── catalog_version
│   └── proof_hash
├── semantic_proof
│   ├── status: pass | fail | unknown
│   ├── plan_id
│   ├── checks[]
│   ├── schema_version
│   └── rule_version
├── execution
├── attempt
└── trace

GateOutcomeV2
├── action / decision / final_answer
├── reason_code
├── validation
├── risk_assessment
│   ├── policy_version
│   ├── policy_mode
│   ├── hard_failures[]
│   ├── warnings[]
│   └── release_status: safe | unsafe | unknown
└── repair_request
```

`missing_fields` tự do từ model có thể được giữ làm diagnostic, nhưng không được dùng một mình để xác nhận `unanswerable`.

## 6. Decision matrix mục tiêu

| Điều kiện | Attempt 0 | Attempt 1/final |
|---|---|---|
| Capability `unsupported` với proof hợp lệ | `unanswerable` | `unanswerable` |
| Capability `ambiguous/unknown` | `abstain` trong enforce | `abstain` |
| Semantic proof `fail` và repairable | `retry` | `abstain` |
| Semantic proof `unknown` | shadow log / enforce abstain | `abstain` |
| `expected_answer_type` mismatch | `retry` | `abstain` |
| Repair đổi `plan_id`, metric, time window hoặc type | không chấp nhận | `abstain` |
| Execution/shape/value fail | policy retry hiện có | `abstain` khi hết retry |
| Mọi proof pass, result strict-valid, risk `safe` | `answer` | `answer` |
| Artifact không nhất quán khi finalize | fail run | không tạo submission |

Reason codes mới dự kiến:

- `CAPABILITY_PROOF_MISSING`
- `CAPABILITY_PROOF_INVALID`
- `SEMANTIC_PROOF_MISSING`
- `SEMANTIC_PROOF_FAILED`
- `ANSWER_TYPE_MISMATCH`
- `REPAIR_SEMANTICS_CHANGED`
- `RISK_NOT_RELEASED`
- `ARTIFACT_INTEGRITY_ERROR`

## 7. Dependency graph triển khai

```text
Task 1: Baseline replay harness
          │
          ▼
Task 2: Contract v2 + adapters
          │
          ├───────────────┐
          ▼               ▼
Task 3: Strict output   Task 4: Capability proof
          │               │
          └───────┬───────┘
                  ▼
          Task 5: Risk policy
                  │
                  ▼
          Task 6: Repair invariants
                  │
          ┌───────┴────────┐
          ▼                ▼
Task 7: Finalizer    Task 8: Shadow integration/release gate
          └───────────────►│
```

Task 3 và Task 4 có thể làm độc lập sau khi contract Task 2 ổn định. Task 7 có thể bắt đầu sau Task 2 nhưng phải hoàn tất trước release checkpoint cuối.

## 8. Kế hoạch triển khai theo lát cắt

### Task 1 — Khóa baseline bằng replay harness local

**Mô tả:** Tạo evaluator chỉ dùng cho development để đọc ground truth, submission, detailed logs và gate trace; tái lập score cũ và so sánh counterfactual policies. Harness không được import bởi runtime B0.5 và không chạy Modal.

**Acceptance criteria:**

- [ ] Tái lập chính xác submission `266/481/253`, score `-0,215`.
- [ ] Tái lập canonical `267/479/254`, score `-0,212`.
- [ ] Mỗi policy report số correct bị mất, wrong bị chặn, abstain và score delta; không chỉ in score cuối.

**Verification:**

- [ ] `uv run --extra dev pytest tests/test_b05_replay.py -q`
- [ ] Chạy CLI replay local trên `artifacts/runs/public_test_full`; không gọi model/Modal.
- [ ] Kiểm tra script không được import từ `src/datamate/b0/b05` hoặc pipeline runtime.

**Dependencies:** Không.
**Files dự kiến:** `scripts/analyze_b05_replay.py`, `tests/test_b05_replay.py`.
**Quy mô:** S — 2 files.
**Increment/commit gợi ý:** `test(b05): add reproducible public-run replay baseline`.

### Task 2 — Thêm contract B0.5 v2 theo hướng additive

**Mô tả:** Định nghĩa proof/risk contracts và adapter strict cho `b05.v2`, đồng thời giữ nguyên hành vi `b05.v1`. Không tích hợp decision logic trong task này.

**Acceptance criteria:**

- [ ] `b05.v1` fixtures hiện tại parse và cho output byte-compatible.
- [ ] `b05.v2` validate enum/status/version/plan ID; từ chối proof thiếu provenance hoặc sai schema.
- [ ] Field v2 vắng mặt được biểu diễn là `unknown`, không tự suy thành `pass`.

**Verification:**

- [ ] `uv run --extra dev pytest tests/test_b05_contract_v2.py tests/test_gate_e2e.py -q`
- [ ] Kiểm tra round-trip fixture v2 không làm mất check/provenance.
- [ ] Kiểm tra fixture v1 không có field mới vẫn chạy ở legacy mode.

**Dependencies:** Task 1.
**Files dự kiến:** `src/datamate/b0/b05/contracts.py`, `adapters.py`, `errors.py`, `tests/test_b05_contract_v2.py`.
**Quy mô:** M — 4 files.
**Increment/commit gợi ý:** `feat(b05): add backward-compatible proof contracts`.

### Task 3 — Làm output validation strict và bất biến

**Mô tả:** Với v2, validator không được mutate `GenerationResult.answer_type`; gate không được tự cứu `number → string/date` hoặc scalar → list. Mismatch tạo reason code rõ ràng và đi qua bounded retry/abstain.

**Acceptance criteria:**

- [ ] `validate_execution()` không sửa bất kỳ field nào trong request.
- [ ] Type/shape mismatch ở attempt 0 trả repair request; attempt 1 trả abstain.
- [ ] Một output chỉ được answer với đúng `expected_answer_type` của plan.

**Verification:**

- [ ] `uv run --extra dev pytest tests/test_b05_strict_output.py tests/test_gate_e2e.py -q`
- [ ] Regression cho CTE/table mismatch, scalar nhiều dòng và number chứa text/date.
- [ ] Hai lần gọi cùng request trả outcome giống nhau và request không đổi.

**Dependencies:** Task 2.
**Files dự kiến:** `src/datamate/b0/b05/validators.py`, `gate.py`, `tests/test_b05_strict_output.py`.
**Quy mô:** M — 3 files.
**Increment/commit gợi ý:** `fix(b05): make answer type validation strict and immutable`.

### Checkpoint A — Contract và strict output

- [ ] Tasks 1–3 hoàn thành và từng task có focused tests pass.
- [ ] Toàn bộ 36 B0.5 fixtures v1 vẫn pass ở legacy mode.
- [ ] Shadow v2 không thay đổi submission v1.
- [ ] Review contract với owner B0.2/B0.3/B0.4 trước khi tiếp tục.

### Task 4 — Thay free-form unanswerable bằng capability proof

**Mô tả:** B0.5 chỉ xác nhận `unanswerable` khi capability ID thuộc taxonomy, proof có catalog/rule version, đã kiểm đủ nguồn và status là `unsupported`. Free-form `missing_fields` không còn là proof độc lập.

**Acceptance criteria:**

- [ ] Tên dẫn xuất như `orders_in_T4_2026` không đủ tạo `unanswerable`.
- [ ] `unsupported` proof hợp lệ tạo reason từ capability taxonomy/provenance, không copy reason tùy ý của model.
- [ ] `supported`, `ambiguous`, `unknown` hoặc proof xung đột không được phát `unanswerable`.

**Verification:**

- [ ] `uv run --extra dev pytest tests/test_b05_answerability_v2.py tests/test_gate_e2e.py -q`
- [ ] Fixtures bao phủ derived metric, missing physical concept, conflict và incomplete source coverage.
- [ ] Replay report hiển thị 26 false unanswerable là upper-bound opportunity, không dùng GT trong decision code.

**Dependencies:** Task 2.
**Files dự kiến:** `src/datamate/b0/b05/answerability.py`, `adapters.py`, `tests/test_b05_answerability_v2.py`.
**Quy mô:** M — 3 files.
**Increment/commit gợi ý:** `fix(b05): require capability proof for unanswerable`.

### Task 5 — Xây deterministic risk policy với shadow mode

**Mô tả:** Thêm policy engine nhỏ nhận proof/checks và trả `safe`, `unsafe`, `unknown`. Không dùng model confidence tự khai báo, business ID hay answer-type blacklist học trực tiếp từ Public Test.

**Acceptance criteria:**

- [ ] Hard failure hoặc proof `fail` luôn là `unsafe`; proof thiếu là `unknown`.
- [ ] `shadow` ghi counterfactual decision nhưng giữ output legacy; `enforce` chỉ answer khi `safe`.
- [ ] Policy có version và mọi decision liệt kê signal/reason đã dùng.

**Verification:**

- [ ] `uv run --extra dev pytest tests/test_b05_risk_policy.py -q`
- [ ] Test decision table cho `pass/fail/unknown`, legacy/shadow/enforce.
- [ ] Cùng input + policy version luôn cho outcome deterministic.

**Dependencies:** Tasks 3 và 4.
**Files dự kiến:** `src/datamate/b0/b05/risk_policy.py`, `gate.py`, `errors.py`, `tests/test_b05_risk_policy.py`.
**Quy mô:** M — 4 files.
**Increment/commit gợi ý:** `feat(b05): add versioned shadow risk policy`.

### Task 6 — Khóa semantic invariants qua bounded retry

**Mô tả:** Repair attempt chỉ được chấp nhận nếu giữ nguyên `plan_id`, metric, expected type và các semantic fields bất biến. B0.5 vẫn giới hạn một retry như hiện tại.

**Acceptance criteria:**

- [ ] Repair đổi `plan_id`/metric/type bị chặn bằng `REPAIR_SEMANTICS_CHANGED`.
- [ ] Attempt 1 chỉ được answer khi semantic proof mới `pass` và strict validation pass.
- [ ] Không phát sinh attempt 2 hoặc vòng lặp retry.

**Verification:**

- [ ] `uv run --extra dev pytest tests/test_b05_retry_v2.py tests/test_gate_e2e.py -q`
- [ ] Test repair đúng syntax nhưng đổi metric phải abstain.
- [ ] Test repair giữ plan và pass proof được answer.

**Dependencies:** Tasks 3 và 5.
**Files dự kiến:** `src/datamate/b0/b05/retry.py`, `gate.py`, `tests/test_b05_retry_v2.py`.
**Quy mô:** M — 3 files.
**Increment/commit gợi ý:** `fix(b05): preserve semantic plan across retry`.

### Checkpoint B — Decision engine

- [ ] Tasks 4–6 hoàn thành; focused tests và `tests/test_gate_e2e.py` pass.
- [ ] Shadow mode có đầy đủ reason/risk signals nhưng không thay output.
- [ ] Không có đường code nào đổi answer type để cứu formatting.
- [ ] Owner upstream xác nhận có thể cung cấp `plan_id`, capability proof và semantic proof.

### Task 7 — Thêm canonical submission finalizer

**Mô tả:** Chuyển file append thành journal; cuối run dựng lại submission từ canonical outcomes, validate toàn tập, đối chiếu artifact và ghi atomic. Đây là lát cắt B0.5 có lợi ích đo được chắc chắn `+0,003` trên run cũ.

**Acceptance criteria:**

- [ ] Finalizer từ chối invalid type, duplicate/missing/extra ID và mismatch giữa outcome/log/submission.
- [ ] File cuối được ghi temp + flush/fsync + atomic replace; có SHA-256 manifest.
- [ ] Hai trường hợp `ubstain` và `ananswerable` bị fail trước khi tạo artifact nộp.

**Verification:**

- [ ] `uv run --extra dev pytest tests/test_b05_finalizer.py tests/test_writer.py tests/test_determinism.py -q`
- [ ] Finalize cùng canonical outcomes hai lần cho byte-identical submission/checksum.
- [ ] Replay integrity-only cho kết quả `267/479/254`, score `-0,212`.

**Dependencies:** Task 2; có thể làm song song Tasks 4–6.
**Files dự kiến:** `src/datamate/b0/b05/finalizer.py`, `writer.py`, `audit.py`, `tests/test_b05_finalizer.py`.
**Quy mô:** M — 4 files.
**Increment/commit gợi ý:** `feat(b05): finalize canonical submission atomically`.

### Task 8 — Tích hợp shadow, replay và release gate local

**Mô tả:** Nối các lát cắt thành flow B0.5 hoàn chỉnh, mở rộng audit với policy/proof summary, chạy replay local và chỉ cho phép bật enforce khi đạt quality gates. Không chạy Modal trong task này.

**Acceptance criteria:**

- [ ] Audit có policy version/mode, proof status, hard failures, legacy decision và shadow decision.
- [ ] Legacy và shadow tạo submission giống nhau; enforce fail-closed khi proof thiếu.
- [ ] Báo cáo replay phân biệt measured, upper bound và target; không ghi target như kết quả thực tế.

**Verification:**

- [ ] `uv run --extra dev pytest tests/test_gate_e2e.py tests/test_b05_*.py tests/test_b0_e2e_integration.py -q`
- [ ] `uv run --extra dev pytest -q` trước khi bàn giao.
- [ ] Chạy replay local cho `legacy`, `shadow`, `enforce`; không gọi Modal/model.

**Dependencies:** Tasks 1–7.
**Files dự kiến:** `src/datamate/b0/b05/audit.py`, `cli.py`, `gate.py`, `tests/test_b05_shadow_integration.py`, tài liệu này.
**Quy mô:** M — 5 files.
**Increment/commit gợi ý:** `feat(b05): integrate shadow policy and local release gates`.

### Checkpoint C — Sẵn sàng bàn giao

- [ ] Full local test suite pass; không cần Modal.
- [ ] V1 backward compatibility được chứng minh.
- [ ] Shadow audit đủ dữ liệu để calibrate mà không cần chain-of-thought.
- [ ] Canonical finalizer cho 0 artifact mismatch.
- [ ] Enforce chưa bật mặc định nếu upstream proof chưa đầy đủ.
- [ ] Human review/approval trước khi chuyển policy mode sang enforce.

## 9. Mục tiêu kết quả sau từng phase

| Phase | Kết quả có thể cam kết | Kết quả chưa thể cam kết |
|---|---|---|
| Task 1 | Baseline/replay tái lập tuyệt đối | Không tăng score runtime |
| Tasks 2–3 | Contract v2, không mutate type | Chưa bắt được semantic SQL sai nếu proof thiếu |
| Task 4 | Không tin free-form missing field | Precision UA ≥90% cần proof upstream và validation |
| Tasks 5–6 | Có fail-closed risk/retry gate | Score dương nếu semantic proof không đủ coverage |
| Task 7 | Loại artifact corruption; hồi cứu `-0,215 → -0,212` | Không sửa đáp án SQL sai |
| Task 8 | Shadow comparison và release gate | Chưa phải kết quả leaderboard mới |

### 9.1. Release targets cho B0.5 v2

Trước khi bật enforce trên lần chạy mới:

- Artifact integrity: **0 mismatch**, 0 invalid type, 0 duplicate/missing ID.
- Answered precision trên validation holdout: **≥65%**.
- Không slice lớn nào có precision dưới **50%**.
- Unanswerable precision: **≥90%**, recall **≥80%**.
- `unknown` proof không được answer trong enforce.
- 100% answer có policy version, plan ID và semantic proof `pass`.
- Full tests pass và v1 legacy regression không đổi.

Nếu coverage đạt 30% với precision 65%, score kỳ vọng theo luật chấm là:

```text
300 answered × (65% - 35%) / 1.000 = +0,090
```

Đây là **mục tiêu toán học**, không phải dự báo đã được đo trên run cũ. Artifact cũ thiếu proof nên không thể chứng minh B0.5 v2 sẽ đạt 65% precision bằng replay hiện tại.

## 10. Chiến lược rollout và rollback

### Giai đoạn 1 — Legacy compatibility

- Merge contract v2 nhưng default `legacy`.
- V1 fixtures và output giữ nguyên.
- Có thể rollback từng commit độc lập.

### Giai đoạn 2 — Shadow

- V1 tiếp tục phát answer.
- V2 ghi counterfactual decision và lý do.
- So sánh false block/unsafe release trên validation data.

### Giai đoạn 3 — Enforce trên validation

- Enforce chỉ trong local evaluation.
- Calibrate policy bằng validation split; Public GT chỉ dùng audit cuối.
- Nếu precision/coverage không đạt, quay lại shadow thay vì hạ quality gate.

### Giai đoạn 4 — Enforce cho submission

- Chỉ bật khi upstream proof coverage đủ và các release target đạt.
- Luôn giữ emergency mode `abstain_on_unknown=true`.
- Finalizer là bước bắt buộc trước upload.

## 11. Risks và mitigation

| Risk | Mức độ | Mitigation |
|---|---|---|
| B0.5 v2 abstain quá nhiều vì upstream chưa gửi proof | Cao | shadow trước; contract additive; đo proof coverage; không bật enforce sớm |
| Hard-code policy từ Public Test làm overfit private test | Critical | Public GT chỉ cho retrospective; calibrate trên holdout; cấm question/business lookup runtime |
| B0.5 lặp semantic logic của B0.4 và hai bên lệch nhau | Cao | B0.5 chỉ consume `SemanticProof`; contract review chung |
| Loại nhầm đáp án đúng làm score giảm | Cao | log `correct_lost/wrong_removed` trong replay; threshold ≥65%; shadow rollout |
| Contract v2 làm vỡ pipeline hiện tại | Cao | hỗ trợ v1 legacy; additive fields; focused regression sau mỗi slice |
| Writer atomic nhưng audit/submission vẫn lệch | Cao | finalizer dựng từ canonical outcomes và đối chiếu cả manifest/log/checksum |
| Retry sửa cú pháp nhưng đổi metric | Cao | khóa `plan_id`, metric, type; attempt 1 cần proof pass |
| Risk engine trở nên quá tổng quát/phức tạp | Trung bình | bắt đầu bằng deterministic decision matrix; chưa dùng ML calibration service |

## 12. Open questions cần thống nhất với team

1. B0.2 sẽ sở hữu danh sách capability ID và versioning theo format nào?
2. B0.3 có thể phát `plan_id` ổn định qua repair không?
3. B0.4 sẽ trả proof ở cấp query hay từng invariant, và mã invariant chuẩn là gì?
4. Pipeline owner sẽ gọi `SubmissionFinalizer.finalize(expected_ids)` ở đâu?
5. Validation split nào được dùng để calibrate policy mà không tái dùng Public GT?
6. Khi proof `unknown`, team muốn enforce tuyệt đối abstain hay cho phép một allowlist metric đã được template hóa?

Các câu hỏi này không chặn Tasks 1–3 và Task 7. Chúng phải được chốt trước Task 5/6 hoàn tất và trước khi bật enforce.

## 13. Definition of Done cho phần B0.5

- [ ] Tất cả 8 tasks và 3 checkpoints hoàn thành.
- [ ] Mỗi task là một increment riêng, có focused tests và commit có thể revert độc lập.
- [ ] Full test suite local pass; không cần Modal cho plan này.
- [ ] `legacy`, `shadow`, `enforce` có behavior và audit rõ ràng.
- [ ] Không còn mutation/rescue answer type trong v2.
- [ ] `unanswerable` chỉ đến từ capability proof hợp lệ.
- [ ] Mọi answer enforce có semantic proof `pass`.
- [ ] Submission finalizer bắt được hai corruption case của run cũ.
- [ ] Replay report ghi đúng baseline/canonical và phân biệt measured/upper-bound/target.
- [ ] Upstream contract được owner B0.1–B0.4 review.
- [ ] Human phê duyệt trước khi bật enforce hoặc chạy submission mới trên Modal.

## 14. Kết luận

Kết quả Public Test cho thấy B0.5 hiện tại đang xác nhận **“query chạy và output có hình dạng hợp lệ”**, trong khi cuộc thi cần xác nhận **“đáp án đủ đáng tin để chịu rủi ro -1 điểm”**.

Trong phạm vi B0.5, thứ tự ROI đúng là:

1. khóa replay baseline;
2. làm contract/proof v2 nhưng giữ backward compatibility;
3. bỏ auto-rescue type;
4. sửa answerability proof;
5. thêm shadow risk policy và khóa semantics qua retry;
6. canonicalize submission;
7. chỉ enforce sau khi đạt precision gate trên validation.

Phần có thể chứng minh ngay từ run cũ là finalizer giúp `-0,215 → -0,212`. Risk filtering có tiềm năng lớn hơn, nhưng B0.5 cần proof từ các tầng khác để chặn đủ lỗi mà không hy sinh quá nhiều câu đúng. Nếu proof chưa sẵn sàng, fail-closed có thể bảo đảm score không âm bằng cách abstain, nhưng đó là fallback an toàn chứ không phải mục tiêu cuối.
