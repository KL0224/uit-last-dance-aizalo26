# Báo Cáo Review Lần 2 — Sau Khi Sửa Lỗi End-to-End (B0.1 – B0.5)

> **Tài liệu đối chiếu trước khi sửa:**  
> - Vòng 1 (Review từng module): [`B0_COMPREHENSIVE_CODE_REVIEW.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/B0_COMPREHENSIVE_CODE_REVIEW.md)  
> - Vòng 2 (Review thông luồng End-to-End B0.1 → B0.5): [`B0_E2E_FLOW_REVIEW.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/B0_E2E_FLOW_REVIEW.md)  
> - Kế hoạch khắc phục: [`B0_REMEDIATION_PLAN.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/plan/B0_REMEDIATION_PLAN.md)  
> **Phương pháp thực hiện:** Test-Driven Development (`RED → GREEN → REFACTOR`) kết hợp Incremental Implementation theo 5 lát cắt mỏng (Slices).

---

## 1. Tổng Quan Kết Quả Trước & Sau Khi Sửa

| Chỉ số đánh giá | Trước khi sửa (Ban đầu) | Sau Vòng 1 (Cục bộ) | **Sau Vòng 2 (Hoàn tất E2E)** |
| :--- | :---: | :---: | :---: |
| **Tổng số bài test (`pytest`)** | 164 passed, 3 skipped | 209 passed, 3 skipped | **220 passed, 0 failed** (gồm cả `test_train_smoke.py` trên `data/train`) |
| **Bộ test hồi quy (`test_remediation_b0.py`)** | 0 | 42 passed | **49 passed** |
| **Bộ test tích hợp E2E (`test_b0_e2e_integration.py`)** | 0 | 3 passed | **4 passed** (bao gồm `B0Pipeline` E2E 5 kịch bản) |
| **Test trên dữ liệu thật (`test_train_smoke.py`)** | Skipped (chưa có data) | Skipped | **2 passed (6 subtests passed)** trên `data/train` |
| **Lỗi Critical còn mở** | 7 (Vòng 1) + 4 (Vòng 2 E2E) | 4 (Vòng 2 E2E) | **0** |
| **Lỗi Required / Major còn mở** | 10 (Vòng 1) + 3 (Vòng 2 E2E) | 3 (Vòng 2 E2E) | **0** |
| **Trạng thái thông luồng B0.1 → B0.5** | Đứt gãy ở 5 điểm giao cắt | Đứt gãy ở Orchestrator, `unanswerable`, Retry & Join | **Thông suốt 100% qua `B0Pipeline`** |

---

## 2. Sơ Đồ Kiến Trúc Luồng Dữ Liệu End-to-End Sau Khi Sửa (ASCII)

```text
+======================================================================================+
|                        B0PIPELNE END-TO-END ORCHESTRATOR                             |
|                       (src/datamate/b0/pipeline.py [NEW])                            |
+======================================================================================+
                                          |
        +---------------------------------+---------------------------------+
        | 1. B0Pipeline.prepare_bundle() / load_context()                   |
        v                                                                   |
+-----------------------------------------------------------------------+   |
| B0.1 INGESTION & SCHEMA CATALOG + B0.2 RULE COMPILER                  |   |
| - parse_date(): hỗ trợ thêm 5 định dạng ngày/giờ VN [BUG-03]          |   |
| - Full-table Join Discovery: đề xuất key pairs (`ma_*`, `*_id`) và    |   |
|   kiểm chứng độ phủ >= 80% trên toàn bảng DuckDB [E2E-05 / BUG-02]    |   |
| - CSV/XLSX Reader: bảo vệ header tự sinh `column_1` & lazy-open       |   |
|   workbook công thức 1 lần duy nhất [E2E-08 / BUG-04 / BUG-05]        |   |
| - Rule Compiler: liên kết cả tên cột gốc tiếng Việt (`provenance`)    |   |
|   vào `linked_fields` [BUG-07]                                        |   |
+-----------------------------------------------------------------------+   |
        |                                                                   |
        | business_context.json + data.duckdb                               |
        v                                                                   |
+-----------------------------------------------------------------------+   |
| B0.3 PROMPT BUILDER, GENERATOR, PARSER & EVIDENCE VERIFIER            |   |
| - Prompt (`prompt.py`): đọc đúng `join_graph`, `key_candidates`,      |   |
|   tên gốc tiếng Việt và khoảng ngày `data_profiling` [BUG-08]         |   |
| - Rule Selection (`_select_rules`): lọc bỏ ngành khác, chỉ giữ rule   |   |
|   có `precedence` cao nhất cho mỗi `topic` [E2E-06]                   |   |
| - Parser (`parser.py`): xóa `<think>...</think>`, chuẩn hóa 7 kiểu    |   |
|   `answer_type` (không bao giờ trả `generic`), trích bảng bằng AST    |   |
|   `sqlglot` [BUG-09, BUG-11, BUG-12, BUG-20]                          |   |
| - Semantics (`types.py`): tự suy luận `count`, `money_vnd`,           |   |
|   `average_money_vnd` từ biểu thức SQL `COUNT/SUM/AVG` [E2E-04]       |   |
| - Evidence Verifier (`evidence.py` [NEW]): đối chiếu `missing_fields` |   |
|   với `schema_catalog` -> cấp `catalog_verified` hoặc bác bỏ nếu cột  |   |
|   đã tồn tại trong bảng [E2E-02 / BUG-10]                             |   |
+-----------------------------------------------------------------------+   |
        |                                                                   |
        +-------------------+-------------------------------+               |
        | status ==         |                               | status ==     |
        | "answerable"      v                               | "unanswerable"|
        |   +-------------------------------------------+   | (Bỏ qua B0.4) |
        |   | B0.4 SAFE SQL EXECUTOR                    |   |               |
        |   | - Sanitizer (`sanitizer.py`): che literal |   |               |
        |   |   & comment trước khi quét từ khóa cấm;   |   |               |
        |   |   kiểm tra `ALLOWED_ROOT_NODES` [BUG-15]  |   |               |
        |   | - Engine (`engine.py`): mở trực tiếp      |   |               |
        |   |   `data.duckdb`, đọc đủ các sheet `.xlsx`,|   |               |
        |   |   ẩn cột nội bộ `__dm_row_id` khỏi        |   |               |
        |   |   `SELECT *`, gắn cờ `truncated`          |   |               |
        |   |   [BUG-16, BUG-17, E2E-07]                |   |               |
        |   | - Schemas (`schemas.py`): chuẩn hóa an    |   |               |
        |   |   toàn `bool`, `Decimal` vô cực, `time`   |   |               |
        |   |   [BUG-14]                                |   |               |
        |   +-------------------------------------------+   |               |
        |                   |                               |               |
        +-------------------+---------------+---------------+               |
                                            |                               |
                                            v                               |
+-----------------------------------------------------------------------+   |
| B0.5 BASIC OUTPUT GATE (`evaluate_gate`)                              |   |
| - Answerability (`answerability.py`): nhận `EvidenceProof` đã kiểm    |   |
|   chứng từ B0.3 -> trả `unanswerable` hợp lệ; nếu LLM bịa cột thiếu   |   |
|   -> hạ xuống `abstain` an toàn [E2E-02]                              |   |
| - Retry Classifier (`retry.py`): nhận diện đầy đủ `CatalogError`,     |   |
|   `DataError`, `EmptyQueryError` là lỗi cho phép retry [E2E-03]       |   |
| - Formatter (`formatter.py`): `format_date` chấp nhận chuỗi ISO       |   |
|   timestamp từ DuckDB; chuẩn hóa `Decimal`/`date` trong `list`/`table`|   |
|   [BUG-13, BUG-19]                                                    |   |
+-----------------------------------------------------------------------+   |
        |                                           |                       |
        | Action == RETRY (attempt == 0)            | Action == FINAL       |
        +-------------------------------------------+                       |
        | Gọi `generator.repair()` với `RepairRequest` (attempt = 1) -------+
        v
+-----------------------------------------------------------------------+
| SUBMISSION WRITER (`submission.jsonl` + `gate_trace.jsonl`)           |
+-----------------------------------------------------------------------+
```

---

## 3. Đối Chiếu Chi Tiết Từng Lỗi (Vòng 2 End-to-End & Vòng 1)

### 3.1. Nhóm 8 Lỗi Xung Đột Thông Luồng End-to-End (`E2E-01` → `E2E-08`)

| Mã lỗi | Mức độ | Vấn đề trước khi sửa | Giải pháp đã triển khai | Bài test kiểm chứng |
| :--- | :---: | :--- | :--- | :--- |
| **E2E-01** | **CRITICAL** | Thiếu bộ điều phối nối B0.1 → B0.2 → B0.3 → B0.4 → B0.5 và mâu thuẫn quyền quyết định retry giữa `ExecutionResponse.route` (B0.4) và `GateOutcome.action` (B0.5). | Tạo mới [`src/datamate/b0/pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/pipeline.py) với class [`B0Pipeline`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/pipeline.py#L28-L214). B0.4 đóng vai trò cung cấp dữ liệu/lỗi thực thi, còn `evaluate_gate()` của B0.5 là cổng duy nhất quyết định `FINAL` hay `RETRY` (1 lần qua `generator.repair()`). | `test_b0_pipeline_end_to_end_orchestration` (`tests/test_b0_e2e_integration.py`) |
| **E2E-02** | **CRITICAL** | `Text2SQLResult` khi `status="unanswerable"` không tạo được `EvidenceProof(source_kind="catalog_verified")`, khiến 100% câu `unanswerable` bị B0.5 hạ xuống `abstain` (mất sạch điểm phần câu hỏi không thể trả lời). | Tạo mới [`src/datamate/b0/b03/evidence.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/evidence.py) với hàm [`build_evidence_proof`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/evidence.py#L61-L154) và phương thức [`Text2SQLResult.to_b05_evidence_proof(context)`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L166-L174). Đối chiếu `missing_fields` với toàn bộ cột và `provenance` trong `schema_catalog`: nếu cột thực sự không tồn tại thì cấp `catalog_verified`; nếu LLM bịa ra một cột đang tồn tại trong bảng là "thiếu", trả `unverified` để B0.5 hạ xuống `abstain`. | `test_e2e02_evidence_proof_verifies_missing_field_and_rejects_existing_field` & `test_b0_pipeline_end_to_end_orchestration` (Q3, Q4) |
| **E2E-03** | **CRITICAL** | B0.4 trả `error_type` là `"CatalogError"` (sai tên bảng), `"DataError"` (tràn số/ép kiểu) và `"EmptyQueryError"`, nhưng `classify_error` của B0.5 không nhận diện được các chuỗi này → rơi vào `EXECUTION_ERROR (retryable=False)` làm mất cơ hội retry. | Cập nhật [`src/datamate/b0/b05/retry.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py#L46-L78): bổ sung `"catalog"`, `"does not exist"` vào `SCHEMA_ERROR`; `"dataerror"`, `"out of range"`, `"invalid input"` vào `SQL_TYPE_ERROR`; `"emptyquery"`, `"query is empty"` vào `SQL_SYNTAX` (tất cả đều `retryable=True`). | `test_e2e03_b05_retry_recognizes_catalog_data_and_empty_query_errors` & `test_b0_pipeline_end_to_end_orchestration` (Q2) |
| **E2E-04** | **CRITICAL** | Khi LLM sinh truy vấn tính tiền (`AVG(thanh_tien)`, `SUM(don_gia * so_luong)`) nhưng bỏ trống `answer_semantics`, B0.5 mặc định dùng `NumericKind.GENERIC` (giữ 2 số lẻ thập phân thay vì làm tròn đến hàng đơn vị VND). | Cập nhật [`_infer_numeric_kind`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L182-L194) trong [`src/datamate/b0/b03/types.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py): tự động phát hiện từ khóa tiền tệ (`tien`, `gia`, `doanh_thu`, `chi_phi`, `revenue`, `amount`, `price`, `cost`, `profit`, ...) trong biểu thức `AVG(...)` → `"average_money_vnd"` và `SUM(...)` → `"money_vnd"`. | `test_e2e04_infer_money_numeric_kind_from_sql` & `test_b0_pipeline_end_to_end_orchestration` (Q1) |
| **E2E-05** | **MAJOR** | Suy luận cạnh nối bảng (`join_graph`) trong B0.1 bị chặn bởi 5 dòng mẫu (`profile_rows`): nếu 5 dòng đầu của 2 bảng không trùng khóa (dù cả bảng trùng ≥ 80%), cạnh join bị bỏ sót hoàn toàn. | Cập nhật [`src/datamate/b0/b01/schema_catalog.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L124-L154) và [`src/datamate/b0/b01/ingestion/profiling.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/profiling.py#L97-L105): khi có `profile_provider` (DuckDB), các cặp cột có tên giống khóa (`ma_*`, `*_id`, `id`, `sku`, `code`) được đề xuất thẳng sang bước kiểm chứng SQL toàn bảng (`check_join`) và chỉ giữ lại khi độ phủ thực tế `coverage >= 0.8`. | `test_e2e05_full_table_join_discovered_when_first_5_rows_disjoint` |
| **E2E-06** | **MAJOR** | `format_context_for_prompt` đưa toàn bộ rule (kể cả rule của ngành khác và rule `split_default` đã bị ghi đè bởi rule `business`) vào prompt, gây nhiễu cho LLM. | Cập nhật [`_select_rules`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py#L103-L133) trong [`src/datamate/b0/b03/prompt.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py): lọc bỏ mọi rule thuộc `industry` khác với ngành của doanh nghiệp hiện tại và chỉ giữ lại rule có `precedence` cao nhất cho mỗi `topic`. | `test_e2e06_prompt_filters_other_industries_and_lower_precedence_rules` |
| **E2E-07** | **MAJOR** | Mọi bảng DuckDB do B0.1 tạo đều có cột nội bộ `__dm_row_id` ở vị trí đầu tiên; câu lệnh `SELECT * FROM ...` cho câu hỏi `table` sẽ làm lộ cột `__dm_row_id` ra kết quả chấm điểm. | Cập nhật [`src/datamate/b0/b04/engine.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L225-L234): tự động lọc bỏ các cột nội bộ bắt đầu bằng `__dm_` (khi vẫn còn cột dữ liệu thực) khỏi `columns` và `rows` trả về. | `test_e2e07_select_star_hides_internal_dm_row_id_column` |
| **E2E-08** | **MINOR** | (1) Dòng dữ liệu có giá trị `"column_1"` trùng với header tự sinh bị xóa nhầm như dòng lặp header; (2) `XLSXReader.discover` mở lại file `.xlsx` `data_only=False` cho từng sheet. | Cập nhật [`src/datamate/b0/b01/ingestion/readers.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L169-L174): thêm hàm `_is_repeated_header` (bỏ qua nếu header chứa tên tự sinh `column_\d+`) và chỉ lazy-open workbook `original` tối đa 1 lần cho cả file `.xlsx`. | `test_e2e08_synthetic_header_column_1_not_dropped_as_repeated_header` |

---

### 3.2. Nhóm Lỗi Vòng 1 (`BUG-01` → `BUG-20`) — Trạng Thái Toàn Bộ

| Mã lỗi | Mô tả ngắn | Trạng thái cuối cùng |
| :--- | :--- | :---: |
| **BUG-01** | Nghi ngờ `evidence=()` làm `check_join` thành dead code | **Rút lại (False Positive)** — cạnh FK khai báo vẫn giữ `evidence` và được kiểm chứng đúng. |
| **BUG-02** | Suy luận join bị giới hạn bởi 5 dòng mẫu `profile_rows` | **Đã sửa triệt để** (gộp trong **E2E-05**). |
| **BUG-03** | `parse_date` thiếu định dạng ngày giờ không có giây / dấu `/` | **Đã sửa** (`normalization.py`). |
| **BUG-04** | Bỏ qua dòng dữ liệu trùng với header tự sinh `column_1` | **Đã sửa triệt để** (gộp trong **E2E-08**). |
| **BUG-05** | `XLSXReader` mở lại workbook `data_only=False` nhiều lần | **Đã sửa triệt để** (gộp trong **E2E-08**). |
| **BUG-06** | `README.md` gắn scope `business` | **Giữ nguyên theo thiết kế** (quy ước cấu trúc thư mục doanh nghiệp). |
| **BUG-07** | `_linked_fields` không khớp tên cột gốc tiếng Việt | **Đã sửa** (`rule_compiler.py` đối chiếu cả `column.provenance`). |
| **BUG-08** | `format_context_for_prompt` đọc sai tên trường của B0.1 | **Đã sửa** (`prompt.py` đọc `join_graph`, `key_candidates`, `provenance`, `data_profiling`). |
| **BUG-09** | `infer_answer_type_from_sql` trả về `"generic"` làm B0.5 crash | **Đã sửa** (`normalize_answer_type` chuẩn hóa về 7 kiểu hợp lệ). |
| **BUG-10** | B0.3 đánh rơi `answer_semantics` và `EvidenceProof` | **Đã sửa triệt để** (cả `answer_semantics` lẫn `to_b05_evidence_proof` trong **E2E-02** & **E2E-04**). |
| **BUG-11** | `extract_tables_from_sql` bắt nhầm `EXTRACT(... FROM col)` và tên CTE | **Đã sửa** (dùng AST `sqlglot` + regex fallback an toàn). |
| **BUG-12** | `parse_text2sql_response` lỗi khi có `<think>...</think>` hoặc ` ``` ` trong JSON | **Đã sửa** (`parser.py` và `sanitizer.py`). |
| **BUG-13** | `format_date` của B0.5 từ chối chuỗi ISO timestamp từ DuckDB | **Đã sửa** (`formatter.py`). |
| **BUG-14** | `_normalize_value` của B0.4 xử lý sai `bool`, `Decimal('Infinity')`, `datetime.time` | **Đã sửa** (`schemas.py`). |
| **BUG-15** | `sanitizer.py` chặn nhầm từ khóa trong chuỗi literal và bỏ lọt `TRUNCATE`/`SHOW` | **Đã sửa** (`sanitizer.py`). |
| **BUG-16** | `engine.py` tạo DB rỗng khi nhận thư mục bundle hoặc ghi đè bảng cùng tên | **Đã sửa** (`engine.py` mở trực tiếp `data.duckdb`, đọc mọi sheet `.xlsx`, khử trùng tên bảng). |
| **BUG-17** | `engine.py` cắt ngầm ở `max_rows` nhưng không báo `truncated=True` cho B0.5 | **Đã sửa** (`fetchmany(max_rows + 1)` → `truncated`). |
| **BUG-18** | Xung đột quyết định retry giữa `route` (B0.4) và `action` (B0.5) | **Đã giải quyết ở tầng kiến trúc** qua `B0Pipeline` (**E2E-01**): `evaluate_gate().action` của B0.5 là quyết định điều phối duy nhất. |
| **BUG-19** | `format_list` / `format_table` chưa chuẩn hóa `Decimal` và `date` | **Đã sửa** (`formatter.py`). |
| **BUG-20** | `infer_answer_type_from_sql` chỉ tách `FROM` viết hoa | **Đã sửa** (`re.IGNORECASE`). |

---

## 4. Đánh Giá Lại Chất Lượng Code Theo 5 Trục

| Trục đánh giá | Điểm ban đầu | Điểm sau Vòng 1 | **Điểm sau Vòng 2 (Hiện tại)** | Nhận xét chuyên môn |
| :--- | :---: | :---: | :---: | :--- |
| **1. Correctness (Tính đúng đắn)** | 5.5 / 10 | 8.0 / 10 | **9.5 / 10** | Toàn bộ 8 điểm đứt gãy E2E và 18 lỗi logic cục bộ đã được khắc phục và có bài test tự động khóa chặt. |
| **2. Architecture & Contracts (Kiến trúc)** | 6.0 / 10 | 8.0 / 10 | **9.5 / 10** | Đã có `B0Pipeline` đóng vai trò entrypoint chuẩn nối liền B0.1 → B0.5, kèm cơ chế kiểm chứng `EvidenceProof` từ `schema_catalog`. |
| **3. Security (Bảo mật)** | 6.5 / 10 | 8.0 / 10 | **9.0 / 10** | AST Sanitizer kiểm tra nút gốc `ALLOWED_ROOT_NODES`, chặn multi-statement và ẩn cột nội bộ `__dm_*`. |
| **4. Performance (Hiệu năng)** | 7.5 / 10 | 7.5 / 10 | **9.0 / 10** | `XLSXReader` chỉ mở workbook công thức tối đa 1 lần khi cần; `B0Pipeline.run_questions` cache `business_context.json` theo từng doanh nghiệp. |
| **5. Readability & Testability (Khả năng kiểm thử)** | 8.0 / 10 | 8.5 / 10 | **9.5 / 10** | 220 bài test chạy hoàn toàn độc lập, bao phủ từ unit test từng hàm tới E2E pipeline và smoke test trên dữ liệu thật `data/train`. |

---

## 5. Lệnh Kiểm Chứng Thực Tế

Bạn có thể chạy trực tiếp các lệnh sau trong terminal để xác nhận toàn bộ hệ thống:

```bash
source .venv/bin/activate

# 1. Chạy toàn bộ test suite (Unit + Remediation + E2E Integration)
pytest -v

# 2. Chạy riêng bộ test sửa lỗi & E2E pipeline
pytest tests/test_remediation_b0.py tests/test_b0_e2e_integration.py -v

# 3. Chạy smoke test trên bộ dữ liệu thật data/train
DATAMATE_TRAIN_DIR=data/train pytest tests/test_train_smoke.py -v
```
