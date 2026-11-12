# Tài Liệu Thay Đổi & Quyết Định Kỹ Thuật (Changelog & ADR)
## Đồng Bộ Tương Thích Giữa B0.1, B0.2 Và Component C Grounding

- **Mã tài liệu:** `ADR-010-B01-B02-GROUNDING-COMPATIBILITY`
- **Ngày thực hiện:** 2026-11-10
- **Trạng thái:** `ACCEPTED` (Đã triển khai và vượt qua 100% test suite)
- **Nhánh áp dụng:** `dev`
- **Tác giả:** UIT Last Dance — DataMate 2026 Team

---

## 1. Bối Cảnh & Động Lực (Context)

Khi nhánh `origin/improvement-b01-b02` được hợp nhất vào nhánh `dev`, tầng Data Foundation (B0.1) và Context Builder (B0.2) đã trải qua đợt nâng cấp kiến trúc lớn nhằm nâng cao độ chính xác khi phân tích quan hệ giữa các bảng:
1. **Phân cấp trạng thái quan hệ JOIN (`JoinEdge.status`)**: B0.1 chuyển từ mô hình nhị phân sang mô hình 4 trạng thái: `"validated"`, `"uncertain"`, `"candidate"`, `"invalid"`. Trong đó, các cạnh chưa qua kiểm chứng (`uncertain`, `candidate`, `invalid`) tuyệt đối không được phép sử dụng trong downstream SQL planning.
2. **Hỗ trợ Khóa Nối Phức Hợp (Composite Equijoin)**: Xuất hiện trường `additional_key_pairs` trong `JoinEdge` cho phép nối 2 bảng qua 2 cột trở lên (ví dụ: `(order_id, line_no)` giữa bảng đơn hàng chi tiết và bảng phân bổ lô kho).
3. **Thống kê toàn bảng (`JoinStatistics`) & Bằng chứng xác thực (`RelationshipEvidence`)**: Ghi nhận tỷ lệ NULL keys, distinct counts, và hash xác thực manifest.
4. **Lược bỏ `profile_rows` khi xuất JSON**: Khi gọi `BusinessContext.to_dict()`, trường `TableMetadata.profile_rows` bị `pop()` để bảo vệ an toàn dữ liệu, toàn bộ dữ liệu mẫu chuyển vào `data_profiling[table]["samples"]`.

Trước thay đổi này, **Component C (Question Grounding)** được xây dựng dựa trên giao diện hợp đồng phẳng của B0.2 ban đầu. Nếu không đồng bộ, Grounding sẽ gặp 4 rủi ro nghiêm trọng khi chạy trên dữ liệu thực tế:
- `B02ContextAdapter` nạp cả các cạnh JOIN `uncertain` hoặc `invalid` do candidate discovery tự sinh, dẫn đến `SchemaGrounder` chọn nhầm đường đi nối bảng chưa được kiểm chứng.
- Mất các cột khóa phụ của quan hệ composite trong gợi ý JOIN gửi sang cho Planner.
- Không đọc được dữ liệu mẫu (`sample_values`) và khoảng thời gian bao phủ (`date_coverage`) khi context được tải từ file JSON nén, làm suy giảm khả năng liên kết giá trị (C4) và kiểm tra khả năng trả lời (C5).
- Không cảnh báo được rủi ro rơi dòng khi câu lệnh SQL thực hiện `INNER JOIN` trên các cột có chứa giá trị `NULL`.

---

## 2. Các Quyết Định Kỹ Thuật & Giải Pháp Chi Tiết (Decisions & Solutions)

```text
┌────────────────────────────────────────────────────────────────────────┐
│                   B0.1 Schema Catalog & B0.2 Context                   │
│   - JoinEdge: status='validated' | 'uncertain' | 'invalid'            │
│   - JoinStatistics: left_null_rows, observed_cardinality               │
│   - data_profiling: samples, observed_min, observed_max               │
│   - schema_mapping: original_name, role (identifier/date/money)        │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                       (B02ContextAdapter.from_dict)
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│                 COMPONENT C: QUESTION GROUNDING ENGINE                 │
│                                                                        │
│  [B02ContextAdapter]                                                   │
│    ├─ Lọc chỉ nhận cạnh status == "validated"                          │
│    ├─ Khôi phục sample_values & date_coverage từ data_profiling        │
│    ├─ Trích xuất vai trò cột (role) & alias tiếng Việt từ provenance   │
│    └─ Tự động tổng hợp MetricSpec từ RuleCatalog & money columns       │
│                                                                        │
│  [C3: SchemaGrounder]                                                  │
│    ├─ Hỗ trợ đảo chiều khóa nối composite (right_col, left_col)        │
│    ├─ Tự động đưa toàn bộ composite keys vào relevant_columns          │
│    └─ Tổng hợp null_key_warning từ JoinStatistics                      │
│                                                                        │
│  [C4: ValueGrounder]                                                   │
│    └─ Quét trực tiếp câu hỏi đối chiếu với sample_values của B0.1      │
│                                                                        │
│  [GroundingToPlannerAdapter]                                           │
│    └─ Render đầy đủ biểu thức JOIN phức hợp (k1 = k1 AND k2 = k2)     │
└────────────────────────────────────────────────────────────────────────┘
```

