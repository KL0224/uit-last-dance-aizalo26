# DataMate AI Agent Pipeline Architecture

> **Dự án**: AI Zalo Challenge 2026 — Track 2 (DataMate)  
> **Đội thi**: UIT Last Dance  
> **Phiên bản thiết kế**: 11/11/2026  
> **Mục tiêu**: Vietnamese Tabular Question Answering & Semantic Data Pipeline

---

## 1. Tổng quan kiến trúc (Architecture Overview)

Kiến trúc hệ thống DataMate AI Agent được thiết kế theo mô hình **2 Pha — 7 Thành phần — 1 Hệ thống đo lường xuyên suốt**, bám sát đặc tả kỹ thuật tại `temp/Zalo_AI_Challenge_2026_Track2_Kien_truc_AI_Agent.docx` và kế hoạch tích hợp module `temp/CAPABILITY_MAP.md`.

Nguyên tắc cốt lõi:
- **LLM hiểu ngữ nghĩa và lập kế hoạch**: LLM tập trung ở khâu hiểu ngữ nghĩa phức tạp (Grounding C) và lập kế hoạch truy vấn (Planner D).
- **Code thực thi tính toán xác định**: DuckDB Sandbox thực thi tính toán chính xác, ngăn ngừa việc LLM tự tính nhẩm sai số học.
- **Bằng chứng dữ liệu quyết định khả năng trả lời**: Chỉ kết luận `unanswerable` khi có chứng cứ thiếu dữ liệu được kiểm chứng độc lập từ schema/catalog, tối ưu điểm Penalized Accuracy (PA).

```text
===================================================================================================
 PHA 1: BUSINESS PREPARATION (Chạy 1 lần duy nhất cho mỗi doanh nghiệp)
===================================================================================================
 [Dữ liệu thô: CSV / XLSX / SQLite + README + Calendar]
        │
        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ A. Data Foundation (datamate.ingestion)                     │
 │    - Quét file, suy luận kiểu, grain, chuẩn hóa số/ngày     │
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ B. Semantic Knowledge (datamate.context)                    │
 │    - Schema graph, metric registry, rulebook, calendar âm   │
 └──────────────────────────────┬──────────────────────────────┘
                                │
                                ▼
         [Business Context Package: DuckDB + business_context.json]
                                │ (tham chiếu ngữ cảnh cho Pha 2)
                                │
================================│==================================================================
 PHA 2: QUESTION INFERENCE (Xử lý từng câu hỏi độc lập)
================================│==================================================================
 [Câu hỏi tiếng Việt + as_of_date]
        │
        ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ C. Question Grounding (datamate.grounding)                  │
 │    - C1: Intent & phép toán (SUM, COUNT, TOP_K...)          │
 │    - C2: Phân giải thời gian dựa theo as_of_date            │
 │    - C3: Chọn bảng, cột, đường đi JOIN chống fanout         │
 │    - C4: So khớp giá trị thực thể với DB                    │
 │    - C5: Answerability Precheck (Kiểm tra bằng chứng)       │
 └──────────────────────────────┬──────────────────────────────┘
                                │
                 [C5: Bằng chứng thiếu dữ liệu?]
                 /                             \
     (UNSUPPORTED xác nhận)              (SUPPORTED / UNKNOWN)
               /                                         \
              ▼                                           ▼
 ┌───────────────────────────┐         ┌─────────────────────────────────────────────────┐
 │ Fast-Path Unanswerable    │         │ Grounding Hints (Intent, Time, Joins, Values)   │
 │ (Bypass LLM & DuckDB)     │         └────────────────────────┬────────────────────────┘
 └────────────┬──────────────┘                                  │
              │                                                 ▼
              │                        ┌─────────────────────────────────────────────────┐
              │                        │ D. Agent Planner (datamate.planner)             │
              │                        │    - Text-to-SQL Generator (DuckDB SQL có kiểu) │
              │                        └────────────────────────┬────────────────────────┘
              │                                                 │
              │                                                 ▼
              │                        ┌─────────────────────────────────────────────────┐
              │                        │ E. Safe Execution (datamate.execution)          │
              │                        │    - DuckDB Read-Only sandbox (timeout 10s)     │
              │                        └────────────────────────┬────────────────────────┘
              │                                                 │
              │                                                 ▼
              │                        ┌─────────────────────────────────────────────────┐
              │                        │ F. Verification & Error Recovery (datamate.gate)│
              │                        │    - Kiểm định kiểu dữ liệu và cú pháp SQL      │
              │                        └───────┬─────────────────────────────────▲───────┘
              │                                │                                 │
              │                (Lỗi có thể sửa & attempt=0)            (Thực thi lại query)
              │                                │                                 │
              │                                ▼                                 │
              │                     [Bounded Repair: Tối đa 1 lần] ──────────────┘
              │                                │
              │                 (Thành công hoặc hết lượt retry)
              │                                │
              ▼                                ▼
 ┌─────────────────────────────────────────────────────────────┐
 │ G. Decision & Output Gate (datamate.gate)                   │
 │    - Đánh giá bằng chứng, phân biệt Unanswerable / Abstain  │
 │    - Typed Formatter: Chuẩn hóa 1 trong 9 answer types      │
 └──────────────────────────────┬──────────────────────────────┘
                                │
================================│==================================================================
 H. TELEMETRY & OBSERVABILITY (Ghi nhận vết thực thi & kết quả)
================================│==================================================================
                                ▼
 ├── submission.jsonl      : Định dạng nộp bài chính thức (id, type, answer)
 ├── detailed_logs.jsonl   : Log chi tiết các lần thử, SQL, suy nghĩ <think>, lỗi DB
 ├── grounding_trace.jsonl : Vết phân tích của C1-C5 (coverage, intent, primary table)
 └── logs/<id>.json        : File kiểm toán chi tiết riêng cho từng câu hỏi
```

