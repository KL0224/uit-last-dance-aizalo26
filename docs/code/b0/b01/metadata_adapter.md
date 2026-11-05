# Giải Thích Mã Nguồn: `metadata_adapter.py` (B0.1)

**Đường dẫn file:** `src/datamate/b0/b01/metadata_adapter.py`  
**Thuộc module:** B0.1 Data Loader & Schema/Join Catalog  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `metadata_adapter.py` là **Lớp phòng thủ biên giới (Boundary Anti-Corruption Layer)** tiếp nhận dữ liệu metadata được tạo ra bởi producer (Data Foundation). 

Nó đảm bảo rằng hệ thống chỉ chấp nhận dữ liệu có cấu trúc hợp lệ (phiên bản `1.0`), đúng mã định danh doanh nghiệp (`business_id`), và chuyển đổi các dictionary JSON thô thành các đối tượng `dataclass` an toàn.

---

## 2. Chi Tiết Các Lớp & Hàm Lõi

### 2.1. `FoundationMetadata`
* Vỏ bọc chứa siêu dữ liệu từ producer:
  * `business_id`: Mã định danh doanh nghiệp.
  * `tables`: Danh sách các bảng đã được trích xuất.
  * `relationships`: Các quan hệ khai báo sẵn giữa các bảng.
  * `data_profiling`: Thống kê dữ liệu bổ sung (nếu có).
  * `answerability_constraints`: Ràng buộc phạm vi dữ liệu (ví dụ: ngày bắt đầu/kết thúc).

### 2.2. `BaseMetadataProvider(ABC)`
* Lớp trừu tượng (Abstract Base Class) định nghĩa phương thức `load(business_id: str) -> FoundationMetadata`.
* Cho phép sau này thay thế nguồn dữ liệu (ví dụ: đọc từ Database trực tiếp, đọc từ SQLite, đọc từ Cache Redis) mà không cần chỉnh sửa bất kỳ dòng code nào trong B01 hay B02.

### 2.3. `JSONMetadataProvider(BaseMetadataProvider)`
* Hiện thực việc đọc từ tệp JSON.
* Phương thức `from_dict(payload, business_id)`:
  * Kiểm tra `metadata_version == "1.0"`. Nếu khác ➔ Ném `ValueError`.
  * Kiểm tra `payload["business_id"] == business_id`. Nếu lệch scope ➔ Ném lỗi ngay lập tức.
  * Giải mã từng bảng, từng cột với các hàm thẩm định kiểu dữ liệu nghiêm ngặt: `_object()`, `_string()`, `_list()`, `_float_or_none()`, `_int_or_none()`.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Từ chối dữ liệu rác (Fail Fast & Explicit Rejection)**:
   Không ngầm ép kiểu hoặc bỏ qua các trường lạ. Nếu file JSON có trường dữ liệu không nằm trong đặc tả v1.0, adapter sẽ báo lỗi rõ ràng. Điều này ngăn chặn việc producer gửi dữ liệu sai mà downstream không hề hay biết.
2. **Không tự động ép kiểu dữ liệu (No Type Guessing)**:
   Cột nếu không rõ kiểu sẽ giữ nguyên `unknown`. Adapter không cố gắng đoán mò từ string sang int/date vì việc đoán sai kiểu sẽ phá hỏng câu truy vấn SQL ở module B0.3 và B0.4.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* Cung cấp dữ liệu đầu vào chuẩn hóa cho `SchemaCatalogBuilder`.
* Cung cấp các ràng buộc `answerability_constraints` để đưa vào `BusinessContext` và chuyển sang B0.5.

---

## 5. Nếu Không Có File Này Thì Sao?

* Toàn bộ mã nguồn phía sau sẽ phải tự đọc JSON, tự parse thủ công bằng `json.loads()`.
* Khi cấu trúc JSON thay đổi hoặc bị thiếu trường, lỗi `KeyError`/`TypeError` sẽ văng ra rải rác ở khắp các tầng bên trong pipeline thay vì được chặn đứng ngay tại cửa ngõ.

