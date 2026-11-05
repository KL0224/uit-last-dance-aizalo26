# Báo Cáo & Tóm Tắt Toàn Bộ Test Cases Module B0.2 (Context Extractor & Business Rules)

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Vị trí tài liệu:** `docs/test/b0/b02/TEST_CASES_SUMMARY.md`  
**Ngày thực thi kiểm thử:** 2026-11-05  
**Môi trường:** Python 3.12.3, Pytest 9.2.0, Linux WSL (x86_64)

---

## 1. Tổng Quan Kết Quả Kiểm Thử (Executive Summary)

Module **B0.2 Context Extractor & Business Rules** được kiểm thử tự động toàn diện qua **23 bài test tự động (Automated Tests)**, kiểm tra cặn kẽ thuật toán băm SHA-256 rule ID, thang bậc ưu tiên 4 cấp (100–400), cơ chế khóa topic khi có xung đột, gắn kết công thức miền (Doanh thu, Lãi gộp, Bán chạy), và đóng gói `BusinessContext`.

```text
============================= TEST EXECUTION SUMMARY (B0.2) =============================
Total Test Suites:            5 files (test_semantic_modules, test_metadata_resolution,
                                       test_composite_and_formulas, test_metadata_entrypoint,
                                       test_b01_b02_modular_imports)
Total B0.2 Test Cases:        23 tests
Passed:                       23 / 23 tests (100%)
Failed:                       0
Skipped / XFailed:            0
Total Execution Time:         ~0.05 seconds (100% offline, zero-network, deterministic)
Status:                       PASSED (All quality gates satisfied)
=========================================================================================
```

---

## 2. Chi Tiết Các Bộ Kiểm Thử Của Module B0.2

### 2.1. Kiểm Thử Biên Dịch Quy Tắc & Ngôn Ngữ DSL (`RuleCompilerTests`)

Đảm bảo văn bản Markdown được số hóa chính xác, sinh hash ID ổn định và biên dịch DSL sang SQL có tham số hóa.

| Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|---|---|:---:|:---:|
| `test_ambiguous_unqualified_field_is_rejected` | Bắt lỗi và từ chối trường không tường minh xuất hiện ở nhiều bảng mà không có tên bảng tiền tố. | **PASSED** | < 0.005s |
| `test_conflicting_topic_is_marked_for_review` | Đánh dấu chủ đề bị mâu thuẫn để chuyển sang trạng thái cần rà soát (`for_review`). | **PASSED** | < 0.005s |
| `test_markdown_ingestion_is_stable_and_preserves_provenance` | Quá trình đọc Markdown bảo toàn 100% nguồn gốc tài liệu và sinh ID băm SHA-256 tất định. | **PASSED** | < 0.005s |
| `test_missing_field_and_unsupported_operator_are_rejected` | Từ chối biên dịch nếu rule yêu cầu cột không có trong DB hoặc chứa toán tử DSL không hỗ trợ. | **PASSED** | < 0.005s |
| `test_rule_precedence_and_industry_subheading_scope` | Tự động gán đúng scope `industry` (mức 200) khi đoạn văn nằm dưới tiêu đề ngành hàng tương ứng. | **PASSED** | < 0.005s |
| `test_structured_expression_is_parameterized` | Biểu thức có cấu trúc được biên dịch thành SQL fragment với các tham số ràng buộc (`?`), chống SQL injection. | **PASSED** | < 0.005s |

---

### 2.2. Kiểm Thử Thang Bậc Ưu Tiên & Phân Xử Xung Đột (`RuleResolutionTests`)

Kiểm tra thuật toán chọn rule có precedence cao nhất và cơ chế khóa cứng topic mâu thuẫn.

| Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|---|---|:---:|:---:|
| `test_catalog_isolation_and_unscoped_business_rules` | Cô lập danh mục quy tắc theo từng doanh nghiệp, không để lọt quy tắc của shop khác. | **PASSED** | < 0.005s |
| `test_conflicting_highest_priority_blocks_instead_of_fallback` | Hai quy tắc cùng đạt điểm ưu tiên cao nhất nhưng mâu thuẫn nhau sẽ **khóa topic lại**, không tự ý chọn bừa. | **PASSED** | < 0.005s |
| `test_conflicting_rule_cannot_be_compiled` | Quy tắc đang bị khóa xung đột sẽ bị chặn không cho phép biên dịch sang SQL. | **PASSED** | < 0.005s |
| `test_invalid_highest_rule_is_not_silently_replaced` | Quy tắc cao nhất bị lỗi (`invalid`) sẽ **không** bị âm thầm thay thế bởi quy tắc thấp hơn. | **PASSED** | < 0.005s |
| `test_scope_filtering_happens_before_precedence` | Quá trình lọc theo scope diễn ra **trước** khi tính điểm precedence, tránh rò rỉ rule shop khác. | **PASSED** | < 0.005s |
| `test_last_table_rule_before_blank_line_is_not_discarded` | Quy tắc nằm ở dòng cuối cùng của bảng Markdown trước dòng trắng không bị bỏ sót khi parse. | **PASSED** | < 0.005s |