---

## 2. Bảng chuyển đổi định danh (Architecture Naming Migration)

Nhằm chuẩn hóa mã nguồn theo đúng vai trò kiến trúc thay vì các tên mã baseline tạm thời (`B0`, `B0.1`–`B0.5`), toàn bộ codebase đã được di chuyển sang định danh chính thức:

| Khối kiến trúc | Module Python | Tên lớp canonical mới | Định danh legacy (shim tương thích) | Trách nhiệm chính |
|---|---|---|---|---|
| **A. Data Foundation** | `datamate.ingestion` | `prepare_business` | `B0.1 Loader` | Khảo sát file, đọc bảng, suy luận grain/kiểu, chuẩn hóa số/ngày, DuckDB store |
| **B. Semantic Knowledge** | `datamate.context` | `BusinessContextRuntimeLoader`, `BusinessRuntimeContext` | `B0.2 Context` | Graph quan hệ bảng, từ điển chỉ số, Rulebook catalog, bảng lịch âm |
| **C. Question Grounding** | `datamate.grounding` | `QuestionGroundingRuntime`, `BusinessContextAdapter` | `B02ContextAdapter` | Phân tích intent (C1), ngày (C2), schema (C3), giá trị (C4), kiểm tra dữ liệu (C5) |
| **D. Agent Planner** | `datamate.planner` | `Text2SQLGenerator`, `build_text2sql_messages` | `B0.3 Text-to-SQL` | Chuyển câu hỏi kèm Grounding hints thành DuckDB SQL có kiểu |
| **E. Safe Execution** | `datamate.execution` | `execute_query`, `ExecutionRequest` | `B0.4 Executor` | Chạy DuckDB read-only sandbox, kiểm soát timeout/max_rows, grain aggregation |
| **F/G. Gate & Decision** | `datamate.gate` | `evaluate_gate`, `GateRequest` | `B0.5 Basic Output Gate` | Xác minh kết quả, phân loại lỗi, Bounded Retry, định dạng 9 answer types |
| **Orchestrator** | `datamate.pipeline` | `DataMatePipeline` | `B0Pipeline`, `Pipeline` | Điều phối toàn bộ luồng, hỗ trợ batch GPU, fast-path và telemetry |
| **Local Runner** | `scripts` | `scripts/run_pipeline.py` | *(Đã loại bỏ script b0 cũ)* | CLI chính thức chạy local/server có cờ `--enable-grounding`, `--batch-size` |
| **Modal GPU Runner** | `scripts` | `scripts/modal_run_pipeline.py` | *(Đã loại bỏ script b0 cũ)* | Serverless GPU runner chính thức chạy phân tán trên Modal A100 |

---

## 3. Cơ chế hoạt động chi tiết từng giai đoạn

### 3.1. Context Loading Đa Góc Nhìn (Multi-View)
Lớp `BusinessContextRuntimeLoader` nạp dữ liệu một lần từ thư mục bundle của doanh nghiệp:
- `planner_context`: Định dạng dictionary tối ưu để sinh prompt cho LLM.
- `grounding_context`: Triển khai giao diện `BusinessContextProtocol` cho Grounding Engine C1–C5 truy cập metadata định kiểu nghiêm ngặt (bảng, cột, vai trò tiền tệ, ngày bao phủ, quan hệ khóa, metric registry).

