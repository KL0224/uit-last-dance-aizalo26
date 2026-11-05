# Giải Thích Mã Nguồn: `contracts.py` (B0.2)

**Đường dẫn file:** `src/datamate/b0/b02/contracts.py`  
**Thuộc module:** B0.2 Context Extractor & Business Rules  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `contracts.py` trong B0.2 định nghĩa **Hợp đồng Ngữ cảnh Kinh doanh Tối hậu (The Ultimate Business Context Contract)**. Nó là nơi kết hợp dữ liệu kỹ thuật (Schema, Cột, Khóa từ B0.1) và dữ liệu nghiệp vụ (Quy tắc, Công thức, Mức ưu tiên từ B0.2) thành một cấu trúc thống nhất sẵn sàng cấp phát cho LLM và Output Gate.

---

## 2. Chi Tiết Các Lớp & Thực Thể

### 2.1. Hằng số `CONTRACT_VERSION = "1.0"`
* Phiên bản hợp đồng hiện tại. Ngăn chặn việc trộn lẫn các phiên bản metadata cũ và mới.

### 2.2. Lớp `BusinessRule`
* Mô tả một quy tắc kinh doanh cụ thể:
  * `rule_id`: Chuỗi băm ổn định định danh quy tắc.
  * `text`: Nội dung gốc trích xuất từ tài liệu.
  * `source`: Nguồn tài liệu (ví dụ: `rulebook_fnb.md`).
  * `scope`: Phạm vi (`question_override`, `business`, `industry`, `split_default`).
  * `precedence`: Điểm ưu tiên số học (100, 200, 300, 400).
  * `status`: Trạng thái (`descriptive`, `validated`, `invalid`).
  * `required_fields`: Danh sách các cột mà quy tắc này yêu cầu phải có trong DB.
  * `expression`: Biểu thức DSL có cấu trúc.
  * `topic`, `industry`, `question_id`: Các tag ngữ cảnh lọc.
  * `binding_evidence`: Bằng chứng chứng minh quy tắc đã được gắn kết hợp lệ.

### 2.3. Lớp `RuleCatalog`
* Danh mục toàn bộ các quy tắc thuộc về một doanh nghiệp cụ thể (`business_id`), đi kèm các cảnh báo phát sinh (`warnings`).

### 2.4. Lớp `BusinessContext`
* Đối tượng kết quả cuối cùng chứa:
  * `contract_version`, `business_id`.
  * `schema_catalog`: Toàn bộ thông tin schema từ B0.1.
  * `rule_catalog`: Toàn bộ quy tắc từ B0.2.
  * `data_profiling`: Dữ liệu thống kê profile (nếu có).
  * `business_metadata`: Metadata nghiệp vụ bổ sung.
  * `answerability_constraints`: Ràng buộc khả năng trả lời.
* Phương thức `to_dict()`: Chuyển đổi thành JSON serializable, đồng thời **tự động loại bỏ `profile_rows`** để không làm rò rỉ dữ liệu mẫu.

### 2.5. Lớp `ContractBuilder`
* Trình xây dựng và kiểm chứng chéo toàn diện:
  * Kiểm tra `business_id` không được rỗng và phải khớp giữa Schema và Rule.
  * Kiểm tra trùng lặp tên bảng hoặc trùng lặp tên cột.
  * Kiểm tra hợp lệ `null_ratio` (0.0 đến 1.0) và `cardinality` (>= 0).
  * **Kiểm tra chéo tính tồn tại của cột trong biểu thức Rule**: Nếu một rule yêu cầu cột `order_date` mà trong DB không bảng nào có cột này ➔ Ném lỗi `ValueError` ngay lập tức.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Kiểm tra chéo nghiêm ngặt tại `ContractBuilder`**:
   Nhiều lỗi trong hệ thống Text-to-SQL xảy ra do Rulebook nói một đằng (gọi tên cột là `ngay_tao`) nhưng bảng DB lại đặt tên là `created_at`. `ContractBuilder` phát hiện ngay sự mâu thuẫn này tại thời điểm chuẩn bị context trước khi tốn token gọi LLM.
2. **Kế thừa và Tương thích với B0.1**:
   `b02.contracts` tái sử dụng trực tiếp các dataclass `SchemaCatalog`, `JoinEdge` từ `datamate.b0.b01.contracts`, tạo nên sự nhất quán về type system trong toàn bộ dự án.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Module B0.3 (Text-to-SQL)**: Đầu vào chính của B0.3 chính là file JSON do `BusinessContext.to_dict()` xuất ra.
* **Module B0.5 (Output Gate)**: Đọc các trường `answerability_constraints` để phát hiện câu hỏi không thể trả lời.

---

## 5. Nếu Không Có File Này Thì Sao?

* Dữ liệu schema và quy tắc sẽ bị rời rạc, không có cơ chế kiểm tra chéo tính hợp lệ giữa cột DB và trường quy tắc.
* Dễ bị rò rỉ các dòng mẫu profile nội bộ vào output.