---

### 2.3. Kiểm Thử Gắn Kết Công Thức Nghiệp Vụ Chuẩn (`FormulaExecutionTests`)

Kiểm tra 3 công thức tài chính: Doanh thu, Lãi gộp và Bán chạy theo đơn vị cơ bản.

| Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|---|---|:---:|:---:|
| `test_distinct_orders_counts_entity_instead_of_lines` | Đếm số lượng đơn hàng phân biệt (`COUNT(DISTINCT order_id)`) thay vì đếm số dòng chi tiết. | **PASSED** | < 0.005s |
| `test_fractional_division_and_zero_denominator` | Xử lý an toàn phép chia số lẻ và trường hợp mẫu số bằng 0 (tránh crash ZeroDivisionError). | **PASSED** | < 0.005s |
| `test_gross_profit_formula_uses_fields_and_preserves_nulls` | Công thức Lãi gộp sử dụng đúng giá vốn ghi nhận tại dòng bán và bảo toàn giá trị NULL. | **PASSED** | < 0.005s |
| `test_nested_aggregate_and_non_scalar_parameters_are_rejected` | Từ chối các hàm tổng hợp lồng nhau (nested aggregates) hoặc tham số phi vô hướng không hợp lệ. | **PASSED** | < 0.005s |

---

### 2.4. Kiểm Thử Hợp Đồng Ngữ Cảnh Kinh Doanh (`ContractTests`)

Thẩm định quy trình ghép nối và kiểm tra chéo của `ContractBuilder`.

| Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|---|---|:---:|:---:|
| `test_context_rejects_edges_to_missing_columns` | Từ chối tạo context nếu có cạnh join tham chiếu tới cột không hề có trong danh mục bảng. | **PASSED** | < 0.005s |
| `test_context_rejects_rule_catalog_from_another_business` | Từ chối ghép nối nếu `business_id` của `RuleCatalog` không khớp với `BusinessContext`. | **PASSED** | < 0.005s |
| `test_context_serializes_with_version_and_keeps_missing_metadata_null` | Tuần tự hóa JSON đúng chuẩn version `1.0`, giữ nguyên các trường chưa có ở trạng thái `null`. | **PASSED** | < 0.005s |
| `test_end_to_end_business_context_combines_b01_and_b02` | Kết hợp hoàn hảo toàn bộ đầu ra của B0.1 và B0.2 thành một Business Context duy nhất. | **PASSED** | < 0.005s |
| `test_rule_precedence_values_are_explicit_in_context` | Giá trị điểm ưu tiên số học được ghi nhận tường minh trong từng quy tắc của context. | **PASSED** | < 0.005s |

---

### 2.5. Kiểm Thử CLI Entrypoint & Modular Exports

| Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|---|---|:---:|:---:|
| `test_cli_outputs_json_and_reports_errors_without_partial_stdout` | CLI `python -m datamate` xuất JSON chuẩn ra stdout và thông báo lỗi ra stderr mà không in rác. | **PASSED** | < 0.005s |
| `test_b02_exports` | Kiểm tra toàn bộ các lớp của B0.2 được export đúng chuẩn tại package `datamate.b0.b02`. | **PASSED** | < 0.005s |

---

## 3. Lệnh Tái Hiện Kiểm Thử B0.2

```bash
# Kích hoạt môi trường ảo
source .venv/bin/activate

# Chạy toàn bộ các test cases của B0.2
pytest tests/test_semantic_modules.py -k "RuleCompiler or Contract" -v
pytest tests/test_metadata_resolution.py -k "RuleResolution or RuleIngestion" -v
pytest tests/test_composite_and_formulas.py -k "FormulaExecution" -v
pytest tests/test_b01_b02_modular_imports.py -k "b02" -v
```