### 3.2. Question Grounding & Fast-Path Answerability
Khi câu hỏi được đưa vào:
1. `QuestionGroundingRuntime.ground_question()` chạy C1–C5:
   - **C1 Intent Parser**: Xác định thao tác (SUM, COUNT, LOOKUP, TOP_K, PERCENT_CHANGE...).
   - **C2 Temporal Resolver**: Biến các mốc thời gian tiếng Việt ("hôm nay", "hôm qua", "tháng trước", "Tết âm lịch") thành khoảng ngày cụ thể dựa trên `as_of_date`.
   - **C3 Schema Grounder**: Xác định bảng trọng tâm, các cột liên quan, và đường đi JOIN tối ưu kèm cảnh báo fanout.
   - **C4 Value Grounder**: So khớp thực thể trong câu hỏi với giá trị thực tế trong DB.
   - **C5 Answerability Precheck**: Đối chiếu yêu cầu chỉ số với Capability Matrix.
2. **Fast-Path rẽ nhánh**:
   - Nếu câu hỏi yêu cầu dữ liệu mà doanh nghiệp xác nhận không có (ví dụ: đòi hỏi giá vốn nhưng catalog không có chi phí) $\rightarrow$ `grounded.is_directly_unanswerable = True`.
   - Hệ thống lập tức chuyển thẳng sang Output Gate trả kết quả `unanswerable`, **bỏ qua hoàn toàn LLM Planner và DuckDB Execution**, tiết kiệm token, giảm latency xuống 0ms và loại bỏ hoàn toàn rủi ro LLM bịa SQL ảo.

### 3.3. Grounded Hints cho Text-to-SQL Planner
Nếu câu hỏi hợp lệ hoặc cần kiểm tra thêm (`SUPPORTED` hoặc `UNKNOWN`):
- `GroundingToPlannerAdapter.format_grounded_hint_for_planner(grounded)` sinh ra đoạn cấu trúc Markdown bổ trợ vào prompt của `Text2SQLGenerator`.
- Prompt cung cấp chính xác: phép toán kỳ vọng, bảng đích, gợi ý điều kiện JOIN `ON left.id = right.id`, khoảng ngày `start_date` đến `end_date`, và giá trị DB đã so khớp (ví dụ: `ca tối -> shift = 'toi'`).

### 3.4. Safe Execution & Verification Gate
- Truy vấn được thực thi trên DuckDB in-memory/read-only với timeout (10s) và giới hạn dòng (10.000 dòng).
- Kết quả đi qua `evaluate_gate(GateRequest)`:
  - Nếu kết quả rỗng do bảng không có dữ liệu hoặc sai cú pháp $\rightarrow$ Gate phát sinh `RepairRequest`.
  - Pipeline kích hoạt **Bounded Retry** (tối đa 1 lần duy nhất), gửi lỗi và hướng dẫn sửa lại cho Planner kèm Grounding hints ban đầu.
  - Sau lần retry hoặc nếu gặp lỗi nghiêm trọng, hệ thống chọn `abstain` thay vì đoán bừa để tối ưu điểm Penalized Accuracy ($PA$).

### 3.5. Telemetry & Ghi nhận vết thực thi
Mỗi câu hỏi hoàn thành được ghi nhận vào 4 kênh đầu ra độc lập:
1. `submission.jsonl`: File nộp bài chính thức theo chuẩn BTC (`{"id": ..., "type": ..., "answer": ...}`).
2. `detailed_logs.jsonl`: Chi tiết từng lượt thực thi, SQL, lỗi DuckDB, suy nghĩ `<think>...</think>`.
3. `grounding_trace.jsonl`: Vết phân tích Grounding (intent, thời gian, schema, coverage).
4. `logs/<id>.json`: File kiểm toán riêng biệt cho từng câu.

---

## 4. Kết quả kiểm thử & Nghiệm thu (Test Verification Report)

Toàn bộ test suite được kiểm thử nghiêm ngặt trong môi trường ảo `.venv` bằng công cụ `pytest`.

### 4.1. Báo cáo tổng thể
- **Tổng số ca kiểm thử**: **417 passed**, 3 skipped, 15 subtests passed.
- **Thời gian chạy toàn bộ**: **12.21 giây**.
- **Tỷ lệ vượt qua**: **100%** không có lỗi hoặc cảnh báo hồi quy (zero regressions).

### 4.2. Bảng phân rã kết quả theo module kiểm thử

