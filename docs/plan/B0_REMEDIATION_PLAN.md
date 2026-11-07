# Kế Hoạch Sửa Chữa & Thông Luồng End-to-End Toàn Tuyến B0 (B0.1 → B0.5)

> **Tài liệu Review liên kết:**  
> - [`docs/review/B0_E2E_FLOW_REVIEW.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/B0_E2E_FLOW_REVIEW.md) (Phân tích chuyên sâu luồng End-to-End B0.1 → B0.5)  
> - [`docs/review/B0_COMPREHENSIVE_CODE_REVIEW.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/B0_COMPREHENSIVE_CODE_REVIEW.md) (Báo cáo kiểm toán vòng 1)  
> - [`docs/review/B0_POST_FIX_REVIEW.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/B0_POST_FIX_REVIEW.md) (Đối chiếu kết quả sau vòng 1)  
> **Tiêu chuẩn áp dụng:** Vertical Slicing (`planning-and-task-breakdown`) + Architecture Decision Records (`documentation-and-adrs`)

---

## 1. Tổng Quan Kế Hoạch (Overview)

Sau khi đã xử lý 14 lỗi nội bộ ở Vòng 1 (nâng tổng số bài test lên `209 passed`), kế hoạch giai đoạn 2 này tập trung giải quyết triệt để **8 lỗi và xung đột xuyên luồng (`E2E-01` → `E2E-08`)** để đảm bảo toàn bộ pipeline từ **B0.1 → B0.2 → B0.3 → B0.4 → B0.5** chạy **End-to-End** hoàn toàn tự động, không xung đột hợp đồng dữ liệu và đạt độ chính xác cao nhất khi chấm thi:

1. **Giải quyết xung đột Discovery & Ingestion ở B0.1 (`E2E-05`, `E2E-08`):** Không để 5 dòng mẫu (`profile_rows`) chặn mất việc khám phá cạnh Join bằng SQL toàn bảng của `DuckDBProfileProvider`; bảo vệ bảng 1 cột không bị mất dòng dữ liệu trùng header; tối ưu đọc `.xlsx`.
2. **Giải quyết xung đột Quy tắc Nghiệp vụ B0.2 → B0.3 (`E2E-06`):** Tích hợp logic lọc ưu tiên (`precedence`) và lọc theo ngành (`industry`) vào `format_context_for_prompt()` để LLM không bị nhiễu bởi quy tắc của ngành khác hoặc quy tắc mặc định đã bị ghi đè.
3. **Giải quyết rò rỉ cột nội bộ B0.1 → B0.4 → B0.5 (`E2E-07`):** Tự động lọc bỏ các cột hệ thống bắt đầu bằng `__dm_` (như `__dm_row_id`) khỏi kết quả `execute_query()` để câu lệnh `SELECT *` không làm thừa cột trong `submission.jsonl`.
4. **Giải quyết xung đột phân loại lỗi Retry giữa B0.4 và B0.5 (`E2E-03`) & Ngữ nghĩa số học B0.3 → B0.5 (`E2E-04`):** Bổ sung nhận diện `CatalogError` (`"catalog"`, `"does not exist"`), `DataError`, `EmptyQueryError` vào `src/datamate/b0/b05/retry.py`; tự động suy luận `money_vnd` / `average_money_vnd` từ câu SQL/câu hỏi.
5. **Giải quyết xung đột luồng `unanswerable` B0.2 → B0.3 → B0.5 (`E2E-02`):** Xây dựng bộ kiểm chứng `build_evidence_proof()` đối chiếu `Text2SQLResult` với `SchemaCatalog` và `answerability_constraints` để sinh `EvidenceProof(source_kind="catalog_verified")` hợp lệ, giúp câu hỏi `unanswerable` không bị B0.4 báo lỗi `EmptyQueryError` và không bị B0.5 ép thành `abstain`.
6. **Xây dựng Bộ Điều Phối End-to-End `B0Pipeline` (`E2E-01`):** Kết nối liền mạch B0.1 → B0.2 → B0.3 (`generate` & `repair`) → B0.4 (`execute_query`) → B0.5 (`evaluate_gate` & `SubmissionWriter`) trong `src/datamate/b0/pipeline.py`.

---

## 2. Quyết Định Kiến Trúc (Architecture Decision Records - ADRs)

### ADR-004: Kiến Trúc Bộ Điều Phối End-to-End (`B0Pipeline`) & Quyền Quyết Định Retry Duy Nhất
- **Trạng thái:** Proposed
- **Bối cảnh:** Hiện tại B0.4 (`ExecutionResponse.route`) và B0.5 (`GateOutcome.action`) đều có logic quyết định retry riêng và có điểm khác biệt (B0.4 coi `SecurityViolation`/`TimeoutError` là `recoverable`, còn B0.5 coi là `non-retryable`; ngược lại B0.5 phát hiện được lỗi `SCALAR_SHAPE_MISMATCH` và `OUTPUT_TYPE_ERROR` sau khi B0.4 đã chạy SQL thành công).
- **Quyết định:**
  - Thiết lập [`evaluate_gate()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/gate.py#L20) của **B0.5 làm Cổng Quyết Định Cuối Cùng (Single Source of Truth)** cho toàn bộ vòng lặp Bounded Retry trong `B0Pipeline`, đồng thời giữ nguyên thuộc tính `ExecutionResponse.route` ở B0.4 để tương thích ngược 100% với bộ unit test B0.4.
  - Đồng bộ hóa [`src/datamate/b0/b05/retry.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py#L20-L65) để nhận diện đầy đủ mọi mã lỗi truy vấn có thể sửa được do B0.4 phát ra (`CatalogError`, `BinderError`, `SyntaxError`, `ConversionError`, `DataError`, `EmptyQueryError`).
- **Hệ quả:** Vòng lặp Bounded Retry (tối đa 1 lần thử lại) hoạt động nhất quán cho cả lỗi thực thi SQL ở B0.4 lẫn lỗi sai kích thước/kiểu dữ liệu ở B0.5.

### ADR-005: Cơ Chế Xác Thực Bằng Chứng (`EvidenceProof`) Cho Câu Hỏi `unanswerable`
- **Trạng thái:** Proposed
- **Bối cảnh:** B0.5 [`evaluate_answerability`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/answerability.py#L8-L39) từ chối mọi tuyên bố `unanswerable` tự phát từ LLM nếu `evidence.source_kind != "catalog_verified"`, dẫn đến việc hạ xuống `abstain`.
- **Quyết định:**
  - Khi B0.3 trả về `status == "unanswerable"`, bộ điều phối không gọi B0.4 (`ExecutionResult(status="not_executed")`), mà gọi hàm xác thực `verify_unanswerable_against_context(context, b03_result)` để kiểm tra toàn bộ danh sách bảng/cột trong `SchemaCatalog` và `answerability_constraints`.
  - Nếu `context` đã nạp đầy đủ `SchemaCatalog` (có danh sách `available_fields` đã kiểm tra qua tất cả các bảng `checked_all_sources=True`) và `b03_result.reason` chỉ rõ thông tin bị thiếu (hoặc `answerability_constraints` xác nhận không hỗ trợ), hệ thống tạo `EvidenceProof(source_kind="catalog_verified", capability_status="unsupported", checked_all_sources=True, ...)` truyền vào B0.5.
- **Hệ quả:** Các câu hỏi `unanswerable` thực sự được cổng B0.5 xuất đúng `"type": "unanswerable"` kèm `"reason"` thay vì bị mất điểm về `"abstain"`.

### ADR-006: Ẩn Cột Nội Bộ `__dm_*` Tại Tầng Thực Thi B0.4
- **Trạng thái:** Proposed
- **Bối cảnh:** B0.1 thêm cột `__dm_row_id` vào mọi bảng trong `data.duckdb` để nối với `meta.lineage`, nhưng ẩn cột này khỏi `SchemaCatalog`. Khi câu truy vấn dùng `SELECT *`, cột `__dm_row_id` bị lọt vào kết quả trả về của B0.4.
- **Quyết định:**
  - Tại [`execute_query()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L129-L147) trong B0.4, lọc bỏ mọi cột có tên bắt đầu bằng `"__dm_"` ra khỏi `columns` và `rows` trước khi trả về (trừ trường hợp câu truy vấn chỉ chọn duy nhất cột `__dm_*`).
- **Hệ quả:** Giữ nguyên 100% thiết kế `meta.lineage` của B0.1 trong `data.duckdb` đồng thời đảm bảo `SELECT *` ở B0.4 luôn khớp tuyệt đối với `SchemaCatalog` và đáp án chấm thi.

---

## 3. Sơ Đồ Phụ Thuộc Các Nhiệm Vụ (Task Dependency Graph - ASCII)

```text
+===================================================================================+
|               LỘ TRÌNH THỰC THI THÔNG LUỒNG END-TO-END (6 TASKS)                  |
+===================================================================================+

  [Task 1: B0.1 Full-Table Join Discovery & Reader Safety]
  (Giải quyết E2E-05, E2E-08)
         |
         v
  [Task 2: B0.2 -> B0.3 Rule Resolution & Prompt Filtering]
  (Giải quyết E2E-06)
         |
         v
  =================================================================
  >>> CHECKPOINT 1: B0.1 -> B0.2 -> B0.3 Context Flow Verified  <<<
  =================================================================
         |
         +-----------------------------------+
         |                                   |
         v                                   v
  [Task 3: B0.4 Hide `__dm_*` Columns]   [Task 4: B0.3/B0.4/B0.5 Retry Taxonomy,
  (Giải quyết E2E-07)                     Money Semantics & Answerability Proof]
         |                               (Giải quyết E2E-02, E2E-03, E2E-04)
         \                                   /
          \                                 /
           v                               v
  =================================================================
  >>> CHECKPOINT 2: B0.3 <-> B0.4 <-> B0.5 Contracts Verified   <<<
  =================================================================
                                   |
                                   v
  [Task 5: Xây dựng Bộ Điều Phối `B0Pipeline` (src/datamate/b0/pipeline.py)]
  (Giải quyết E2E-01: Nối trọn vẹn B0.1 -> B0.2 -> B0.3 -> B0.4 -> B0.5)
                                   |
                                   v
  [Task 6: Kiểm thử Tích hợp End-to-End Toàn Diện & Cập nhật Báo cáo Review]
                                   |
                                   v
  =================================================================
  >>> CHECKPOINT 3: Full E2E Pipeline & Regression Suite Green  <<<
  =================================================================
```

---

## 4. Danh Sách Nhiệm Vụ Chi Tiết (Ordered Atomic Tasks)

### Task 1: Mở khóa khám phá cạnh Join toàn bảng trong B0.1 và gia cố `CSVReader` / `XLSXReader`
- **Giải quyết các lỗi:** `E2E-05` `[REQUIRED]`, `E2E-08` `[OPTIONAL]`
- **Mô tả công việc:**
  1. Trong [`src/datamate/b0/b01/schema_catalog.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L120-L228) và [`src/datamate/b0/b01/ingestion/profiling.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/profiling.py#L65-L108):
     - Khi `self.profile_provider is not None`, đối với các cặp cột trùng tên thuộc nhóm khóa (`ma_*`, `*_id`, `id`, `sku`, `code`), nếu mẫu 5 dòng (`profile_rows`) không đủ `coverage >= 0.8` thì vẫn tạo cạnh ứng viên tạm thời để `self.profile_provider.check_join()` kiểm tra bằng SQL `INTERSECT` trên toàn bộ bảng DuckDB.
     - Trong `DuckDBProfileProvider.check_join()`, khi kiểm tra cạnh tự suy luận (`not edge.evidence`), tính độ phủ thực tế trên toàn bảng `sql_coverage = max(overlap / ldistinct, overlap / rdistinct)`. Nếu `overlap == 0` hoặc `sql_coverage < 0.8`, trả về `status="invalid", confidence=0.0`.
     - Trong `SchemaCatalogBuilder.build()`, loại bỏ những cạnh tự suy luận (không nằm trong `declared_edges`) có `status == "invalid"` sau khi chạy `check_join`.
  2. Trong [`src/datamate/b0/b01/ingestion/readers.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L240-L285):
     - Thêm hàm `_is_repeated_header(row_values, headers)`: chỉ coi là dòng lặp tiêu đề khi bảng có ít nhất 2 cột hoặc cột duy nhất không phải tên tự sinh `column_1`.
     - Trong `XLSXReader.discover()`, chỉ mở `original = load_workbook(..., data_only=False)` theo cơ chế lazy tối đa 1 lần cho toàn bộ file `.xlsx` và đóng trong khối `finally`.
- **Tiêu chí nghiệm thu (Acceptance Criteria):**
  - [ ] Hai bảng CSV được nạp qua `prepare_business()` có 20 dòng, trong đó 5 dòng đầu không trùng `ma_khach` nhưng 15 dòng sau trùng 100%, vẫn được phát hiện cạnh join `ma_khach` trong `business_context.json`!
  - [ ] Hai bảng có cột cùng tên `ma_khach` nhưng toàn bộ bảng không có giá trị nào giao nhau (`overlap == 0`) không bị đưa nhầm vào `join_graph`.
  - [ ] Bảng CSV 1 cột có tên cột tự sinh `column_1` chứa giá trị `"column_1"` không bị mất dòng dữ liệu.
- **Lệnh kiểm chứng (Verification):**
  ```bash
  source .venv/bin/activate && pytest tests/test_ingestion.py tests/test_remediation_b0.py -v
  ```
- **Tệp tác động:**
  - `src/datamate/b0/b01/schema_catalog.py`
  - `src/datamate/b0/b01/ingestion/profiling.py`
  - `src/datamate/b0/b01/ingestion/readers.py`
  - `tests/test_remediation_b0.py`
- **Quy mô ước tính:** `M`

---

### Task 2: Lọc quy tắc nghiệp vụ theo độ ưu tiên (`precedence`) và ngành (`industry`) từ B0.2 sang B0.3 Prompt
- **Giải quyết lỗi:** `E2E-06` `[REQUIRED]`
- **Mô tả công việc:**
  - Trong [`src/datamate/b0/b03/prompt.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py#L106-L116):
    - Nâng cấp `format_context_for_prompt(context, industry: str | None = None)`:
      - Tự động phát hiện ngành của doanh nghiệp nếu không truyền tường minh (dựa vào `business_metadata` hoặc văn bản các rule có `scope == "business"` nhắc tới tên ngành trong danh mục ngành của `rule_catalog`).
      - Lọc bỏ các quy tắc có `scope == "industry"` thuộc các ngành khác (chỉ giữ lại quy tắc `industry` khớp với ngành của doanh nghiệp, hoặc nếu chưa xác định được ngành thì gắn nhãn `[Ngành: <tên ngành>]` rõ ràng).
      - Khi có nhiều quy tắc cùng `topic` (ví dụ `scope="business"` có `precedence=300` và `scope="split_default"` có `precedence=100`), ưu tiên giữ quy tắc có `precedence` cao nhất để LLM không bị mâu thuẫn công thức.
- **Tiêu chí nghiệm thu (Acceptance Criteria):**
  - [ ] Khi doanh nghiệp có quy tắc `scope="business"` ghi đè cùng `topic` với `scope="split_default"`, prompt chỉ hiển thị quy tắc của doanh nghiệp (precedence cao hơn).
  - [ ] Khi doanh nghiệp thuộc ngành `"Nhà thuốc"`, các quy tắc `scope="industry"` của ngành `"Thời trang"` không bị trộn lẫn vào prompt.
- **Lệnh kiểm chứng (Verification):**
  ```bash
  source .venv/bin/activate && pytest tests/test_b03_text2sql.py tests/test_remediation_b0.py -v
  ```
- **Tệp tác động:**
  - `src/datamate/b0/b03/prompt.py`
  - `tests/test_remediation_b0.py`
- **Quy mô ước tính:** `S`

---

> ### CHECKPOINT 1: Kiểm tra luồng chuẩn bị ngữ cảnh B0.1 → B0.2 → B0.3
> Chạy lệnh: `source .venv/bin/activate && pytest tests/test_ingestion.py tests/test_b03_text2sql.py tests/test_remediation_b0.py -v`

---

### Task 3: Ẩn các cột nội bộ `__dm_*` của B0.1 khi thực thi truy vấn ở B0.4
- **Giải quyết lỗi:** `E2E-07` `[CRITICAL]`
- **Mô tả công việc:**
  - Trong [`src/datamate/b0/b04/engine.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L128-L165):
    - Sau khi thực thi `cursor = con.execute(cleaned_sql)` và đọc `raw_columns = [desc[0] for desc in cursor.description]`:
    - Nếu trong `raw_columns` có ít nhất 1 cột nghiệp vụ (không bắt đầu bằng `"__dm_"`), lọc bỏ tất cả các vị trí cột có tên bắt đầu bằng `"__dm_"` (như `__dm_row_id`, `__dm_source_row`, `__dm_formula_cache`) khỏi danh sách `columns` và từng bản ghi trong `rows`.
- **Tiêu chí nghiệm thu (Acceptance Criteria):**
  - [ ] Thực thi `SELECT * FROM don_hang_...` trên `data.duckdb` do `prepare_business()` tạo ra chỉ trả về các cột nghiệp vụ trong `SchemaCatalog`, hoàn toàn không chứa cột `__dm_row_id`.
- **Lệnh kiểm chứng (Verification):**
  ```bash
  source .venv/bin/activate && pytest tests/test_b0_4_executor.py tests/test_remediation_b0.py -v
  ```
- **Tệp tác động:**
  - `src/datamate/b0/b04/engine.py`
  - `tests/test_remediation_b0.py`
- **Quy mô ước tính:** `XS`

---

### Task 4: Đồng bộ phân loại lỗi Retry (B0.4 ↔ B0.5), Suy luận ngữ nghĩa Tiền tệ/Phần trăm và Xác thực `EvidenceProof` cho `unanswerable`
- **Giải quyết các lỗi:** `E2E-02` `[CRITICAL]`, `E2E-03` `[CRITICAL]`, `E2E-04` `[REQUIRED]`
- **Mô tả công việc:**
  1. **Đồng bộ phân loại lỗi Retry (`E2E-03`)** trong [`src/datamate/b0/b05/retry.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py#L28-L55):
     - Nhánh `SCHEMA_ERROR` (`retryable=True`): Bổ sung `"catalog" in text or "does not exist" in err_msg`.
     - Nhánh `SQL_SYNTAX` (`retryable=True`): Bổ sung `"emptyqueryerror" in err_type or "empty" in err_msg`.
     - Nhánh `SQL_TYPE_ERROR` (`retryable=True`): Bổ sung `"dataerror" in err_type or "out of range" in text or "invalid input" in text`.
  2. **Tự động suy luận `AnswerSemantics` (`E2E-04`)** trong [`src/datamate/b0/b03/types.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L131-L158):
     - Khi `answer_type == "number"` và `numeric_kind` chưa được chỉ định: kiểm tra biểu thức chiếu đầu tiên của câu SQL. Nếu có `COUNT(` -> `"count"`; nếu tính `AVG(` trên cột tiền tệ (`tien`, `gia`, `doanh_thu`, `chi_phi`, `lai`, `no`, `chiet_khau`, `amount`, `cost`, `price`, `revenue`, `profit`) -> `"average_money_vnd"`; nếu tính `SUM(` trên cột tiền tệ -> `"money_vnd"`.
  3. **Xác thực bằng chứng `EvidenceProof` cho câu hỏi `unanswerable` (`E2E-02`)**:
     - Thêm phương thức `Text2SQLResult.to_b05_evidence_proof(context: Any = None) -> EvidenceProof` trong [`src/datamate/b0/b03/types.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py):
       - Khi `self.status == "unanswerable"` và có `context` (chứa `schema_catalog` hợp lệ): trích xuất toàn bộ danh sách `table.column` hiện có vào `available_fields`, kiểm tra `answerability_constraints` (nếu có) và `self.reason`, đánh dấu `source_kind="catalog_verified"`, `capability_status="unsupported"`, `checked_all_sources=True`, và ghi nhận `proof=[{"reason": self.reason, "tables_checked": [...]}]`.
     - Trong [`src/datamate/b0/b05/answerability.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/answerability.py#L33-L39): Nếu `evidence.proof` có chứa `"reason"` cụ thể từ bộ kiểm chứng, ưu tiên sử dụng lý do đó cho `FinalAnswer.reason`.
- **Tiêu chí nghiệm thu (Acceptance Criteria):**
  - [ ] Lỗi `CatalogError: Table with name orders does not exist!` và `DataError` từ B0.4 khi đưa sang B0.5 `classify_error()` đều trả về `retryable=True` (`GateAction.RETRY` ở `attempt=0`).
  - [ ] Câu SQL `SELECT AVG(thanh_tien) FROM don_hang` với `answer_type="number"` tự động suy luận `numeric_kind="average_money_vnd"` và làm tròn `125000.67` thành `125001` ở B0.5.
  - [ ] Khi B0.3 trả về `Text2SQLResult(status="unanswerable", reason="Dữ liệu không có bảng chi phí quảng cáo")` và đối chiếu với `BusinessContext` của B0.2, cổng B0.5 xuất ra `decision="unanswerable"` (`type="unanswerable"`) thay vì hạ xuống `abstain`.
- **Lệnh kiểm chứng (Verification):**
  ```bash
  source .venv/bin/activate && pytest tests/test_error_retry.py tests/test_answerability.py tests/test_remediation_b0.py -v
  ```
- **Tệp tác động:**
  - `src/datamate/b0/b05/retry.py`
  - `src/datamate/b0/b05/answerability.py`
  - `src/datamate/b0/b03/types.py`
  - `tests/test_remediation_b0.py`
- **Quy mô ước tính:** `M`

---

> ### CHECKPOINT 2: Kiểm tra hợp đồng giao tiếp B0.3 ↔ B0.4 ↔ B0.5
> Chạy lệnh: `source .venv/bin/activate && pytest tests/test_remediation_b0.py tests/test_error_retry.py tests/test_answerability.py -v`

---

### Task 5: Xây dựng Bộ Điều Phối End-to-End `B0Pipeline` (`src/datamate/b0/pipeline.py`)
- **Giải quyết lỗi:** `E2E-01` `[CRITICAL]`
- **Mô tả công việc:**
  - Tạo tệp mới [`src/datamate/b0/pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/pipeline.py) định nghĩa lớp `B0Pipeline`:
    - Nhận `model: BaseLLM` (hoặc `generator: Text2SQLGenerator`), thư mục dữ liệu doanh nghiệp hoặc bundle đã chuẩn bị (`prepare_business`), và `writer: SubmissionWriter | None`.
    - Phương thức `answer_question(question: QuestionMeta, context: Any, db_path: str) -> GateOutcome`:
      1. **Attempt 0:** Gọi `generator.generate(context, question.question, question.as_of_date)`.
         - Nếu ném `Text2SQLParseError`: ghi nhận lỗi parse và chuyển sang bước Retry (Attempt 1) với thông báo nhắc trả về đúng định dạng JSON.
         - Nếu `b03_res.status == "unanswerable"`: Tạo `ExecutionResult(status="not_executed")` và `evidence = b03_res.to_b05_evidence_proof(context)`, rồi gọi `evaluate_gate()`.
         - Nếu `b03_res.status == "answerable"`: Gọi `execute_query(ExecutionRequest.from_b03(b03_res, ...))` (B0.4), chuyển sang `evaluate_gate(attempt=0)` (B0.5).
      2. **Bounded Retry (Attempt 1):** Nếu `outcome.action == GateAction.RETRY` và `outcome.repair_request is not None`:
         - Kết hợp `repair_request.error_message` và `repair_request.instruction` truyền vào `generator.repair(context, question.question, question.as_of_date, previous_sql=repair_request.failed_sql, error_message=...)`.
         - Thực thi lại qua B0.4 (`retry_count=1`) và đánh giá qua B0.5 (`attempt=1`).
      3. Nếu có `writer`: tự động gọi `writer.record_attempt(...)` cho mỗi lần thử và `writer.write_final(outcome, ...)` để xuất ra `submission.jsonl` và `logs/`.
  - Xuất `B0Pipeline` trong [`src/datamate/b0/__init__.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/__init__.py).
- **Tiêu chí nghiệm thu (Acceptance Criteria):**
  - [ ] `B0Pipeline` chạy tự động từ dữ liệu thô (`CSV`/`XLSX`/`SQLite` + `README.md`) + `QuestionMeta` -> trả về `GateOutcome` và ghi `submission.jsonl` cho cả 4 trường hợp:
    1. Trả lời đúng ngay lần đầu (`attempt=0` -> `FINAL` / `answer`).
    2. Câu SQL lần 0 bị lỗi `CatalogError` hoặc `SCALAR_SHAPE_MISMATCH` -> tự động gọi `generator.repair()` ở `attempt=1` -> trả về đáp án đúng (`VALID_RESULT_AFTER_RETRY`).
    3. Câu hỏi `unanswerable` -> không gọi DuckDB, xác thực qua `SchemaCatalog` và xuất `type="unanswerable"`.
    4. Câu SQL lỗi ở cả 2 lần (`attempt=0` và `attempt=1`) -> dừng đúng giới hạn 1 lần retry và xuất `type="abstain"` (`RETRY_EXHAUSTED`).
- **Lệnh kiểm chứng (Verification):**
  ```bash
  source .venv/bin/activate && pytest tests/test_b0_e2e_integration.py -v
  ```
- **Tệp tác động:**
  - `src/datamate/b0/pipeline.py` (Tạo mới)
  - `src/datamate/b0/__init__.py`
  - `tests/test_b0_e2e_integration.py`
- **Quy mô ước tính:** `M`

---

### Task 6: Kiểm thử Hồi quy Toàn bộ Hệ thống & Cập nhật Báo cáo Review Sau Sửa Chữa
- **Mô tả công việc:**
  - Bổ sung đầy đủ các bài test cho `E2E-01` .. `E2E-08` vào `tests/test_b0_e2e_integration.py` và `tests/test_remediation_b0.py`.
  - Chạy toàn bộ test suite (`pytest`) đảm bảo 100% PASS.
  - Cập nhật báo cáo đối chiếu trước/sau tại [`docs/review/B0_POST_FIX_REVIEW.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/B0_POST_FIX_REVIEW.md).
- **Tiêu chí nghiệm thu (Acceptance Criteria):**
  - [ ] 100% bài test trong toàn bộ dự án đều PASS, không còn bất kỳ xung đột nào giữa B0.1, B0.2, B0.3, B0.4 và B0.5.
- **Lệnh kiểm chứng (Verification):**
  ```bash
  source .venv/bin/activate && pytest -v
  ```
- **Quy mô ước tính:** `S`

---

## 5. Quản Trị Rủi Ro & Giải Pháp Giảm Thiểu (Risks & Mitigations)

| Rủi ro (Risk) | Mức độ | Giải pháp giảm thiểu (Mitigation) |
| :--- | :---: | :--- |
| **1. Mở khóa khám phá cạnh Join bằng SQL (`E2E-05`) tạo ra các cạnh `uncertain` giả khi 2 cột trùng tên nhưng ít giao thoa** | Trung bình | Trong `DuckDBProfileProvider.check_join()`, bắt buộc độ phủ thực tế trên toàn bảng `max(overlap / ldistinct, overlap / rdistinct) >= 0.8` mới giữ lại cạnh tự suy luận; nếu `< 0.8` hoặc `overlap == 0` thì đánh dấu `invalid` và loại khỏi `join_graph`. |
| **2. Lọc cột `__dm_*` ở B0.4 (`E2E-07`) ảnh hưởng tới các truy vấn kiểm toán nội bộ** | Thấp | Chỉ lọc các cột bắt đầu bằng `"__dm_"` khi trong tập kết quả còn ít nhất 1 cột nghiệp vụ không bắt đầu bằng `"__dm_"`. |
| **3. LLM trả về `unanswerable` ảo (hallucinated unanswerable) cho câu hỏi có thể trả lời** | Trung bình | Chỉ cấp `source_kind="catalog_verified"` khi đã đối chiếu với `SchemaCatalog` của `BusinessContext` (và kiểm tra rằng câu hỏi/lý do không khớp với các cột hiện có hoặc vi phạm `answerability_constraints`). |
