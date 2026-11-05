# Giải Thích Mã Nguồn: `schema_catalog.py` (B0.1)

**Đường dẫn file:** `src/datamate/b0/b01/schema_catalog.py`  
**Thuộc module:** B0.1 Data Loader & Schema/Join Catalog  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `schema_catalog.py` là **Bộ máy phân tích Schema và Suy luận Khóa Chính/Khóa Ghép** của hệ thống. 

Từ danh sách bảng thô do `metadata_adapter` cung cấp, module này tiến hành:
1. Thẩm định tính duy nhất của các candidate key đơn cột và đa cột.
2. Xác định bản chất dòng dữ liệu (`grain`) và bằng chứng hỗ trợ (`grain_evidence`).
3. Khám phá các mối quan hệ liên kết tiềm năng giữa các bảng và phát hiện nguy cơ nhân bản dòng (Fanout Warning).

---

## 2. Chi Tiết Lớp & Logic Thuật Toán Lõi

### 2.1. Lớp `SchemaCatalogBuilder`
* Phương thức chính: `build(tables: list[TableMetadata], declared_edges: list[JoinEdge] | None = None) -> SchemaCatalog`.
* Quy trình thực hiện:
  1. Kiểm tra tính duy nhất của tên bảng trong toàn bộ database.
  2. Với mỗi bảng, gọi hàm nội bộ `_infer_keys(table, warnings)` để tìm kiếm candidate keys.
  3. Duyệt cặp bảng chéo (cross-table) để tìm các cạnh quan hệ join ứng viên (`_infer_relationships()`).
  4. Đóng gói kết quả thành đối tượng `SchemaCatalog`.

### 2.2. Thuật toán Suy luận Khóa Đơn & Khóa Ghép (`_infer_keys`)
* **Khóa đơn**:
  * Nếu bảng có khai báo `primary_key_candidates`, kiểm tra dữ liệu mẫu `profile_rows`.
  * Nếu cột chứa bất kỳ giá trị `NULL` nào ➔ **Loại bỏ ngay**, vì khóa chính không được phép NULL.
  * Nếu số lượng giá trị duy nhất bằng đúng số dòng (`len(unique_values) == row_count`) và `profile_is_complete == True` ➔ Xác nhận trạng thái `candidate` với `confidence = 1.0`.
* **Khóa ghép (Composite Keys)**:
  * Xét các tổ hợp 2 hoặc nhiều cột (`itertools.combinations`).
  * Giới hạn tối đa **64 tổ hợp** khả dĩ (`islice(..., 64)`) để ngăn chặn bùng nổ tổ hợp với các bảng có hàng trăm cột.
  * Kiểm tra tính duy nhất trên toàn bộ tuple giá trị `(val_col1, val_col2, ...)`. Bất kỳ tuple nào chứa phần tử `None` đều bị loại khỏi tập khóa.

### 2.3. Thuật toán Phát hiện Fanout Warning trong Quan Hệ Join
* Khi phát hiện quan hệ giữa 2 bảng:
  * Nếu phía bảng trái không có khóa duy nhất VÀ phía bảng phải cũng không có khóa duy nhất ➔ Đánh dấu `cardinality = "many_to_many"` và gán cờ `fanout_warning = True`.
  * *Ý nghĩa*: Cảnh báo các module phía sau rằng phép JOIN này có thể nhân đôi/nhân ba số dòng, làm sai lệch hàm `SUM()` hoặc `COUNT()`.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Nguyên tắc Chứng Minh Dựa Trên Bằng Chứng (Evidence-based)**:
   Hệ thống không bao giờ "đoán mò" khóa chính chỉ vì một cột có tên là `id`. Nó đòi hỏi phải có bằng chứng từ `profile_rows` hoặc khai báo có cơ sở từ Data Foundation. Nếu thiếu bằng chứng, trạng thái được giữ là `uncertain`.
2. **Loại bỏ `profile_rows` trước khi xuất bản**:
   Dữ liệu mẫu `profile_rows` chỉ dùng nội bộ để chứng minh tính duy nhất, sau đó bị loại bỏ khỏi `BusinessContext` JSON đầu ra nhằm đảm bảo an toàn bảo mật dữ liệu.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Module B0.2**: Cung cấp danh mục bảng và cột hợp lệ để B0.2 kiểm tra tính hợp lệ của các trường trong Rulebook.
* **Module B0.3 (Text-to-SQL)**: Sử dụng danh sách Primary Keys và Grain để viết mệnh đề `GROUP BY` và các phép tính tổng hợp chính xác.
* **Module B0.5 (Output Gate)**: Cung cấp bằng chứng khi thẩm định câu hỏi có thể trả lời được hay không.

---

## 5. Nếu Không Có File Này Thì Sao?

* LLM sẽ không biết cột nào là khóa chính, dễ dẫn đến việc join nhầm các cột phụ hoặc viết các câu lệnh SELECT với grain bị sai (ví dụ: đếm số mặt hàng thay vì đếm số đơn hàng).

