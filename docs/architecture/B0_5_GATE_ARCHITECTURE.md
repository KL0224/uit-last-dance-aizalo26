# Kiến Trúc & Tài Liệu Triển Khai: B0.5 Basic Output Gate
**Dự án: DataMate — Zalo AI Challenge 2026 (Track 2)**  
**Nhóm thực hiện: UIT Last Dance**  
**Vị trí tài liệu:** `docs/code/B0_5_GATE_ARCHITECTURE.md`

---

## 1. Tổng Quan Về Module B0.5 (Basic Output Gate)

Trong hệ thống **Baseline B0 (Direct Text-to-SQL)**, module **B0.5 Basic Output Gate** đóng vai trò là chốt chặn an toàn và kiểm soát chất lượng cuối cùng trước khi ghi nhận kết quả vào tệp nộp bài (`submission.jsonl`).

```text
Question + as_of_date
          │
          ▼
B0.1 Loader ──► B0.2 Schema Context ──► B0.3 Text-to-SQL
                                          │
                                          ▼ GenerationResult
                                      B0.4 Safe Executor
                                          │
                                          ▼ ExecutionResult
                           ┌─────────────────────────────┐
                           │ B0.5 BASIC OUTPUT GATE      │
                           │ 1. Contract Adapter        │
                           │ 2. Execution Validator     │
                           │ 3. Error Classifier        │
                           │ 4. Retry Controller        │
                           │ 5. Answerability Decision  │
                           │ 6. Typed Formatter         │
                           │ 7. Writer + Audit Logger   │
                           └──────────┬────────┬─────────┘
                                      │        │
                         action=RETRY │        │ action=FINAL
                                      ▼        ▼
                           B0.3 regenerate  submission.jsonl
                              │             /result/logs/<id>.json
                              ▼
                           B0.4 execute
                              │
                              └──► B0.5 revalidate (attempt=1)
```

### Trách nhiệm cốt lõi của B0.5:
1. **Kiểm soát hợp đồng dữ liệu (Contract Enforcement)**: Tiếp nhận kết quả từ B0.3 (sinh mã SQL) và B0.4 (thực thi trên DuckDB), validate chặt chẽ theo chuẩn `GateRequest`.
2. **Xác thực hình học và giá trị (Execution & Shape Validation)**: Kiểm tra trạng thái thực thi, ma trận dòng/cột (`rows`, `columns`), phát hiện giá trị `NULL`, `NaN`, `Infinity`, và chặn các kết quả preview bị cắt (`truncated=True`).
3. **Phân loại lỗi & Điều phối Bounded Retry**: Bắt các lỗi có thể sửa chữa (`SCHEMA_ERROR`, `SQL_SYNTAX`, `SCALAR_SHAPE_MISMATCH`) để yêu cầu B0.3 sửa lại SQL với giới hạn **tối đa 1 lần retry duy nhất**.
4. **Phòng chống phạt điểm PA (Penalty Avoidance)**: Công thức chấm thi:
   $$\text{PA} = \frac{\text{Correct} - \text{Wrong}}{N}$$
   Dự đoán sai `unanswerable` bị trừ 1 điểm, trong khi `abstain` (bỏ qua) được 0 điểm. Do đó, B0.5 chỉ cho phép phát sinh `unanswerable` khi có **bằng chứng tin cậy từ catalog được kiểm chứng độc lập** (`catalog_verified`). Mọi trường hợp LLM tự nhận không trả lời được mà thiếu bằng chứng đều được chuyển thành `abstain`.
5. **Định dạng chuẩn 9 Types**: Ép kiểu nghiêm ngặt theo đúng 9 loại đáp án của BTC (bảo toàn số âm, làm tròn Decimal `ROUND_HALF_UP`, chuẩn hóa Unicode NFC, giữ nguyên dấu tiếng Việt).
6. **Lưu vết và ghi tệp tin cậy (Atomic Output & Audit Trail)**: Ghi tệp `submission.jsonl` atomic, flush từng dòng, khử trùng lặp (`de-duplication`) và lưu đầy đủ lịch sử 2 lần thử vào `/result/logs/<id>_<hash>.json`.

---

## 2. Kiến Trúc Module & Luồng Dữ Liệu Chi Tiết

Toàn bộ mã nguồn B0.5 được tổ chức theo chuẩn Clean Architecture tại `src/datamate/b05/`:

```text
src/datamate/b05/
├── __init__.py           # Export các giao diện public
├── contracts.py          # Định nghĩa cấu trúc dữ liệu, Enums (GateRequest, GateOutcome, v.v.)
├── adapters.py           # Chuẩn hóa raw dictionary -> GateRequest, validate ngày ISO
├── validators.py         # Kiểm tra tính toàn vẹn của kết quả truy vấn (shape, null, truncated)
├── errors.py             # Hệ thống mã lỗi và Custom Exceptions
├── retry.py              # Bộ phân loại lỗi và State Machine điều phối Bounded Retry
├── answerability.py      # Động cơ thẩm định câu hỏi unanswerable dựa trên bằng chứng
├── formatter.py          # Bộ chuẩn hóa 9 dạng đầu ra (Decimal HALF_UP, Unicode NFC)
├── gate.py               # Pipeline điều phối chính: evaluate_gate(request) -> GateOutcome
├── writer.py             # Quản lý ghi tệp submission.jsonl và khử trùng lặp
├── audit.py              # Ghi vết chi tiết per-question audit trace JSON
└── cli.py                # Command-line runner chạy độc lập với fixtures JSONL
```

---

## 3. Chi Tiết Triển Khai Các Thành Phần Cốt Lõi

### 3.1. Contracts & Data Schemas (`contracts.py`)
Module định nghĩa các kiểu dữ liệu có cấu trúc:
- **`AnswerType` (Enum)**: `number`, `percent`, `string`, `date`, `boolean`, `list`, `table`, `unanswerable`, `abstain`.
- **`NumericKind` (Enum)**: `count`, `money_vnd`, `average_money_vnd`, `average_nonmoney`, `quantity`, `generic`.
- **`PercentUnit` (Enum)**: `percent_points`, `fraction`.
- **`GateAction` (Enum)**: `FINAL`, `RETRY`.
- **`Decision` (Enum)**: `answer`, `unanswerable`, `abstain`, `retry`.
- **`FinalAnswer`**: Có phương thức `to_submission_dict()` đảm bảo tính tuân thủ tuyệt đối quy định BTC:
  - Khi `type == "abstain"`: Chỉ xuất `{"id": "...", "type": "abstain"}` (tuyệt đối không có trường `answer`, kể cả `null`).
  - Khi `type == "unanswerable"`: Chỉ xuất `{"id": "...", "type": "unanswerable"}` kèm trường `reason` (nếu có), không có trường `answer`.
  - Các type còn lại: Xuất `{"id": "...", "type": "...", "answer": ...}`.

### 3.2. Contract Adapter & Input Validator (`adapters.py`)
- Kiểm tra phiên bản hợp đồng: Chỉ chấp nhận `contract_version == "b05.v1"`.
- Validate nghiêm ngặt ngày `as_of_date`: Bắt buộc đúng chuẩn ISO `YYYY-MM-DD` và phải là ngày lịch hợp lệ (ví dụ: ngày `2026-02-30` lập tức bị chặn bằng `ContractError`).
- Kiểm tra chỉ số `attempt`: Chỉ chấp nhận `0` (lần đầu) hoặc `1` (lần retry).
- Chuẩn hóa các dict lồng nhau thành các đối tượng dataclass an toàn kiểu dữ liệu.

### 3.3. Execution & Shape Validator (`validators.py`)
- **Kiểm tra trạng thái**: Nếu `status == "error"` hoặc `"not_executed"`, chuyển tiếp thông tin lỗi.
- **Chặn dữ liệu preview**: Nếu `truncated == True`, lập tức từ chối với mã lỗi `TRUNCATED_RESULT`.
- **Kiểm tra hình học ma trận theo Answer Type**:
  - Đối với các kiểu vô hướng (`number`, `percent`, `string`, `date`, `boolean`): Bắt buộc chính xác **1 dòng × 1 cột**. Nếu rỗng -> `EMPTY_RESULT`; nếu nhiều hơn 1 dòng/cột -> `SCALAR_SHAPE_MISMATCH`.
  - Đối với kiểu `list`: Mỗi dòng phải có đúng 1 cột. Không cho phép rỗng trừ khi có cờ `empty_set_policy == "allowed"`.
  - Đối với kiểu `table`: Kiểm tra danh sách `columns` không rỗng và độ rộng của từng dòng trong `rows` phải bằng đúng số cột.