### Quyết định 1: Lọc trạng thái cạnh JOIN nghiêm ngặt (`status == "validated"`)
- **Vị trí sửa đổi**: `src/datamate/grounding/adapters.py` (`_build_joins`).
- **Nội dung**: Duyệt qua `schema_catalog.join_graph` và chỉ chấp nhận các cạnh có `getattr(edge, "status", "validated") == "validated"`. Mọi cạnh `uncertain`, `candidate`, `invalid` bị loại bỏ khỏi đồ thị `JoinSpec`.
- **Hệ quả**: `SchemaGrounder` chỉ tìm kiếm đường đi qua các quan hệ đã được kiểm chứng bằng chứng từ hoặc SQL profile toàn bảng.

### Quyết định 2: Hỗ trợ Khóa Nối Phức Hợp (Composite Equijoin)
- **Vị trí sửa đổi**:
  - `src/datamate/grounding/protocols.py`: Thêm `additional_key_pairs` và property `key_pairs` vào `JoinSpec`.
  - `src/datamate/grounding/contracts.py`: Thêm `additional_key_pairs` và property `key_pairs` vào `CandidateJoinPath`.
  - `src/datamate/grounding/schema_grounder.py`: Khi duyệt ngược cạnh (`right -> left`) trong BFS, đảo chiều từng cặp `(right_col, left_col)`. Đưa tất cả các cột trong `key_pairs` vào danh sách `relevant_columns`.
  - `src/datamate/grounding/adapters.py`: Trong `GroundingToPlannerAdapter.to_planner_prompt_markdown`, sinh chuỗi `AND` nối tất cả các cặp cột:
    ```markdown
    + Gợi ý JOIN: `allocations.order_id = lines.order_id AND allocations.line_no = lines.line_no` (many_to_one)
    ```

### Quyết định 3: Tích hợp cảnh báo rủi ro rơi dòng do NULL Keys
- **Vị trí sửa đổi**:
  - `src/datamate/grounding/protocols.py`: Thêm `null_key_warning: bool` vào `JoinSpec`.
  - `src/datamate/grounding/adapters.py`: Kiểm tra `edge.statistics.left_null_rows > 0` hoặc `right_null_rows > 0` để bật cờ `null_key_warning`.
  - `src/datamate/grounding/schema_grounder.py`: Khi có cạnh chứa NULL key, bổ sung cảnh báo vào `SelectedSchema.warnings`:
    `"Cảnh báo khóa NULL (null_key_warning): Cột nối có chứa giá trị NULL; INNER JOIN có thể làm rơi dòng, cân nhắc LEFT JOIN."`
  - Render thẻ `[CẢNH BÁO KHÓA NULL - CÂN NHẮC LEFT JOIN]` trong prompt của Planner.

### Quyết định 4: Khôi phục `sample_values` và `date_coverage` từ `data_profiling`
- **Vị trí sửa đổi**: `src/datamate/grounding/adapters.py` (`_build_tables`).
- **Nội dung**:
  - Khi `tbl.profile_rows` bị rỗng (do serialize JSON), adapter tự động chuyển sang đọc `data_profiling[tbl.name]["samples"]`.
  - Đọc `observed_min` và `observed_max` từ `data_profiling[tbl.name]["columns"]` để thiết lập `date_coverage_start` và `date_coverage_end` cho bảng.
- **Hệ quả**: Module C5 (`AnswerabilityPrechecker`) phát hiện chính xác lỗi hỏi ngoài khoảng thời gian dữ liệu (`TEMPORAL_OUT_OF_RANGE`), và C4 (`ValueGrounder`) có đầy đủ dữ liệu mẫu để đối chiếu thực thể.

