# Báo Cáo & Tóm Tắt Toàn Bộ Test Cases Module B0.1 (Data Loader & Schema/Join Catalog)

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Vị trí tài liệu:** `docs/test/b0/b01/TEST_CASES_SUMMARY.md`  
**Ngày thực thi kiểm thử:** 2026-11-05  
**Môi trường:** Python 3.12.3, Pytest 9.2.0, Linux WSL (x86_64)

---

## 1. Tổng Quan Kết Quả Kiểm Thử (Executive Summary)

Module **B0.1 Data Loader & Schema/Join Catalog** được bảo vệ và kiểm chứng toàn diện qua **22 bài test tự động (Automated Tests)**, kiểm tra cặn kẽ tính năng nạp metadata JSON, suy luận khóa chính/khóa ghép, phát hiện fanout trong quan hệ nhiều-nhiều, và điều hướng BFS trên đồ thị join.

```text
============================= TEST EXECUTION SUMMARY (B0.1) =============================
Total Test Suites:            4 files (test_semantic_modules, test_metadata_resolution,
                                       test_composite_and_formulas, test_metadata_entrypoint)
Total B0.1 Test Cases:        22 tests
Passed:                       22 / 22 tests (100%)
Failed:                       0
Skipped / XFailed:            0
Total Execution Time:         ~0.05 seconds (100% offline, zero-network, deterministic)
Status:                       PASSED (All quality gates satisfied)
=========================================================================================
```

---

## 2. Chi Tiết Các Bộ Kiểm Thử Của Module B0.1

### 2.1. Kiểm Thử Suy Luận Khóa & Phân Tích Grain (`KeyEvidenceTests`)

Đảm bảo hệ thống chỉ công nhận khóa chính khi có đầy đủ bằng chứng thống kê, không bao giờ lấy cột chứa NULL làm khóa chính, và nhận diện chính xác khóa ghép.

| Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|---|---|:---:|:---:|
| `test_declared_fk_requires_complete_coverage_and_correct_cardinality` | Khóa ngoại khai báo bắt buộc phải có độ bao phủ giá trị 100% và đúng bản số cardinality. | **PASSED** | < 0.005s |
| `test_documented_grain_is_preserved` | Bảo tồn nguyên vẹn ý nghĩa dòng dữ liệu (`grain`) đã được tài liệu hóa từ Data Foundation. | **PASSED** | < 0.005s |
| `test_inconsistent_complete_flag_does_not_prove_full_table_key` | Cờ `complete` không nhất quán với `row_count` sẽ không được chứng minh là khóa toàn bảng. | **PASSED** | < 0.005s |
| `test_minimal_composite_key_supplies_structural_grain` | Khóa ghép tối thiểu cung cấp bằng chứng cấu trúc cho `grain` của bảng. | **PASSED** | < 0.005s |
| `test_null_or_missing_key_cells_never_prove_uniqueness` | Bất kỳ cột hoặc tuple nào chứa ô `NULL`/trống tuyệt đối không thể làm khóa chính. | **PASSED** | < 0.005s |
| `test_sample_only_composite_and_duplicate_declared_key_remain_uncertain` | Khóa ghép chỉ dựa trên tập mẫu (sample) hoặc bị trùng lặp khai báo phải giữ trạng thái `uncertain`. | **PASSED** | < 0.005s |

---

### 2.2. Kiểm Thử Khám Phá Schema & Quan Hệ Join (`SchemaCatalogTests`)

Kiểm tra khả năng phân tích bảng, cột, kiểu dữ liệu và tự động phát hiện quan hệ giữa các bảng.

| Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|---|---|:---:|:---:|
| `test_column_name_match_without_profile_does_not_create_join` | Trùng tên cột nhưng thiếu dữ liệu profile chứng minh sẽ **không** tự ý tạo quan hệ join. | **PASSED** | < 0.005s |
| `test_declared_join_is_candidate_and_invalid_reference_is_warning` | Quan hệ khai báo trở thành `candidate`, nếu tham chiếu tới bảng/cột không tồn tại sẽ cảnh báo `warning`. | **PASSED** | < 0.005s |
| `test_different_column_names_can_form_uncertain_candidate_from_values` | Cột khác tên nhưng có giá trị khớp nhau tạo thành ứng viên `uncertain`. | **PASSED** | < 0.005s |
| `test_many_to_many_relationship_warns_about_fanout` | Quan hệ Many-to-Many tự động kích hoạt cảnh báo nguy cơ nhân bản dòng (`fanout_warning = True`). | **PASSED** | < 0.005s |
| `test_primary_key_can_be_inferred_from_complete_profile_statistics` | Khóa chính đơn được chứng minh tự động nếu thống kê profile đầy đủ xác nhận 100% unique. | **PASSED** | < 0.005s |
| `test_primary_key_candidate_requires_non_null_unique_profile` | Ứng viên khóa chính bắt buộc phải thỏa mãn 2 điều kiện: không NULL và hoàn toàn phân biệt. | **PASSED** | < 0.005s |
| `test_relationship_candidates_include_cardinality_and_fanout_warning` | Các ứng viên quan hệ phải xác định đúng cardinality (`one_to_one`, `one_to_many`, `many_to_many`). | **PASSED** | < 0.005s |

---

### 2.3. Kiểm Thử Đồ Thị Join & Khóa Ghép Phức Tạp (`CompositeJoinTests`)

Kiểm tra tính năng điều hướng đồ thị join (BFS) và biên dịch biểu thức equijoin trên nhiều cặp cột khóa ghép.

| Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|---|---|:---:|:---:|
| `test_individual_values_do_not_prove_tuple_referential_coverage` | Khớp từng giá trị cột riêng lẻ không chứng minh được độ bao phủ của toàn bộ tuple khóa ghép. | **PASSED** | < 0.005s |
| `test_only_validated_paths_are_available` | `JoinGraphNavigator.find_path()` chỉ cho phép đi qua các cạnh đã được xác nhận (`validated`). | **PASSED** | < 0.005s |
| `test_same_name_composite_identity_produces_uncertain_candidate` | Cặp bảng trùng tên các cột khóa ghép tạo ra ứng viên `uncertain` an toàn. | **PASSED** | < 0.005s |
| `test_tuple_join_is_validated_and_executes_without_cross_product` | Phép join khóa ghép được xác thực thực thi chính xác trên database mà không sinh tích Descartes. | **PASSED** | < 0.005s |
| `test_unknown_composite_column_is_rejected_by_contract` | Hợp đồng từ chối mọi cạnh join tham chiếu tới cột khóa ghép không tồn tại trong schema. | **PASSED** | < 0.005s |

---

### 2.4. Kiểm Thử Bộ Chuyển Đổi Metadata JSON (`MetadataBoundaryTests`)

Thẩm định tính toàn vẹn của lớp Anti-Corruption Layer tiếp nhận metadata JSON từ Data Foundation.

| Tên Test Case | Mục đích & Điều kiện kiểm thử | Kết quả | Thời gian |
|---|---|:---:|:---:|
| `test_provider_rejects_bad_profile_types_counts_and_relationships` | Bắt lỗi và từ chối các file JSON có kiểu dữ liệu profile sai lệch hoặc số đếm âm. | **PASSED** | < 0.005s |
| `test_provider_rejects_invalid_version_scope_and_unknown_fields` | Từ chối file có `metadata_version != "1.0"`, sai lệch `business_id` hoặc chứa trường lạ. | **PASSED** | < 0.005s |
| `test_service_preserves_producer_metadata_and_document_warnings` | Bảo tồn nguyên vẹn siêu dữ liệu của producer và chuyển đổi tài liệu thiếu thành cảnh báo an toàn. | **PASSED** | < 0.005s |
| `test_b01_exports` | Kiểm tra toàn bộ các lớp của B0.1 được export đúng chuẩn tại `datamate.b0.b01`. | **PASSED** | < 0.005s |

---

## 3. Lệnh Tái Hiện Kiểm Thử B0.1

```bash
# Kích hoạt môi trường ảo
source .venv/bin/activate

# Chạy toàn bộ các test cases của B0.1
pytest tests/test_semantic_modules.py -k "SchemaCatalog" -v
pytest tests/test_metadata_resolution.py -k "KeyEvidence" -v
pytest tests/test_composite_and_formulas.py -k "CompositeJoin" -v
pytest tests/test_b01_b02_modular_imports.py -k "b01" -v
```

