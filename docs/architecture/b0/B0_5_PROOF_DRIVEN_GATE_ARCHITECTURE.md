# Kiến trúc B0.5 Proof-Driven Output Gate

**Trạng thái:** Implemented locally, chưa chạy Modal
**Contract:** `b05.v1` (legacy) và `b05.v2` (proof-driven)
**Policy version:** `b05-risk.v1`
**Ngày cập nhật:** 2026-11-09

## 1. Mục tiêu kiến trúc

B0.5 là ranh giới phát hành cuối của baseline. Thành phần này không tự chứng minh SQL đúng nghiệp vụ; nó nhận proof có provenance từ B0.2–B0.4, kiểm tra output và quyết định một trong bốn kết quả:

- `answer`: phát hành đáp án đã qua strict validation;
- `unanswerable`: chỉ phát hành khi capability proof chứng minh thiếu dữ liệu;
- `retry`: yêu cầu đúng một lần repair có ràng buộc semantics;
- `abstain`: fail closed khi proof thiếu, sai hoặc không nhất quán.

Thiết kế giải quyết bốn lỗi chính của baseline cũ:

1. query chạy thành công nhưng chưa đủ bằng chứng để phát hành;
2. validator/formatter tự đổi answer type và che lỗi upstream;
3. repair có thể đổi metric hoặc loại đáp án;
4. submission append có thể lệch canonical outcome.

## 2. Ranh giới trách nhiệm

| Thành phần | Trách nhiệm | Dữ liệu B0.5 tiêu thụ |
|---|---|---|
| B0.1 | schema, grain và nguồn dữ liệu | gián tiếp qua catalog/proof |
| B0.2 | capability taxonomy và catalog version | `CapabilityProof` |
| B0.3 | plan, metric, expected answer type và SQL | `plan_id`, `metric_id`, `expected_answer_type` |
| B0.4 | thực thi và semantic conformance | `ExecutionResult`, `SemanticProof` |
| B0.5 | risk decision, strict formatting, retry, audit, finalization | toàn bộ contract v2 |

B0.5 không parse lại SQL AST và không dùng Public GT trong runtime policy. Điều này tránh tạo semantic validator thứ hai cạnh tranh với B0.4 và tránh overfit public test.

## 3. Luồng xử lý

```text
GateRequest
    |
    +-- b05.v1 / legacy --------------------------+
    |                                             |
    |                                  legacy validation/formatting
    |                                             |
    +-- b05.v2                                    |
          |                                       |
          +-- adapter strict                      |
          |     - plan identity                   |
          |     - proof enums/provenance          |
          |                                       |
          +-- deterministic risk policy           |
          |     - capability proof                |
          |     - semantic proof                  |
          |     - expected type                   |
          |     - repair invariants               |
          |                                       |
          +-- shadow: giữ legacy output + log counterfactual
          |
          +-- enforce: safe -> strict validator -> formatter
                         |                |
                         | fail           +-- answer/unanswerable
                         +-- retry một lần hoặc abstain
                                             |
                                             +------+
                                                    |
Canonical GateOutcome journal ----------------------+
    |
SubmissionFinalizer
    - exact question manifest
    - type/JSON/artifact consistency
    - deterministic ordering
    - temp + fsync + os.replace
    - SHA-256 manifest
```

## 4. Contract v2

### 4.1. Plan identity

`GenerationResult` bổ sung ba field bắt buộc trong `b05.v2`:

| Field | Ý nghĩa |
|---|---|
| `plan_id` | định danh plan ổn định qua retry |
| `metric_id` | metric nghiệp vụ được hỏi |
| `expected_answer_type` | loại đáp án do planner xác định, bất biến sau planning |

`answer_type` của candidate phải bằng `expected_answer_type`. B0.5 không còn đổi scalar thành list hay đổi number thành string/date trong v2.

### 4.2. Capability proof

`CapabilityProof.status` nhận `supported`, `unsupported`, `ambiguous`, `unknown`.

Một proof khác `unknown` phải có:

- `capability_ids`;
- `checked_source_ids`;
- `catalog_version`;
- `proof_hash`;
- riêng `unsupported` phải có `missing_requirement_ids`.

`unanswerable` chỉ hợp lệ khi status là `unsupported`, provenance đầy đủ và không có conflict. `EvidenceProof.missing_fields` của v1 chỉ còn là compatibility diagnostic, không đủ để phát `unanswerable` trong v2.

### 4.3. Semantic proof

`SemanticProof.status` nhận `pass`, `fail`, `unknown`. Proof khác `unknown` phải có `plan_id`, ít nhất một check, `schema_version` và `rule_version`. Mọi check trong proof `pass` cũng phải là `pass`.

Đáp án thường chỉ được release khi:

```text
capability = supported
AND semantic = pass
AND semantic.plan_id = generation.plan_id
AND candidate answer_type = expected_answer_type
AND repair invariants unchanged
AND execution/output validation passes
```

## 5. Risk policy

