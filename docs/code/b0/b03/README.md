# Thư Mục Tài Liệu Kỹ Thuật Module B0.3 (Text-to-SQL LLM Layer)

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Vị trí:** `docs/code/b0/b03/`

---

## 1. Mục Đích & Phạm Vi

Thư mục này chứa toàn bộ các tài liệu giải thích chi tiết chuyên sâu cho **từng file mã nguồn** bên trong package [`src/datamate/b0/b03/`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/).

Mỗi tài liệu phân tích cặn kẽ:
* **Vai trò & Nhiệm vụ** của file trong kiến trúc Text-to-SQL Baseline B0.
* **Chi tiết từng Class, Hàm, Thuật toán** và các tham số kỹ thuật.
* **Tại sao lại thiết kế như vậy?** (Lazy import vLLM, zero GPU-lockup, JSON schema enforcement, heuristic fallback).
* **Mối liên hệ & Khả năng tương thích** với B0.1 Loader, B0.2 Context, B0.4 Executor và B0.5 Output Gate.
* **Kịch bản rủi ro nếu thiếu file này** (Lỗi import, tràn bộ nhớ VRAM, suy diễn sai định dạng, crash pipeline).

---

## 2. Danh Mục Các Tệp Mã Nguồn & Tài Liệu Chi Tiết

| Tệp Mã Nguồn | Tệp Tài Liệu Tương Ứng | Tóm Tắt Nhiệm Vụ |
|---|---|---|
| `__init__.py` | [`init.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/init.md) | Điểm công khai (Public Interface) xuất khẩu toàn bộ API lõi mà không nạp GPU runtime. |
| `base.py` | [`base.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/base.md) | Lớp trừu tượng `BaseLLM` định nghĩa hợp đồng chung cho inference engines (`load`, `chat`, `generate`, `generate_batch`). |
| `config.py` | [`config.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/config.md) | Trình đọc cấu hình TOML chuẩn Python 3.12, tự động chuẩn hóa đường dẫn weights tương đối. |
| `errors.py` | [`errors.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/errors.md) | Hệ thống ngoại lệ phân cấp (`LLMError`, `ModelLoadError`, `Text2SQLParseError`...) không phụ thuộc vLLM. |
| `generator.py` | [`generator.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/generator.md) | Lớp điều phối cấp cao `Text2SQLGenerator` kết nối LLM với Prompt Builder, Parser và Bounded Retry. |
| `inference.py` | [`inference.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/inference.md) | Kịch bản chạy mẫu minh họa hoàn chỉnh luồng Chat và Text-to-SQL với cấu hình local. |
| `parser.py` | [`parser.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/parser.md) | Bộ bóc tách JSON/SQL kiên cố (robust parser) hỗ trợ markdown code fence, regex extraction và fallback heuristics. |
| `prompt.py` | [`prompt.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/prompt.md) | Bộ tạo câu lệnh prompt chuẩn hóa từ `BusinessContext` (B0.2) và xây dựng prompt sửa lỗi cho Bounded Retry. |
| `types.py` | [`types.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/types.md) | Định nghĩa các lớp dữ liệu cốt lõi (`ChatMessage`, `GenerationOptions`, `ModelConfig`, `Text2SQLResult`). |
| `vllm_model.py` | [`vllm_model.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/vllm_model.md) | Adapter thực thi offline của vLLM với cơ chế kiểm tra manifest download và nạp weights cục bộ an toàn. |

---

## 3. Sơ Đồ Phụ Thuộc Nội Bộ Trong Module B0.3

```text
                        ┌────────────────────────┐
                        │        types.py        │
                        │  (Data Contracts / DTO)│
                        └───────────┬────────────┘
                                    │
           ┌────────────────────────┼────────────────────────┐
           ▼                        ▼                        ▼
       base.py                  prompt.py                parser.py
  (BaseLLM Interface)      (Prompt & Retry Msg)     (Robust JSON/SQL Parser)
           │                        │                        │
           ▼                        └───────────┬────────────┘
     vllm_model.py                              │
  (Offline Engine Adapter)                      ▼
           │                               generator.py
           │                           (Text2SQL Orchestrator)
           │                                    │
           └────────────────────┬───────────────┘
                                ▼
                           __init__.py
                     (Isolated Public Exports)
```

---

## 4. Tương Thích & Luồng Dữ Liệu Với Toàn Bộ Pipeline Baseline B0

```text
[B0.1 Loader]
     │ (SchemaCatalog)
     ▼
[B0.2 Context]
     │ (BusinessContext: Tables + Joins + Business Rules + Constraints)
     ▼
[B0.3 LLM Text-to-SQL]
     │ 1. prompt.build_text2sql_messages()
     │ 2. vllm_model.chat()
     │ 3. parser.parse_text2sql_response() -> Text2SQLResult
     ├───(sql query)───────────────► [B0.4 DuckDB Executor]
     │                                    │
     │                                    ▼
     │                             (Execution Result: OK or Error)
     │                                    │
     │◄──(Error Feedback for Retry)───────┤
     │                                    ▼
     └───(Text2SQLResult.to_b05_...)──► [B0.5 Output Gatekeeper]
                                          │
                                          ▼
                                     submission.jsonl
```

