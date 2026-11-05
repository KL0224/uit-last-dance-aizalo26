# Giải Thích Mã Nguồn: `contracts.py` (B0.1)

**Đường dẫn file:** `src/datamate/b0/b01/contracts.py`  
**Thuộc module:** B0.1 Data Loader & Schema/Join Catalog  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `contracts.py` định nghĩa "Bản hợp đồng dữ liệu" (Data Contracts & Schemas) mô tả cấu trúc vật lý và logic của toàn bộ cơ sở dữ liệu. Nó bao gồm định nghĩa về cột, bảng, khóa chính, quan hệ khóa ngoại (join edge) và danh mục lược đồ (schema catalog).

---

## 2. Chi Tiết Các Lớp Dữ Liệu

### 2.1. `ColumnMetadata`
* **Mục đích**: Lưu thông tin chi tiết của 1 cột trong bảng.
* **Các trường**:
  * `name`: Tên cột (bắt buộc, không được để trống).
  * `data_type`: Kiểu dữ liệu vật lý (mặc định `"unknown"`).
  * `nullable`: Cột có chứa NULL hay không.
  * `null_ratio`: Tỷ lệ phần trăm giá trị NULL (từ 0.0 đến 1.0).
  * `cardinality`: Số lượng giá trị phân biệt (distinct values).
  * `provenance`: Nguồn gốc trích xuất metadata.

### 2.2. `TableMetadata`
* **Mục đích**: Mô tả 1 bảng và các đặc tính thống kê.
* **Các trường**:
  * `name`: Tên bảng duy nhất.
  * `columns`: Tuple các đối tượng `ColumnMetadata`.
  * `row_count`: Tổng số dòng của bảng.
  * `grain`: Ý nghĩa thực tế của mỗi dòng (ví dụ: *"mỗi dòng là một sản phẩm trong đơn hàng"*).
  * `primary_key_candidates`: Danh sách các candidate key đơn cột.
  * `composite_key_candidates`: Mảng các nhóm cột tạo thành khóa ghép.
  * `profile_rows`: Tập mẫu dữ liệu nội bộ phục vụ việc chứng minh tính duy nhất (repr=False để không in rác log).
  * `profile_is_complete`: Cờ đánh dấu tập profile có phải là toàn bộ bảng hay không.

### 2.3. `KeyCandidate`
* **Mục đích**: Đại diện cho một ứng viên khóa chính được phát hiện.
* **Các trường**:
  * `table`, `columns`, `key_type` (`primary` / `composite`).
  * `status`: Trạng thái (`candidate` khi đã có bằng chứng, `uncertain` nếu chỉ là mẫu dữ liệu nhỏ).
  * `confidence`: Độ tin cậy (0.0 đến 1.0).
  * `evidence`: Bằng chứng thống kê (ví dụ: *"profile_unique_100_percent"*).

### 2.4. `JoinEdge`
* **Mục đích**: Mô tả mối quan hệ giữa 2 bảng.
* **Các trường**:
  * `left_table`, `left_column`, `right_table`, `right_column`.
  * `cardinality`: Bản số (`one_to_one`, `one_to_many`, `many_to_many`).
  * `status`: `candidate` hoặc `validated`.
  * `fanout_warning`: `True` nếu là quan hệ N-N có nguy cơ nhân bản dòng kết quả.
  * `additional_key_pairs`: Lưu các cặp cột bổ sung đối với quan hệ khóa ghép.
  * Thuộc tính `key_pairs`: Trả về toàn bộ danh sách cặp cột `(left_col, right_col)`.

### 2.5. `SchemaCatalog`
* **Mục đích**: Vỏ bọc tổng hợp chứa danh sách tất cả các bảng, các khóa ứng viên và đồ thị join của một doanh nghiệp.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Sử dụng `@dataclass(frozen=True)`**:
   Tất cả các đối tượng hợp đồng đều là bất biến (immutable). Bất kỳ hành vi thay đổi thuộc tính nào (như `table.name = "new"`) đều sẽ ném lỗi `FrozenInstanceError`. Điều này bảo vệ pipeline khỏi các lỗi side-effect ngầm khi chạy đa luồng hoặc truyền qua nhiều module.
2. **Hỗ trợ Khóa ghép (Composite Keys) chuẩn mực**:
   Nhiều bảng dữ liệu trong thực tế kinh doanh (ví dụ bảng `chi_tiet_don_hang`) có khóa chính gồm `(order_id, item_id)`. Bằng cách thiết kế `additional_key_pairs` và thuộc tính `key_pairs`, B0.1 xử lý khóa ghép tự nhiên mà vẫn giữ tương thích ngược với API khóa đơn cột (`left_column`, `right_column`).

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Module B0.2**: Lớp `ContractBuilder` của B0.2 sử dụng `SchemaCatalog` để kiểm tra chéo: các trường yêu cầu trong Business Rule có tồn tại trong các bảng của SchemaCatalog hay không.
* **Module B0.3**: Cung cấp cấu trúc bảng và đường join chính xác để LLM viết đúng cú pháp SQL.

---

## 5. Nếu Không Có File Này Thì Sao?

* Hệ thống sẽ không có định nghĩa kiểu dữ liệu thống nhất, buộc các module phải tự truyền nhau các dictionary thô (dict of dicts).
* Dễ phát sinh lỗi `KeyError`, không thể kiểm tra lỗi kiểu dữ liệu trước khi chạy (Type Check via MyPy/Pyright).

