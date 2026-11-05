# Kiến Trúc Module B0.1: Data Loader & Schema/Join Catalog

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Tài liệu:** `docs/architecture/B0_1_LOADER_ARCHITECTURE.md`  
**Phiên bản:** `b01.v1.0`  
**Trạng thái:** Production-Ready / Fully Tested

---

## 1. Tổng Quan & Vai Trò Trong Pipeline Baseline B0

Trong kiến trúc tổng thể **Baseline B0 (Direct Text-to-SQL)**, module **B0.1 Loader** giữ vai trò "Cánh cổng tiếp nhận dữ liệu đầu vào" (Input Ingestion & Schema Profiling Layer).

```text
========================================================================================================================
[NGUỒN DỮ LIỆU ĐẦU VÀO]               [MODULE B0.1: LOADER & CATALOG]                [HẠ NGUỒN TIẾP NHẬN (DOWNSTREAM)]
========================================================================================================================

┌────────────────────────────┐
│   Metadata JSON v1.0       │───────┐
│ (Data Foundation producer) │       │
└────────────────────────────┘       ▼
                              ┌─────────────────────────────────────┐
┌────────────────────────────┐│        metadata_adapter.py          │
│   Table Profiles & Samples ││       (JSONMetadataProvider)        │
│    (Row counts, nulls)     │└──────────────────┬──────────────────┘
└────────────────────────────┘                   │
                                                 ▼
                              ┌─────────────────────────────────────┐                ┌────────────────────────────────┐
                              │         schema_catalog.py           │───────────────►│  B0.2 Context Extractor        │
                              │       (SchemaCatalogBuilder)        │                │  (Schema + Rules Prompt)       │
                              └──────────┬──────────────────────┬───┘                └────────────────────────────────┘
                                         │                      │
                                         ▼                      │                    ┌────────────────────────────────┐
                              ┌─────────────────────────────────┐│ (Catalog Proof)   │  B0.5 Output Gate              │
                              │          join_graph.py          │└ - - - - - - - - -►│  (Answerability Verification)  │
                              │ (JoinGraphNavigator & BFS Path) │                    └────────────────────────────────┘
                              └──────────────────┬──────────────┘
                                                 │                                   ┌────────────────────────────────┐
                                                 └──────────────────────────────────►│  B0.3 Text-to-SQL LLM          │
                                                    (Validated Equijoin Predicates)  │  (Join Clauses & Aliases)      │
                                                                                     └────────────────────────────────┘
========================================================================================================================
```

### Nhiệm Vụ Trọng Tâm Của B0.1:
1. **Tiếp nhận Metadata an toàn (Strict Adapter Boundary)**: Nhận payload JSON từ Data Foundation (version `1.0`), kiểm tra đúng business scope, kiểu dữ liệu, bắt lỗi định dạng mà không tự tiện ép kiểu hay thay đổi dữ liệu gốc.
2. **Khám phá Khóa chính & Bản chất dòng (Primary Key & Grain Analysis)**:
   - Thẩm định candidate key đơn cột và khóa ghép (composite keys) dựa trên dữ liệu profile có bằng chứng (`evidence`).
   - Giữ nguyên `grain` khai báo hoặc suy luận `grain` cấu trúc nếu có đầy đủ bằng chứng thống kê.
3. **Xây dựng Đồ thị Join & Cảnh báo Fanout (Join Graph & Equijoin Predicates)**:
   - Phát hiện các cặp quan hệ tiềm năng giữa các bảng dựa trên trùng tên cột hoặc dữ liệu profile.
   - Thẩm định toàn bộ tuple khóa ghép, kiểm tra cardinality (1-1, 1-N, N-N).
   - Gắn cờ cảnh báo nhân bản dòng (`fanout_warning = True`) đối với quan hệ Many-to-Many để cảnh báo B0.3 Text-to-SQL không viết câu lệnh join gây sai lệch số liệu sum/count.
4. **Cung cấp Bằng chứng Khả năng trả lời (Answerability Proof for B0.5)**:
   - Nếu một câu hỏi yêu cầu bảng/cột không hề tồn tại trong `SchemaCatalog`, B0.1 cung cấp bằng chứng `catalog_verified` để B0.5 tự tin kết luận `unanswerable` mà không bị trừ điểm PA (-1 điểm).

---

## 2. Hợp Đồng Dữ Liệu Lõi (Data Contracts)

Tất cả các thực thể trong B0.1 đều là các `dataclass(frozen=True)` bất biến, ngăn chặn mọi hành vi chỉnh sửa trạng thái ngầm:

| Lớp (Class) | Ý nghĩa nghiệp vụ | Các trường cốt lõi |
|---|---|---|
| `ColumnMetadata` | Siêu dữ liệu từng cột | `name`, `data_type`, `nullable`, `null_ratio`, `cardinality`, `provenance` |
| `TableMetadata` | Siêu dữ liệu bảng & mẫu profile | `name`, `columns`, `row_count`, `grain`, `primary_key_candidates`, `composite_key_candidates`, `grain_evidence`, `profile_rows` |
| `KeyCandidate` | Khóa chính đề xuất | `table`, `columns`, `key_type`, `status` (`candidate` / `uncertain`), `confidence`, `evidence` |
| `JoinEdge` | Cạnh quan hệ giữa 2 bảng | `left_table`, `left_column`, `right_table`, `right_column`, `cardinality`, `status` (`candidate` / `validated`), `additional_key_pairs`, `fanout_warning` |
| `SchemaCatalog` | Danh mục schema toàn diện | `tables`, `key_candidates`, `join_graph`, `warnings` |

---

## 3. Kiến Trúc Chi Tiết Các Tệp Mã Nguồn

### 3.1. `metadata_adapter.py` — Bộ chuyển đổi Metadata JSON
* **Mục tiêu**: Đóng vai trò lớp phòng thủ biên giới (Anti-Corruption Layer).
* **Cơ chế**:
  * Định nghĩa trừu tượng `BaseMetadataProvider(ABC)` với phương thức `load(business_id: str) -> FoundationMetadata`.
  * `JSONMetadataProvider` hiện thực việc đọc file JSON, thẩm định `metadata_version == "1.0"`, kiểm tra `business_id` khớp yêu cầu.
  * Bóc tách các trường tùy chọn: `data_profiling`, `business_metadata`, `answerability_constraints`.

### 3.2. `schema_catalog.py` — Trình xây dựng Catalog & Suy luận Khóa
* **Mục tiêu**: Xây dựng cấu trúc bảng và chứng minh tính duy nhất (Uniqueness) của khóa.
* **Quy tắc vàng**:
  * *Không có dữ liệu profile ➔ Không kết luận bừa*: Nếu không có `profile_rows` hoàn chỉnh (`profile_is_complete == True`), candidate key chỉ được đánh dấu là `uncertain`.
  * *Bỏ qua giá trị NULL*: Cột chứa NULL không bao giờ có thể làm khóa chính.
  * *Khóa ghép (Composite Keys)*: Kiểm tra toàn bộ tuple giá trị, tối đa xét 64 tổ hợp khả dĩ để tránh bùng nổ tổ hợp (combinatorial explosion).

### 3.3. `join_graph.py` — Đồ thị Quan hệ & Biên dịch Mệnh đề Join
* **Mục tiêu**: Điều hướng đường đi ngắn nhất giữa các bảng và sinh biểu thức SQL JOIN chuẩn xác.
* **Thành phần**:
  * `JoinGraphNavigator`: Sử dụng thuật toán BFS (Breadth-First Search) duyệt đồ thị chỉ qua các cạnh có `status == "validated"`.
  * `JoinPredicateCompiler`: Biên dịch cặp khóa (đơn hoặc ghép) thành biểu thức equijoin an toàn, ví dụ:
    `"sales.order_id = orders.id AND sales.branch_id = orders.branch_id"`.

---

## 4. Tương Tác & Đồng Bộ Với Module B0.5 Basic Output Gate

1. **Bảo vệ điểm PA (Unanswerable Verification)**:
   Khi truy vấn câu hỏi người dùng cần tìm kiếm một cột (ví dụ `profit_margin`), B0.1 đối chiếu `SchemaCatalog`. Nếu cột không tồn tại và không thể tính toán từ các cột hiện có:
   * B0.1 phát sinh cảnh báo `MISSING_COLUMN`.
   * Cung cấp bằng chứng nguồn `catalog_verified`.
   * Chuyển tiếp tới B0.5 để B0.5 chốt kết quả `unanswerable` hợp lệ (tránh bị ban tổ chức phạt -1 điểm).
2. **Khử trùng lặp dòng (Fanout Avoidance)**:
   Nếu `JoinEdge.fanout_warning == True`, B0.1 gắn cờ cảnh báo. Khi B0.4 thực thi và B0.5 kiểm tra ma trận dòng kết quả (`validate_execution`), nếu phát hiện số dòng nhân lên bất thường, B0.5 sẽ từ chối kết quả và kích hoạt Bounded Retry để yêu cầu LLM sửa lại logic GROUP BY / DISTINCT.