### Quyết định 5: Ánh xạ vai trò cột (`role`), alias tiếng Việt và tổng hợp `MetricSpec`
- **Vị trí sửa đổi**: `src/datamate/grounding/adapters.py` (`_build_tables`, `_build_metrics`, `_ROLE_MAP`).
- **Nội dung**:
  - Ánh xạ `role` từ `business_metadata["schema_mapping"]`: `identifier` $\rightarrow$ `id`, `date`, `money`, `quantity`, `text`.
  - Trích xuất tên cột gốc tiếng Việt từ `col.provenance` và `original_name` vào `ColumnSpec.aliases` (tự động phân rã tiền tố `"Mã "`, `"Tên "`, `"Số "`).
  - Hàm `_build_metrics()` tự động quét `rule_catalog.rules` kết hợp các cột `money` để sinh `MetricSpec` chuẩn cho doanh nghiệp mà không cần hardcode.
  - `ValueGrounder` được nâng cấp cơ chế quét trực tiếp câu hỏi đối chiếu với `sample_values` (domain-agnostic).

### Quyết định 6: Hỗ trợ nạp trực tiếp từ JSON Dictionary (`B02ContextAdapter.from_dict`)
- **Vị trí sửa đổi**: `src/datamate/grounding/adapters.py`.
- **Nội dung**: Cung cấp classmethod `from_dict(payload)` sử dụng `BusinessContextSchemaReader().read(payload)` của B0.1 để thẩm định chữ ký `RelationshipEvidence` và khởi tạo đối tượng `BusinessContext` chuẩn xác từ file JSON lưu trên đĩa.

---

## 3. Ma Trận Tác Động Tới Các File Mã Nguồn (Code Impact Matrix)

| File Mã Nguồn | Loại Thay Đổi | Mô Tả Thay Đổi Chi Tiết |
| :--- | :---: | :--- |
| `src/datamate/grounding/protocols.py` | Cập nhật contract | Bổ sung `additional_key_pairs`, `null_key_warning`, và property `key_pairs` vào `JoinSpec`. |
| `src/datamate/grounding/contracts.py` | Cập nhật contract | Bổ sung `additional_key_pairs`, `null_key_warning`, và property `key_pairs` vào `CandidateJoinPath`. |
| `src/datamate/grounding/adapters.py` | Nâng cấp Adapter | Thêm `from_dict`, `_build_metrics`, fallback đọc `data_profiling`, lọc `status == "validated"`, cảnh báo NULL keys và format gợi ý JOIN phức hợp. |
| `src/datamate/grounding/schema_grounder.py` | Cải tiến thuật toán | Xử lý đảo chiều khóa nối composite trong BFS, đưa khóa composite vào `relevant_columns`, cộng điểm khi bảng khớp `sample_values`, tổng hợp cảnh báo khóa NULL. |
| `src/datamate/grounding/value_grounder.py` | Cải tiến thuật toán | Quét trực tiếp câu hỏi đối chiếu với giá trị mẫu phi số học (`sample_values`) của bảng B0.1. |
| `tests/grounding/test_b01_b02_compatibility.py` | Thêm mới test suite | 4 test case kiểm chứng toàn diện tính tương thích giữa B0.1, B0.2 và Grounding. |

---

## 4. Kết Quả Kiểm Thử & Xác Minh (Test Verification)

Toàn bộ các bài test đơn vị và tích hợp đã được chạy kiểm thử tự động:
1. **Kiểm thử bộ tương thích mới (`test_b01_b02_compatibility.py`)**:
   - `test_b02_adapter_ignores_unvalidated_join_edges`: **PASSED**
   - `test_b02_adapter_preserves_composite_join_keys_and_null_warnings`: **PASSED**
   - `test_b02_adapter_extracts_samples_date_coverage_and_roles_from_profiling`: **PASSED**
   - `test_e2e_b01_schema_catalog_builder_to_grounding_reverse_composite_traversal`: **PASSED**
2. **Kiểm thử toàn bộ Grounding (`tests/grounding/`)**:
   - **58/58 tests PASSED** trong **0.81s**.
3. **Kiểm thử toàn bộ dự án DataMate (`pytest -q`)**:
   - **336 passed, 3 skipped, 15 subtests passed** trong **12.30s**.
   - **0 hồi quy (Zero Regressions)** trên toàn bộ hệ thống B0.1, B0.2, B0.3, B0.4, B0.5.

