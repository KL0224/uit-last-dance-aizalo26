# Báo Cáo Thay Đổi & Hồ Sơ Quyết Định Kiến Trúc (ADR-013): Tái Cấu Trúc Toàn Diện Các Module Chuẩn Hóa Dưới Thư Mục `src/datamate/`

> **Tài liệu:** `docs/change/DATAMATE_MODULAR_REFACTORING_CHANGELOG.md`  
> **Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
> **Phạm vi tác động:** `src/datamate/`, `scripts/`, `tests/`  
> **Trạng thái:** **Accepted & Verified (361 passed, 3 skipped, 15 subtests passed)**

---

## 1. Bối Cảnh & Động Lực (Context & Motivation)

Trong giai đoạn đầu của dự án, các thành phần hệ thống được tổ chức trong thư mục con `src/datamate/b0/` với các tiền tố `b01`, `b02`, `b03`, `b04`, `b05`. Cấu trúc này phù hợp cho giai đoạn xây dựng đường cơ sở B0 (Baseline 0). 

Tuy nhiên, khi dự án bước sang giai đoạn phát triển mở rộng (B1, B2) với các module chuyên biệt như **Component C (`grounding`)**, tối ưu hóa bộ thực thi DuckDB (`execution`), quản lý ngân sách suy luận mô hình (`planner`), và cổng kiểm soát kết quả nâng cao (`gate`), cấu trúc `b0/` bộc lộ một số hạn chế:
1. **Thiếu tính định danh ngữ nghĩa (Semantic Naming)**: Tên gọi `b01`, `b02` không phản ánh trực tiếp chức năng nghiệp vụ của module.
2. **Khó khăn trong mở rộng kiến trúc**: Các module nâng cao (như `grounding`) nằm ngoài thư mục `b0/`, tạo ra sự bất đối xứng trong việc import và đóng gói.
3. **Phụ thuộc vào mã nguồn cũ**: Các module kế thừa tên `b0` gây nhầm lẫn khi người dùng hoặc các module cấp cao muốn tận dụng lại tính năng cốt lõi cho các baseline sau.

Nhằm chuẩn hóa kiến trúc dự án theo tiêu chuẩn production-grade, toàn bộ hệ thống đã được tái cấu trúc thành các module độc lập, mang tên ngữ nghĩa trực tiếp dưới `src/datamate/`.

---

## 2. Bản Đồ Kiến Trúc Mới (Canonical Architecture Mapping)

| Module Mới (`src/datamate/`) | Đường Dẫn Cũ (`src/datamate/b0/`) | Trách Nhiệm Nghiệp Vụ Cốt Lõi (Core Responsibilities) |
| :--- | :--- | :--- |
| **`datamate.ingestion`** | `b0/b01/` | Nạp dữ liệu đa định dạng (CSV, XLSX), chuẩn hóa tên bảng/cột, profiling thống kê DuckDB, trích xuất `SchemaCatalog`, phát hiện và xác thực `JoinGraph`. |
| **`datamate.context`** | `b0/b02/` | Phân tích và biên dịch quy tắc kinh doanh (`rulebook.md`), quản lý `RuleCatalog`, giải quyết xung đột quy tắc theo độ ưu tiên (`RuleResolver`), và xây dựng `BusinessContext`. |
| **`datamate.grounding`** | `grounding/` (giữ nguyên) | Chuẩn hóa câu hỏi tiếng Việt, phân giải mốc thời gian tất định (`QuestionTemporalResolver`), liên kết schema/giá trị, và tiền kiểm chứng khả năng trả lời (`AnswerabilityPrecheck`). |
| **`datamate.planner`** | `b0/b03/` | Xây dựng prompt Text-to-SQL, quản lý kết nối inference engine (vLLM / OpenAI API), kiểm soát ngân sách token suy luận (`thinking_token_budget`), phân tích cú pháp AST phản hồi, và thu thập chẩn đoán (`GenerationDiagnostics`). |
| **`datamate.execution`** | `b0/b04/` | Thực thi truy vấn DuckDB ở chế độ Read-Only an toàn, bộ lọc AST chống tấn công SQL injection (`validate_read_only_sql`), làm giàu ngữ cảnh lỗi kèm schema (`enrich_error_with_schema`). |
| **`datamate.gate`** | `b0/b05/` | Cổng kiểm duyệt đầu ra, định dạng câu trả lời theo 9 loại kiểu dữ liệu hợp lệ, máy trạng thái retry có giới hạn (bounded retry state machine), ghi nhận file nộp bài (`submission.jsonl`) và audit trail (`detailed_logs.jsonl`). |
| **`datamate.pipeline`** | `b0/pipeline.py` | Bộ điều phối toàn trình (`Pipeline` / alias `B0Pipeline`), tích hợp toàn bộ luồng từ Ingestion $\rightarrow$ Context $\rightarrow$ Planner $\rightarrow$ Execution $\rightarrow$ Gate. |

---

## 3. Hoàn Tất Chuyển Đổi & Xóa Bỏ Hoàn Toàn Thư Mục Legacy `src/datamate/b0/`