- **Chống ô nhiễm dữ liệu**: Bắt các giá trị `NULL`, `NaN`, `Infinity` ở mọi cấp độ cell.

### 3.4. Bounded Retry Controller (`retry.py`)
Triển khai máy trạng thái (State Machine) điều phối sửa lỗi:

```text
attempt=0
  ├─ passed + answerable ──► FINAL(answer)
  ├─ confirmed missing data ► FINAL(unanswerable)
  ├─ retryable + budget ────► RETRY(attempt=1)
  └─ otherwise ────────────► FINAL(abstain)

attempt=1
  ├─ passed + answerable ──► FINAL(answer)
  ├─ confirmed missing data ► FINAL(unanswerable)
  └─ any remaining error ──► FINAL(abstain, RETRY_EXHAUSTED)
```

- Phân loại lỗi tự động:
  - `BinderException` / `unknown table` / `column not found` ➔ `SCHEMA_ERROR` (Cho phép retry).
  - `ParserException` / `syntax error` ➔ `SQL_SYNTAX` (Cho phép retry).
  - Lỗi vi phạm bảo mật (`DROP`, `DELETE`, `UPDATE`) ➔ `SECURITY_VIOLATION` (Nghiêm cấm retry, chuyển thẳng `abstain`).
  - Hết thời gian thực thi ➔ `QUERY_TIMEOUT` (Không retry).
- Khi `attempt >= 1`, cơ chế retry bị khóa vĩnh viễn, chuyển sang `FINAL / abstain` với mã `RETRY_EXHAUSTED` để tránh rơi vào vòng lặp vô tận.

### 3.5. Evidence-Based Answerability Engine (`answerability.py`)
Bảo vệ điểm PA tối đa bằng cách chặn đứng **False Unanswerable**:
- Chỉ chấp nhận kết luận `unanswerable` khi thỏa mãn đồng thời:
  1. Nguồn bằng chứng là đáng tin cậy: `evidence.source_kind == "catalog_verified"`.
  2. Báo cáo không hỗ trợ: `evidence.capability_status == "unsupported"`.
  3. Đã duyệt toàn bộ các nguồn thay thế: `evidence.checked_all_sources == True`.
  4. Có danh sách trường bị thiếu (`missing_fields`) hoặc bằng chứng kiểm tra (`proof`).
- Nếu LLM tự tuyên bố unanswerable (`source_kind == "llm_self_claim"`), hệ thống lập tức bác bỏ và chuyển thành `abstain`.

### 3.6. Typed Output Formatter (`formatter.py`)
Định dạng chính xác 9 loại kết quả đầu ra:
- **`number`**:
  - `count`: Ép kiểu số nguyên chính xác (loại bỏ float không nguyên).
  - `money_vnd` & `average_money_vnd`: Làm tròn về đơn vị đồng VND bằng `Decimal.quantize(Decimal('1'), rounding=ROUND_HALF_UP)`.
  - `average_nonmoney`: Làm tròn 2 chữ số thập phân (`Decimal('0.01')`, `ROUND_HALF_UP`).
- **`percent`**:
  - Đưa về điểm phần trăm (percentage points, ví dụ: `-12.45` biểu thị `-12.45%`).
  - Xử lý giá trị `-0.004` làm tròn về `0` (tránh sinh ra `-0.0`).
- **`string`**: Chuẩn hóa Unicode NFC, cắt khoảng trắng thừa, **bảo toàn 100% chữ hoa/thường và dấu tiếng Việt**.
- **`date`**: Kiểm tra ngày lịch ISO `YYYY-MM-DD` hoặc `YYYY-MM` (đối với câu hỏi tháng).
- **`boolean`**: JSON boolean `true` / `false` thuần túy (không chấp nhận số nguyên 1/0).
- **`list`**: Giữ nguyên thứ tự truy vấn ban đầu (tuyệt đối không tự ý sort lại list).
- **`table`**: Kiểm tra cấu trúc `{"columns": [...], "rows": [...]}` không đổi thứ tự.
- **`normalize_match_key()`**: Hàm tiện ích nội bộ (NFC -> lowercase -> xóa ký tự đặc biệt) dùng cho việc đánh giá Local CV, không can thiệp vào chuỗi gửi nộp.

