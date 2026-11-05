# B0.5 Basic Output Gate — Hướng Dẫn Kỹ Thuật & Tích Hợp
**DataMate — Zalo AI Challenge 2026 (Track 2)**

Module **B0.5 Basic Output Gate** đóng vai trò là chốt chặn cuối cùng của Baseline B0 (Direct Text-to-SQL):
- Kiểm soát hợp đồng đầu vào (`GateRequest`) từ B0.3 (Generation) và B0.4 (Safe Execution).
- Validate kết quả truy vấn (ma trận shape, kiểu dữ liệu, NULL, non-finite NaN/Inf, truncated).
- Phân loại lỗi và điều phối cơ chế **One Bounded Retry** (tối đa 1 lần sửa lỗi SQL có cấu trúc, nếu thất bại chuyển sang `abstain`).
- Xác thực bằng chứng tin cậy cho câu hỏi không thể trả lời (`unanswerable`).
- Chuẩn hóa đầu ra theo đúng **9 official answer types** (Decimal HALF_UP, NFC Unicode, không sửa đổi ranking hay câu hỏi).
- Ghi nhận `submission.jsonl` atomic, flush theo từng câu, chống trùng lặp ID và lưu vết audit log đầy đủ (`/result/logs/*.json`).

---

## 1. Cấu Trúc Thư Mục Module

```text
src/datamate/b05/
├── __init__.py           # Exports public API
├── contracts.py          # Enums, Dataclasses, Type definitions
├── adapters.py           # Parse raw input dict -> GateRequest, validate ISO date
├── validators.py         # Shape, null, truncated, non-finite validator
├── errors.py             # Error taxonomy, standard codes, exceptions
├── retry.py              # Error classifier & 1-bounded retry state machine
├── answerability.py      # Evidence-based unanswerable decision engine
├── formatter.py          # 9 official output types formatter & NFC normalizer
├── gate.py               # Main pipeline: evaluate_gate(request) -> GateOutcome
├── writer.py             # Atomic submission.jsonl writer & de-duplicator
├── audit.py              # Per-question audit trace logger (safe filename hash)
└── cli.py                # Standalone mock CLI runner
```

---

## 2. API & Data Contracts

### 2.1. Đánh giá một câu hỏi qua Gate

```python
from datamate.b05 import evaluate_gate, GateRequest, GateAction
from datamate.b05.adapters import adapt_gate_request

# Raw request từ Orchestrator
raw_request = {
    "contract_version": "b05.v1",
    "question": {
        "id": "q_001",
        "business_id": "biz_01",
        "question": "Tháng này có bao nhiêu đơn?",
        "as_of_date": "2026-03-04"
    },
    "generation": {
        "answer_type": "number",
        "sql": "SELECT COUNT(*) FROM orders",
        "tables_used": ["orders"],
        "answer_semantics": {"numeric_kind": "count"}
    },
    "execution": {
        "status": "success",
        "columns": ["count"],
        "rows": [[125]],
        "row_count": 1,
        "truncated": False
    },
    "attempt": 0
}

req = adapt_gate_request(raw_request)
outcome = evaluate_gate(req)

if outcome.action == GateAction.RETRY:
    print("Yêu cầu B0.3 sửa SQL:", outcome.repair_request)
elif outcome.action == GateAction.FINAL:
    print("Kết quả nộp bài:", outcome.final_answer.to_submission_dict())
    # Output: {"id": "q_001", "type": "number", "answer": 125}
```

### 2.2. Ghi Submission & Audit Log

```python
from datamate.b05 import SubmissionWriter

writer = SubmissionWriter(result_dir="/result")
writer.write_final(outcome)
```

File `/result/submission.jsonl` được flush ngay lập tức, đảm bảo:
- Mỗi `question_id` chỉ có duy nhất 1 dòng cuối cùng.
- Nếu `abstain`: chỉ ghi `{"id": "...", "type": "abstain"}` (không có field `answer`).
- Nếu `unanswerable`: chỉ ghi `{"id": "...", "type": "unanswerable", "reason": "..."}`.

---

## 3. Chạy Kiểm Thử & CLI Runner

### Chạy Unit & Integration Tests (65 test cases)
```bash
.venv/bin/pytest tests/ -v
```

### Chạy CLI Runner Độc Lập Với Bộ 36 Fixtures
```bash
PYTHONPATH=src .venv/bin/python3 -m datamate.b05.cli \
    --fixtures tests/fixtures/b05_cases.jsonl \
    --result-dir /tmp/b05_run
```