| Nhóm module kiểm thử | Tệp test chính | Số ca test | Trạng thái | Nội dung kiểm thử |
|---|---|:---:|:---:|---|
| **Pipeline & State Machine** | `tests/test_datamate_pipeline.py` | 5 | PASSED | Fast-path unanswerable, hint injection, toggle grounding, batch inference GPU, telemetry |
| **Grounded Planner Bridge** | `tests/test_grounded_planner_bridge.py` | 5 | PASSED | Naming aliases, tích hợp prompt hint, generator single & batch options |
| **Question Grounding Core** | `tests/grounding/` (8 suites) | 70 | PASSED | Intent parser, temporal resolver, schema grounder, value matcher, answerability precheck |
| **Context Runtime Boundary** | `tests/test_business_context_runtime.py` | 13 | PASSED | Context loader, protocol validation, cache isolation, join discovery |
| **End-to-End Orchestration** | `tests/test_b0_e2e_integration.py` | 5 | PASSED | Luồng end-to-end hoàn chỉnh, bounded retry, catalog-verified unanswerable |
| **Planner & Text-to-SQL** | `tests/test_b03_text2sql.py` | 16 | PASSED | Cú pháp DuckDB, CTE, xử lý tiếng Việt, thinking token budget |
| **Safe Executor Engine** | `tests/test_b0_4_executor.py` | 27 | PASSED | Read-only sandbox, timeout protection, max_rows truncation, sanitization |
| **Gate, Retry & Formatter** | `tests/test_gate_e2e.py`, `test_formatter.py`, `test_validator.py` | 64 | PASSED | Kiểm định 9 answer types, phân loại lỗi retry, rủi ro sửa sai ngữ nghĩa |
| **Modular Imports & Compatibility** | `tests/test_modular_imports.py`, `tests/test_b01_b02_modular_imports.py` | 17 | PASSED | Kiểm tra alias canonical và tương thích ngược của tất cả module |
| **Data Ingestion & Joins** | `tests/test_ingestion.py`, `tests/test_downstream_join_graph.py` | 195 | PASSED | Chuẩn hóa CSV/Excel, suy luận khóa, schema mapping, tránh fanout |

### 4.3. Xác nhận tính toàn vẹn mã nguồn
- `python -m compileall -q src scripts main.py`: **Pass** (0 lỗi cú pháp).
- `git diff --check`: **Clean** (không có trailing whitespace hoặc lỗi định dạng).
- Kiểm tra độc lập: `QuestionGroundingRuntime` hoàn toàn không phụ thuộc ngược vào `Pipeline`, `Planner` hay `Gate`.

---

## 5. Hướng dẫn vận hành Pipeline (Usage & Runbook)

### 5.1. Chạy trên máy trạm Local / Server
```bash
# Kích hoạt môi trường ảo
source .venv/bin/activate

# 1. Chạy thử nghiệm 10 câu hỏi với chế độ sinh suy luận thinking
python scripts/run_pipeline.py \
    --split-dir data/train \
    --output-dir artifacts/runs/train_sample_10 \
    --limit 10 \
    --enable-thinking

# 2. Chạy thử nghiệm riêng cho một doanh nghiệp cụ thể (ví dụ biz_105)
python scripts/run_pipeline.py \
    --split-dir data/train \
    --output-dir artifacts/runs/train_biz105 \
    --business-id biz_105

# 3. Chạy A/B testing tắt Grounding (chạy luồng legacy)
python scripts/run_pipeline.py \
    --split-dir data/train \
    --output-dir artifacts/runs/train_no_grounding \
    --no-enable-grounding \
    --limit 20
```

### 5.2. Chạy trên Serverless GPU Modal (A100 40GB - Dual LLM Models)
Hệ thống hỗ trợ nạp đồng thời cả 2 mô hình LLM trên cùng 1 GPU A100 (40GB VRAM) được cấu hình tỉ lệ VRAM an toàn tuyệt đối tránh OOM:
- **Model 1 (Grounding C1 Fallback)**: `Qwen2.5-3B-Instruct` (`gpu_memory_utilization = 0.22` ~ 8.8 GB VRAM).
- **Model 2 (Planner Generator)**: `Qwen3.5-9B` (`gpu_memory_utilization = 0.68` ~ 27.2 GB VRAM).
- **VRAM Headroom**: Chừa lại 4.0 GB (10%) cho CUDA runtime, PyTorch context và DuckDB.

```bash
# 1. Chạy thử nghiệm 20 câu tập train trên GPU Modal với 2 mô hình online sẵn
modal run scripts/modal_run_pipeline.py --split train --limit 20 --enable-thinking

# 2. Chạy toàn bộ tập public_test để xuất file nộp bài submission.jsonl
modal run scripts/modal_run_pipeline.py \
    --split public_test \
    --batch-size 16 \
    --local-output-dir artifacts/runs/public_test_final
```