### 3.7. Persistent Writer & Audit Logger (`writer.py` & `audit.py`)
- **SubmissionWriter**:
  - Ghi tệp `/result/submission.jsonl` theo từng câu và gọi `.flush()` ngay lập tức để chống mất bài thi khi hết giờ hoặc sập nguồn.
  - Tự động quét các `question.id` đã ghi trước đó khi chạy tiếp (resume capability) để khử trùng lặp (de-duplication).
- **AuditLogger**:
  - Ghi tệp `/result/logs/<slug>_<sha256_hash>.json` cho từng câu hỏi.
  - Sử dụng mã băm SHA-256 kết hợp slug an toàn để triệt tiêu nguy cơ tấn công Path Traversal.
  - Lưu giữ đầy đủ thông tin của cả 2 lượt thực thi (`attempts: [attempt_0, attempt_1]`), không ghi đè vết lỗi cũ.

---

## 4. Ma Trận Kiểm Thử 36 Ca Thực Nghiệm (T01 – T36)

Toàn bộ 36 ca kiểm thử tổng hợp (synthetic cases) được xây dựng tại `tests/fixtures/b05_cases.jsonl` và kiểm chứng tự động qua `tests/test_gate_e2e.py`:

| Mã Test | Điều kiện đầu vào | Hành vi mong đợi | Kết quả kiểm thử thực tế |
|---|---|---|:---:|
| **T01** | `number/count`, rows `[[125]]` | FINAL, number `125` | **PASSED** |
| **T02** | `number/money_vnd`, rows `[[1250000.5]]` | FINAL, number `1250001` (HALF_UP) | **PASSED** |
| **T03** | `number/average_nonmoney`, `[[12.345]]` | FINAL, number `12.35` | **PASSED** |
| **T04** | `percent/percent_points`, `[[-12.445]]` | FINAL, percent `-12.45` | **PASSED** |
| **T05** | `percent/fraction`, `[[0.125]]` | FINAL, percent `12.5` | **PASSED** |
| **T06** | `string`, `[["  Cà phê sữa  "]]` | FINAL, string `"Cà phê sữa"` | **PASSED** |
| **T07** | `date`, `[["2026-02-28"]]` | FINAL, date `"2026-02-28"` | **PASSED** |
| **T08** | month question, `[["2026-03"]]` | FINAL, date `"2026-03"` | **PASSED** |
| **T09** | `boolean`, `[[true]]` | FINAL, boolean `true` | **PASSED** |
| **T10** | ordered `list`, rows `[["A"], ["B"]]` | FINAL, list `["A", "B"]` | **PASSED** |
| **T11** | `table`, 2 cols × 2 rows | FINAL, cấu trúc bảng đầy đủ | **PASSED** |
| **T12** | `number/count`, `[[0]]` | FINAL, number `0` | **PASSED** |
| **T13** | `number`, `[[null]]` | FINAL, abstain (`NULL_RESULT`) | **PASSED** |
| **T14** | scalar number, `[]` (rỗng) | FINAL, abstain (`EMPTY_RESULT`) | **PASSED** |
| **T15** | scalar number, `[[1],[2]]`, attempt 0 | RETRY (`SCALAR_SHAPE_MISMATCH`) | **PASSED** |
| **T16** | scalar number, `[[1],[2]]`, attempt 1 | FINAL, abstain (`RETRY_EXHAUSTED`) | **PASSED** |
| **T17** | `BinderException`, attempt 0 | RETRY (`SCHEMA_ERROR`) | **PASSED** |
| **T18** | `BinderException`, attempt 1 | FINAL, abstain (`RETRY_EXHAUSTED`) | **PASSED** |
| **T19** | `ParserException`, attempt 0 | RETRY (`SQL_SYNTAX`) | **PASSED** |
| **T20** | `SECURITY_VIOLATION` (`DROP TABLE`) | FINAL, abstain (cấm retry bảo mật) | **PASSED** |
| **T21** | `QUERY_TIMEOUT` | FINAL, abstain (`QUERY_TIMEOUT`) | **PASSED** |
| **T22** | boolean với giá trị nguyên `[[1]]` | RETRY (`OUTPUT_TYPE_ERROR`) | **PASSED** |
| **T23** | giá trị chứa NaN/Inf | RETRY (`OUTPUT_TYPE_ERROR`) | **PASSED** |
| **T24** | list/table có `truncated=true` | FINAL, abstain (`TRUNCATED_RESULT`) | **PASSED** |
| **T25** | proof unsupported + checked all sources | FINAL, `unanswerable` hợp lệ | **PASSED** |
| **T26** | LLM tự xưng unanswerable (không proof) | FINAL, abstain (`MISSING_EVIDENCE`) | **PASSED** |
| **T27** | ngày sai lịch `as_of_date=2026-02-30` | FINAL, abstain (`CONTRACT_ERROR`) | **PASSED** |
| **T28** | list giữ đúng thứ tự `["B", "A"]` | FINAL, list `["B", "A"]` | **PASSED** |
| **T29** | ghi trùng lặp cùng question ID | Writer tự lọc, chỉ ghi đúng 1 dòng | **PASSED** |
| **T30** | chạy lại 2 lần độc lập | Output giống nhau 100% byte-by-byte | **PASSED** |
| **T31** | `not_executed` + confirmed proof | FINAL, `unanswerable` hợp lệ | **PASSED** |
| **T32** | kiểu answer_type lạ không hỗ trợ | FINAL, abstain (`CONTRACT_ERROR`) | **PASSED** |
| **T33** | cảnh báo join fanout được ghi nhận | Warnings lưu đầy đủ trong audit log | **PASSED** |
| **T34** | table row thiếu cell so với số cột | FINAL, abstain (`TABLE_SHAPE_ERROR`) | **PASSED** |
| **T35** | list rỗng nhưng có `empty_set_policy=allowed` | FINAL, list rỗng `[]` hợp lệ | **PASSED** |
| **T36** | percent âm `-0.004` làm tròn 2dp | FINAL, percent `0` (không sinh `-0.0`) | **PASSED** |