Sau khi kiểm thử toàn diện và xác nhận mọi tính năng của hệ thống hoạt động ổn định trên cấu trúc module mới:
1. **Xóa Bỏ Toàn Diện Thư Mục `src/datamate/b0/`**:
   - Toàn bộ các thư mục con `b01`, `b02`, `b03`, `b04`, `b05` và `b0/pipeline.py` đã được loại bỏ triệt để khỏi cây mã nguồn.
   - Loại bỏ toàn bộ các khối `try ... except ImportError` fallback về `b0`, giữ mã nguồn sạch sẽ, không còn nợ kỹ thuật (dead code / obsolete shims).
2. **Hỗ Trợ Alias `B0Pipeline` Tại Namespace Chính**:
   - Để giữ tính tương thích thuận tiện cho các script triệu gọi cũ, class `Pipeline` tiếp tục được alias `B0Pipeline = Pipeline` ngay tại `datamate` và `datamate.pipeline`.

---

## 4. Chi Tiết Các Thay Đổi & Tái Cấu Trúc (Refactoring Details)

### 4.1. Cập Nhật Import Nội Bộ Tại Gốc (`src/datamate/__init__.py`)
Package gốc export trực tiếp toàn bộ các module ngữ nghĩa:
```python
from datamate import context, execution, gate, grounding, ingestion, pipeline, planner
from datamate.pipeline import B0Pipeline, Pipeline

__all__ = [
    "ingestion",
    "context",
    "grounding",
    "planner",
    "execution",
    "gate",
    "pipeline",
    "Pipeline",
    "B0Pipeline",
]
```

### 4.2. Cập Nhật Import Trong Tất Cả Các Module Canonical
Toàn bộ các tệp nguồn trong:
* `src/datamate/ingestion/`
* `src/datamate/context/`
* `src/datamate/grounding/`
* `src/datamate/planner/`
* `src/datamate/execution/`
* `src/datamate/gate/`
* `src/datamate/pipeline.py`
đã được chuyển đổi để ưu tiên tham chiếu trực tiếp các module anh em dưới namespace `datamate.*`.

### 4.3. Cập Nhật Scripts Công Cụ (`scripts/`)
Các scripts vận hành đã được tái thiết import:
* [`scripts/demo_join_graph.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/demo_join_graph.py): chuyển đổi sang `datamate.ingestion` và `datamate.context`.
* [`scripts/run_b0_pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_b0_pipeline.py): import `datamate.pipeline.Pipeline`, `datamate.planner.*`.
* [`scripts/check_thinking_budget.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/check_thinking_budget.py): import `datamate.planner.*`.
* [`scripts/benchmark_b04_comparison.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/benchmark_b04_comparison.py): import `datamate.execution.*`.
* [`scripts/benchmark_preparation.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/benchmark_preparation.py): import `datamate.ingestion.*`.
* [`scripts/audit_prepared_bundles.py`](file:///home/kiet97/uit-last-dance-aizalo26/scripts/audit_prepared_bundles.py): import `datamate.ingestion.*`.

### 4.4. Tái Thiết Lập Bộ Kiểm Thử (`tests/`)
1. **Tạo mới `tests/test_modular_imports.py`** với 9 test cases độc lập:
   - Kiểm tra export tại root package `datamate`.
   - Kiểm tra export và tính toàn vẹn của `datamate.ingestion`.
   - Kiểm tra export và tính toàn vẹn của `datamate.context`.
   - Kiểm tra export và tính toàn vẹn của `datamate.grounding`.
   - Kiểm tra export và tính toàn vẹn của `datamate.planner` (kèm xác thực `thinking_token_budget`).
   - Kiểm tra export và tính toàn vẹn của `datamate.execution` (kèm security contracts).
   - Kiểm tra export và tính toàn vẹn của `datamate.gate`.
   - Kiểm tra khởi tạo và API của `datamate.pipeline.Pipeline`.
   - Kiểm tra tính tương thích 100% của facade `datamate.b0.*`.
2. **Cập nhật toàn bộ test suites**:
   - `tests/grounding/test_vllm_fallback.py`: monkeypatch cả `datamate.planner.VLLMModel` và `datamate.b0.b03.VLLMModel`.
   - `tests/grounding/test_b01_b02_compatibility.py` và `test_grounding_e2e.py`: chuyển sang import canonical.
   - `tests/test_b0_e2e_integration.py`, `tests/test_b04_b05_pipeline_compatibility.py`, `tests/test_thinking_budget_diagnostics.py`, `tests/test_b0_4_executor.py`, `tests/test_b03_text2sql.py`, và toàn bộ họ `tests/test_b05_*.py`: đồng bộ hoàn toàn sang canonical `datamate.*`.

---

## 5. Kết Quả Kiểm Thử (Verification Results)

Sau khi hoàn tất tái cấu trúc và đồng bộ toàn diện, bộ kiểm thử tự động ghi nhận kết quả:
* **Tổng số test cases vượt qua:** **`361 passed, 3 skipped, 15 subtests passed`** (tăng từ 352 lên 361 với bộ test modular imports mới).
* **Tỷ lệ kiểm thử thành công:** **`100% GREEN`**.
* **Thời gian thực thi:** **~12.40s**.
* **Không phát hiện bất kỳ regression hay xung đột mã nguồn nào.**

