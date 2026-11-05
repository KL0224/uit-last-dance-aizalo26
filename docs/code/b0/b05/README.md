# Thư Mục Tài Liệu Kỹ Thuật Module B0.5 (Basic Output Gate)
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Vị trí:** `docs/code/b05/`

---

## 1. Mục Đích Của Thư Mục Này

Thư mục này chứa toàn bộ các bài giải thích chi tiết chuyên sâu cho **từng file mã nguồn** bên trong package `src/datamate/b05/`.

Mỗi tài liệu phân tích cặn kẽ:
* Vai trò của file trong hệ thống Gatekeeper.
* Chi tiết từng Class, Enum, Hàm và logic bên trong.
* **Tại sao lại code như vậy?** (Những cân nhắc kỹ thuật, bài toán Zalo AI Challenge).
* Ý nghĩa & ảnh hưởng liên đới đến các module khác.
* **Nếu không có nó thì sao?** (Kịch bản rủi ro, lỗi crash, mất điểm PA).

---

## 2. Sơ Đồ Tương Tác Giữa Các File (Dependency & Call Graph)

```text
                               ┌─────────────────────────────┐
                               │       contracts.py          │
                               │  (Data Schemas & Enums)     │
                               └──────────────┬──────────────┘
                                              │
                      ┌───────────────────────┼───────────────────────┐
                      ▼                       ▼                       ▼
               adapters.py               validators.py            errors.py
          (Input Guard & ISO Date)    (Shape, Null & Truncated)   (Error Taxonomy)
                      │                       │                       │
                      └───────────┬───────────┴───────────┬───────────┘
                                  ▼                       ▼
                          answerability.py            retry.py
                       (Proof vs False UA)     (Bounded Retry 1-shot)
                                  │                       │
                                  └───────────┬───────────┘
                                              ▼
                                         formatter.py
                                   (9 Types & Decimal Half-Up)
                                              │
                                              ▼
                                           gate.py
                                   (Main Evaluation Engine)
                                              │
                                  ┌───────────┴───────────┐
                                  ▼                       ▼
                              writer.py                audit.py
                        (submission.jsonl)         (/result/logs/*.json)
                                  ▲
                                  │
                                cli.py
                        (Standalone CLI Runner)
```

---

## 3. Bảng Mục Lục Các File Giải Thích Chi Tiết

| Tên file tài liệu | File mã nguồn tương ứng | Tóm tắt vai trò & Trọng tâm giải thích |
|---|---|---|
| [**`contracts.md`**](contracts.md) | `src/datamate/b05/contracts.py` | Hợp đồng dữ liệu trung tâm: 9 AnswerTypes, Dataclass `GateRequest`, `GateOutcome`, `RepairRequest`, `FinalAnswer`. |
| [**`errors.md`**](errors.md) | `src/datamate/b05/errors.py` | Phân loại lỗi chuẩn hóa (`ErrorCode`), phân biệt lỗi sửa được (retryable) và lỗi dừng ngay. Custom exceptions. |
| [**`adapters.md`**](adapters.md) | `src/datamate/b05/adapters.py` | Lớp bảo vệ cửa ngõ: Thẩm định ngày ISO lịch thực tế, validate schema, ném `ContractError` sớm nếu sai format. |
| [**`validators.md`**](validators.md) | `src/datamate/b05/validators.py` | Kiểm tra ma trận hình học: bắt `SCALAR_SHAPE_MISMATCH`, chặn kết quả preview (`truncated`), phát hiện `NULL`/`NaN`. |
| [**`retry.md`**](retry.md) | `src/datamate/b05/retry.py` | Bộ điều phối máy trạng thái Bounded Retry: tạo `RepairRequest` có cấu trúc cho B0.3, khóa cứng tối đa 1 lần retry. |
| [**`answerability.md`**](answerability.md) | `src/datamate/b05/answerability.py` | Chống phạt điểm PA (-1 điểm): Chỉ công nhận `unanswerable` khi có bằng chứng `catalog_verified` độc lập. |
| [**`formatter.md`**](formatter.md) | `src/datamate/b05/formatter.py` | Định dạng 9 types chuẩn: Số học `Decimal` `ROUND_HALF_UP`, điểm phần trăm, bảo toàn dấu tiếng Việt Unicode NFC. |
| [**`gate.py`**](gate.md) | `src/datamate/b05/gate.py` | Trái tim điều phối: Hàm `evaluate_gate()` pure-function kết nối toàn bộ logic đưa ra quyết định cuối cùng. |
| [**`writer.md`**](writer.md) | `src/datamate/b05/writer.py` | Ghi đĩa an toàn: Single writer ghi `submission.jsonl`, `flush()` ngay lập tức chống mất bài, khử trùng lặp ID. |
| [**`audit.md`**](audit.md) | `src/datamate/b05/audit.py` | Hộp đen kiểm toán: Ghi vết JSON per-question logs, bảo toàn lịch sử 2 lần thử, băm SHA-256 chống Path Traversal. |
| [**`cli.md`**](cli.md) | `src/datamate/b05/cli.py` | Giao diện dòng lệnh: Chạy thử nghiệm mock trên file fixtures JSONL độc lập mà không cần các module B0.1-B0.4. |
| [**`init.md`**](init.md) | `src/datamate/b05/__init__.py` | Giao diện xuất khẩu (Public Facade): Khai báo `__all__`, đóng gói package chuyên nghiệp và tiện dụng. |