---

## 5. Kết Quả Kiểm Thử Toàn Diện (Pytest & Performance)

```bash
$ .venv/bin/pytest tests/ -v
============================== 65 passed in 0.07s ==============================
```

- **Tổng số tests**: 65 bài kiểm thử đơn vị và tích hợp.
- **Tỷ lệ vượt qua**: **100% (65/65 passed)**.
- **Thời gian xử lý trung bình qua CLI**: **~0.14 ms / câu hỏi**, hoàn toàn không tạo ra bất kỳ độ trễ nghẽn (bottleneck) nào cho pipeline tổng thể (giới hạn bài thi là 6 giờ).

---

## 6. Hướng Dẫn Tích Hợp Module Vào Pipeline Toàn Dự Án

### 6.1. Gọi trực tiếp từ Pipeline Orchestrator

```python
from datamate.b05 import evaluate_gate, GateAction, SubmissionWriter
from datamate.b05.adapters import adapt_gate_request

writer = SubmissionWriter(result_dir="/result")

# Vòng lặp duyệt từng câu hỏi
for question in questions:
    # 1. Gọi B0.3 sinh SQL và B0.4 thực thi
    gen_result, exec_result = run_b03_and_b04(question, attempt=0)

    # 2. Đóng gói request đưa vào B0.5
    raw_req = {
        "contract_version": "b05.v1",
        "question": question.to_dict(),
        "generation": gen_result.to_dict(),
        "execution": exec_result.to_dict(),
        "attempt": 0
    }
    gate_req = adapt_gate_request(raw_req)
    outcome = evaluate_gate(gate_req)

    # 3. Xử lý Bounded Retry nếu có yêu cầu
    if outcome.action == GateAction.RETRY:
        # Gọi B0.3 sửa SQL theo repair_request
        gen_repaired, exec_repaired = run_b03_and_b04(
            question, 
            attempt=1, 
            repair_request=outcome.repair_request
        )
        raw_req["generation"] = gen_repaired.to_dict()
        raw_req["execution"] = exec_repaired.to_dict()
        raw_req["attempt"] = 1
        
        gate_req_attempt1 = adapt_gate_request(raw_req)
        outcome = evaluate_gate(gate_req_attempt1)

    # 4. Ghi kết quả cuối cùng (Chỉ ghi khi action == FINAL)
    writer.write_final(outcome, trace_meta={"business_id": question.business_id})
```

### 6.2. Chạy thử nghiệm CLI độc lập

```bash
# Thiết lập PYTHONPATH và chạy runner với file mock fixtures
PYTHONPATH=src .venv/bin/python3 -m datamate.b05.cli \
    --fixtures tests/fixtures/b05_cases.jsonl \
    --result-dir /result
```

Tệp kết quả sẽ xuất hiện tại `/result/submission.jsonl` và các bản ghi chi tiết tại `/result/logs/`.

