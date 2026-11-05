# B0.5 Basic Output Gate — Implementation Report
**DataMate — Zalo AI Challenge 2026, Track 2**

## 1. Danh Sách Các File Đã Tạo / Chỉnh Sửa

| Đường dẫn file | Loại file | Mục đích / Trách nhiệm |
|---|---|---|
| `src/datamate/b05/__init__.py` | Package init | Xuất các contracts và hàm evaluate_gate, SubmissionWriter |
| `src/datamate/b05/contracts.py` | Core contracts | Dataclasses, Enums: GateRequest, GateOutcome, RepairRequest, FinalAnswer |
| `src/datamate/b05/errors.py` | Taxonomy | Mã lỗi chuẩn, taxonomy phân loại, custom exceptions |
| `src/datamate/b05/adapters.py` | Adapter | Chuẩn hóa raw dict -> GateRequest, validate ngày ISO |
| `src/datamate/b05/validators.py` | Validation | Kiểm tra shape ma trận, null, non-finite, truncated |
| `src/datamate/b05/formatter.py` | Formatter | Định dạng chuẩn 9 types, Decimal HALF_UP, NFC Unicode |
| `src/datamate/b05/retry.py` | Controller | Phân loại lỗi và điều phối One Bounded Retry (attempt 0 -> 1 -> abstain) |
| `src/datamate/b05/answerability.py` | Decision | Đánh giá unanswerable dựa trên catalog_verified proof độc lập |
| `src/datamate/b05/gate.py` | Engine | Pipeline chính: evaluate_gate(request) -> GateOutcome |
| `src/datamate/b05/audit.py` | Logger | Ghi per-question audit trace JSON với safe slug/hash |
| `src/datamate/b05/writer.py` | Writer | Ghi atomic submission.jsonl, de-duplication, flush mỗi câu |
| `src/datamate/b05/cli.py` | CLI | Runner thử nghiệm độc lập trên tệp fixtures JSONL |
| `tests/fixtures/b05_cases.jsonl` | Fixtures | 36 test cases giả lập toàn diện (T01 – T36) |
| `tests/test_contracts.py` | Test | Kiểm thử hợp đồng dữ liệu đầu vào |
| `tests/test_formatter.py` | Test | Kiểm thử định dạng 9 types |
| `tests/test_validator.py` | Test | Kiểm thử validation shape, null, truncated |
| `tests/test_error_retry.py` | Test | Kiểm thử phân loại lỗi và bounded retry |
| `tests/test_answerability.py` | Test | Kiểm thử xác thực unanswerable độc lập |
| `tests/test_writer.py` | Test | Kiểm thử writer, de-duplication, format abstain |
| `tests/test_determinism.py` | Test | Kiểm thử tính tái lập tuyệt đối (byte-by-byte) |
| `tests/test_gate_e2e.py` | Test | Kiểm thử end-to-end 36 kịch bản T01-T36 |
| `README_B05.md` | Tài liệu | Hướng dẫn sử dụng và tích hợp module |

---

## 2. Kết Quả Kiểm Thử Thực Tế

### 2.1. Kết quả chạy Pytest toàn diện
- **Lệnh thực thi**: `.venv/bin/pytest tests/ -v`
- **Kết quả**: **65 / 65 tests PASSED (100%)**
- **Thời gian chạy**: **0.07 giây**
- Không có bài test nào bị skip, xfail hay lỗi.

### 2.2. Kết quả chạy CLI Standalone với 36 Fixtures (T01 - T36)
- **Lệnh thực thi**: `PYTHONPATH=src .venv/bin/python3 -m datamate.b05.cli --fixtures tests/fixtures/b05_cases.jsonl --result-dir /tmp/b05_test_output`
- **Thống kê đầu ra**:
  - Tổng số câu hỏi: **36**
  - Số câu trả lời (Answer): **21**
  - Số câu không thể trả lời có kiểm chứng (Unanswerable): **2**
  - Số câu bỏ phiếu trắng (Abstain): **13**
  - Số lần thực hiện Bounded Retry (Attempt 0 -> 1): **5**
  - Thời gian xử lý: **0.005 giây** (tương đương ~0.14 ms / câu)
  - Submission file: **36 dòng JSONL hợp lệ, 100% đúng schema BTC**.

---

## 3. Đánh Giá Độ Ổn Định & Tính Tái Lập (Determinism)
- Module B0.5 không sử dụng bất kỳ hàm ngẫu nhiên hay phụ thuộc hệ thống nào trong quá trình đưa ra quyết định hoặc format.
- Chạy 2 lần độc lập trên cùng bộ fixtures cho ra kết quả `submission.jsonl` **trùng khớp 100% byte-by-byte** (đã được xác nhận qua `tests/test_determinism.py`).

---

## 4. Điểm Cần Thống Nhất & Phối Hợp Với B0.3 / B0.4

1. **Với B0.3 (Text-to-SQL Generator)**:
   - Thống nhất gửi kèm metadata `answer_semantics` (đặc biệt là `numeric_kind` như `count`, `money_vnd`, `average_nonmoney` và `percent_unit` như `fraction`, `percent_points`) để B0.5 làm tròn chính xác theo rulebook.
   - Khi nhận `RepairRequest`, B0.3 chỉ sửa SQL dựa trên `schema_hint` và `error_message`, không thay đổi câu hỏi hay ngữ nghĩa gốc.
2. **Với B0.4 (Safe Executor - DuckDB)**:
   - Đảm bảo trả kết quả **đầy đủ** (`truncated = False`). B0.5 tuyệt đối từ chối submit kết quả preview bị cắt.
   - Trả về mã lỗi có cấu trúc trong trường `error.type` (ví dụ `BinderException`, `ParserException`) để B0.5 phân loại chính xác thay vì chỉ phân tích chuỗi string.