`risk_policy.assess_risk()` là pure deterministic function, trả:

- `safe`: đủ bằng chứng để tiếp tục;
- `unsafe`: có hard failure;
- `unknown`: thiếu proof bắt buộc.

Policy không đọc question ID, business ID, GT hay model confidence. Mọi outcome v2 mang `policy_version`, `policy_mode`, `hard_failures`, `warnings` và `release_status`.

| Signal | Release status | Enforce behavior |
|---|---|---|
| proof đầy đủ và pass | `safe` | tiếp tục strict validation |
| semantic `fail` | `unsafe` | retry ở attempt 0, abstain khi hết retry |
| expected type mismatch | `unsafe` | retry ở attempt 0, abstain khi hết retry |
| repair đổi plan/metric/type | `unsafe` | abstain ngay |
| proof vắng mặt | `unknown` | abstain |
| unsupported capability hợp lệ | `safe` | `unanswerable` |

## 6. Ba policy mode

| Mode | Contract/behavior | Mục đích |
|---|---|---|
| `legacy` | hành vi v1 | tương thích pipeline hiện tại |
| `shadow` | phát legacy outcome, ghi thêm v2 counterfactual | đo false block trước rollout |
| `enforce` | v2 quyết định output thật, unknown fail closed | release sau khi đạt quality gate |

`b05.v2` mặc định `shadow`; `b05.v1` luôn mặc định `legacy`. Pipeline B0 hiện vẫn phát v1, do đó thay đổi này chưa tự bật enforce.

## 7. Bounded retry và semantic invariants

Attempt 0 có thể tạo `RepairRequest` kèm `plan_id`, `metric_id` và `expected_answer_type`. Attempt 1 phải gửi lại `repair_origin`; B0.5 so sánh ba invariant trước khi xem execution result.

Không có attempt 2. Repair đổi semantics trả `REPAIR_SEMANTICS_CHANGED` và abstain ngay cả khi SQL mới chạy thành công.

## 8. Canonical finalization

`SubmissionWriter.write_final()` vẫn hỗ trợ journal/resume. Artifact upload phải được dựng lại bằng `SubmissionFinalizer.finalize()`:

1. nhận canonical final outcomes;
2. kiểm duplicate, missing và extra ID theo question manifest;
3. kiểm `outcome.question_id == final_answer.id`;
4. kiểm 9 answer types và JSON không chứa NaN/Infinity;
5. tùy chọn so exact với reference artifact;
6. serialize theo thứ tự manifest;
7. ghi temp, flush, `fsync`, `os.replace`;
8. ghi `submission.manifest.json` chứa SHA-256 và số record.

Finalizer bắt được cả `ubstain` và `ananswerable` trước khi tạo submission mới.

## 9. Audit và quan sát

Audit từng câu ghi thêm:

- legacy decision;
- shadow decision và reason;
- policy version/mode;
- proof/risk hard failures và warnings;
- release status.

Replay development nằm ở `scripts/analyze_b05_replay.py`, độc lập với runtime B0.5 và không gọi model/Modal.

## 10. Trade-offs và quyết định

### Chọn proof consumer thay vì parse SQL trong B0.5

Ưu điểm là ownership rõ và không nhân đôi semantic logic. Đổi lại, enforce phụ thuộc B0.2–B0.4 cung cấp proof đủ coverage.

### Chọn fail closed khi unknown

Với luật `đúng +1 / sai -1`, release một candidate không có proof có rủi ro lớn. Trade-off là coverage có thể giảm mạnh; vì vậy shadow là default của v2.

### Giữ v1 thay vì breaking migration

Contract additive cho phép nhóm khác tích hợp dần. Chi phí là phải duy trì legacy path cho đến khi pipeline chuyển hoàn toàn sang v2.

### Finalize toàn tập thay vì tin append file

Whole-run validation tốn thêm một lượt đọc/serialize nhưng chi phí nhỏ so với inference, trong khi loại được corruption và ordering nondeterminism.

## 11. Điều kiện bật enforce

Chỉ chuyển sang enforce sau khi upstream cung cấp đủ proof và validation holdout đạt:

- 0 artifact mismatch, duplicate, missing hoặc invalid type;
- answered precision ít nhất 65%;
- unanswerable precision ít nhất 90%, recall ít nhất 80%;
- 100% released answer có plan ID và semantic proof `pass`;
- full local suite xanh;
- human review trước lần chạy submission mới.

## 12. Trạng thái tích hợp

Đã hoàn tất trong B0.5: contract v2, strict adapter, risk policy, shadow/enforce dispatch, immutable validation, capability answerability, retry invariants, audit extension, finalizer, replay và tests.

Còn cần handoff từ team:

- B0.2 cung cấp capability taxonomy/version/proof hash;
- B0.3 phát plan identity ổn định;
- B0.4 phát semantic proof có version;
- pipeline chuyển request từ v1 sang v2 và chọn thời điểm bật enforce;
- chưa chạy Modal theo phạm vi yêu cầu hiện tại.
