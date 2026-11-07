# Thư Mục Tài Liệu Kỹ Thuật Module B0.4 (DuckDB Read-Only Execution Engine)

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Vị trí:** `docs/code/b0/b04/`

---

## 1. Mục Đích & Phạm Vi

Thư mục này chứa toàn bộ các tài liệu giải thích chi tiết chuyên sâu cho **từng file mã nguồn** bên trong package [`src/datamate/b0/b04/`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/).

Mỗi tài liệu phân tích cặn kẽ:
* **Vai trò & Nhiệm vụ** của file trong kiến trúc thực thi cơ sở dữ liệu Baseline B0.
* **Chi tiết từng Class, Hàm, Thuật toán bảo mật** và cơ chế sandbox.
* **Tại sao lại thiết kế như vậy?** (Kiểm tra AST trước khi chạy, chặn Multi-statement Injection, cơ chế ngắt timer thread hard interrupt, khóa cấu hình DuckDB).
* **Mối liên hệ & Khả năng tương thích** với B0.1 Loader, B0.2 Context, B0.3 LLM và B0.5 Output Gate.
* **Kịch bản rủi ro nếu thiếu file này** (Rò rỉ file hệ thống, treo CPU do vòng lặp vô tận, tràn RAM, crash format JSON).

---

## 2. Danh Mục Các Tệp Mã Nguồn & Tài Liệu Chi Tiết

| Tệp Mã Nguồn | Tệp Tài Liệu Tương Ứng | Tóm Tắt Nhiệm Vụ |
|---|---|---|
| `__init__.py` | [`init.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/init.md) | Điểm công khai (Public Interface) xuất khẩu các lớp dữ liệu và hàm thực thi lõi của B0.4. |
| `schemas.py` | [`schemas.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/schemas.md) | Định nghĩa các DTO Pydantic (`ExecutionRequest`, `ExecutionResponse`), chuẩn hóa giá trị Python (`normalize_value`) và adapter kết nối B0.3/B0.5. |
| `sanitizer.py` | [`sanitizer.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/sanitizer.md) | Bộ phân tích cú pháp tĩnh AST bằng `sqlglot`, gỡ bỏ markdown code block, cấm DDL/DML, cấm đọc file tùy tiện và chặn Multi-statement injection. |
| `error_handler.py` | [`error_handler.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/error_handler.md) | Phân loại ngoại lệ DuckDB/Python, quyết định điều hướng (`yes`, `recoverable`, `abstain`), và tinh gọn error message cho Bounded Retry. |
| `engine.py` | [`engine.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/engine.md) | Trình thực thi truy vấn an toàn: kết nối file/memory/folder, thiết lập giới hạn RAM/threads, luồng timer ngắt timeout (`con.interrupt()`), và giới hạn `max_rows`. |
| Kế hoạch nâng cấp B0.4 | [`improvement_execute_layer_plan.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/improvement_execute_layer_plan.md) | Kế hoạch nâng cấp tầng thực thi B0.4 (xử lý AST/regex, `temp_directory` Docker Read-Only, Schema Hint cho Bounded Retry, kiểm tra kết quả rỗng/NULL, cache thư mục) & quy trình đóng gói Docker + Modal.ai. |
| Quy trình các bước tiếp theo | [`EXECUTION_UPGRADE_ROADMAP.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/EXECUTION_UPGRADE_ROADMAP.md) | Sơ đồ & lộ trình tổng thể 6 giai đoạn từ nâng cấp code B0.4, benchmark đối đầu, build Docker đến chạy Modal GPU. |
| Hướng dẫn thực hành chi tiết | [`USER_TESTING_GUIDE.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/USER_TESTING_GUIDE.md) | Cẩm nang hướng dẫn chi tiết từng lệnh: chạy benchmark so sánh, chạy pytest, build/test Docker offline, chạy Modal GPU và giải nén dữ liệu. |

---

## 3. Sơ Đồ Phụ Thuộc Nội Bộ Trong Module B0.4

```text
                        ┌────────────────────────┐
                        │       schemas.py       │
                        │ (Pydantic DTOs & Types)│
                        └───────────┬────────────┘
                                    │
           ┌────────────────────────┼────────────────────────┐
           ▼                                                 ▼
      sanitizer.py                                    error_handler.py
 (AST Static Analysis &                           (Error Classification &
  Read-only Sanitization)                          Route Determination)
           │                                                 │
           └────────────────────────┬────────────────────────┘
                                    ▼
                                engine.py
                      (Sandboxed Execution Core)
                                    │
                                    ▼
                               __init__.py
                         (Public Package Exports)
```

---

## 4. Tương Thích & Luồng Dữ Liệu Trong Baseline B0

```text
[B0.3 LLM Text-to-SQL]
     │
     │ Text2SQLResult (sql, answer_type)
     ▼
[B0.4 DuckDB Executor]
     │ 1. ExecutionRequest.from_b03()
     │ 2. sanitizer.validate_read_only_sql()
     │ 3. engine.execute_query() [Timeout Timer + DuckDB Sandbox]
     │ 4. error_handler.classify_error() & determine_route()
     │
     ├───(Nếu route == 'recoverable' & retry_count < 1)───► [Quay lại B0.3 Bounded Retry]
     │
     │ ExecutionResponse.to_b05_execution_result()
     ▼
[B0.5 Basic Output Gate] ──► Kiểm duyệt 9 types, Format & Xuất JSONL
```

