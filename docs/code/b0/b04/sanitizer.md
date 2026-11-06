# Giải Thích Mã Nguồn: `sanitizer.py` (B0.4)

**Đường dẫn file:** [`src/datamate/b0/b04/sanitizer.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/sanitizer.py)  
**Thuộc module:** B0.4 DuckDB Read-Only Execution Engine  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `sanitizer.py` là **Lớp phòng thủ bảo mật tĩnh (Static Security & Sanitation Layer)** của module B0.4. Trước khi bất kỳ câu lệnh SQL nào được gửi tới engine DuckDB để thực thi, nó bắt buộc phải đi qua tệp này để:
1. Bóc tách markdown code fence (` ```sql ... ``` `).
2. Phân tích cây cú pháp trừu tượng AST (Abstract Syntax Tree) bằng thư viện `sqlglot`.
3. Kiểm tra tính chất chỉ đọc (Read-only Verification), ngăn chặn tuyệt đối các lệnh phá hoại, thay đổi dữ liệu, đọc trộm file hệ thống hoặc kỹ thuật chèn nhiều câu lệnh (Multi-statement SQL Injection).

---

## 2. Chi Tiết Các Thành Phần & Thuật Toán

### 2.1. Danh Sách Đen Cấp Độ AST (Forbidden AST Nodes)
```python
FORBIDDEN_AST_NODES = (
    exp.Drop, exp.Delete, exp.Update, exp.Insert, exp.Create,
    exp.Alter, exp.Copy, exp.Attach, exp.Detach, exp.Install,
    exp.Command, exp.Pragma, exp.Set, exp.Transaction, exp.Commit, exp.Rollback,
)
```
* Bất kỳ câu truy vấn nào chứa các node trên trong cây AST (kể cả trong subquery hoặc CTE) đều bị coi là vi phạm bảo mật nghiêm trọng.

### 2.2. Danh Sách Hàm Cấm (Forbidden Functions)
```python
FORBIDDEN_FUNCTIONS = {
    "read_csv", "read_csv_auto", "read_parquet", "read_json",
    "read_text", "read_blob", "write_parquet", "write_csv", "copy", ...
}
```
* Ngăn chặn người dùng hoặc mô hình LLM khai thác tính năng mạnh mẽ của DuckDB để đọc các file nhạy cảm trong hệ điều hành (ví dụ: `SELECT * FROM read_csv('/etc/passwd')`).

### 2.3. Hàm `extract_clean_sql(raw_sql: str) -> str`
* Sử dụng Regex `r"```(?:sql)?\s*([\s\S]*?)\s*```"` để bóc tách nội dung câu SQL nằm bên trong các block markdown do LLM sinh ra.
* Gỡ bỏ các dấu chấm phẩy thừa (`r";+\s*$"`) ở cuối câu.
* Ném `EmptyQueryError` nếu sau khi bóc tách chuỗi rỗng.

### 2.4. Hàm `validate_read_only_sql(sql: str) -> str`
Quy trình kiểm tra an toàn tĩnh gồm 4 bước:

1. **Kiểm tra rỗng:** Gọi `extract_clean_sql(sql)`.
2. **Kiểm tra Multi-statement Injection:**
   * Sử dụng `sqlglot.parse(cleaned, read="duckdb")`.
   * Nếu danh sách statements trả về có độ dài `> 1` (ví dụ: `SELECT 1; DROP TABLE customers;`), ném ngay `SecurityViolation: Multiple statements are not permitted`.
3. **Kiểm tra Node Gốc (Root Node):**
   * Câu lệnh gốc bắt buộc phải là một trong các dạng truy vấn dữ liệu: `exp.Select`, `exp.Union`, `exp.Intersect`, `exp.Except`.
4. **Quét sâu đệ quy cây cú pháp (AST Traversal):**
   * Duyệt qua toàn bộ các node con (`expression.find_all(exp.Expression)`):
     * Nếu bắt gặp bất kỳ node nào trong `FORBIDDEN_AST_NODES`: ném `SecurityViolation`.
     * Nếu bắt gặp `exp.Anonymous` hoặc `exp.Func` có tên hàm nằm trong `FORBIDDEN_FUNCTIONS`: ném `SecurityViolation`.
5. **Dung nạp lỗi cú pháp thực sự (Pass-through Genuine Syntax Errors):**
   * Nếu `sqlglot` gặp lỗi `ParseError` do cú pháp SQL đặc thù của DuckDB hoặc lỗi cú pháp thông thường, hàm cho phép câu lệnh đi tiếp tới DuckDB để DuckDB đưa ra thông báo lỗi chính xác (kèm số dòng và gợi ý "Did you mean"), giúp LLM sửa lỗi ở bước retry hiệu quả hơn.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Tại sao dùng AST thay vì Regex để chặn DROP/DELETE?**
   * Kiểm tra bằng Regex hoặc chuỗi ký tự rất dễ bị vượt mặt (Bypass) bằng kỹ thuật comment: `SELECT /* drop */ id FROM tbl;` hoặc khi một cột hay chuỗi có chữ "drop": `WHERE status = 'dropped'`.
   * Phân tích AST bằng `sqlglot` hiểu được cấu trúc ngữ pháp thực sự, chỉ chặn khi từ khóa đó thực sự là một lệnh thực thi (Action Node).
2. **Cho phép lỗi cú pháp đi tiếp (Pass-through):**
   * Một số sanitizer quá khắt khe sẽ chặn luôn câu lệnh nếu parser không nhận diện được cú pháp. Việc để lỗi cú pháp đi tới DuckDB giúp ta lấy được thông điệp lỗi tự nhiên của hệ quản trị cơ sở dữ liệu để truyền lại cho vòng lặp Bounded Retry.

---

## 4. Tương Thích & Mối Liên Hệ

* Được gọi ở Bước 1 của hàm [`execute_query`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/engine.md).
* Ném các ngoại lệ định nghĩa tại [`schemas.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b04/schemas.md).

---

## 5. Nếu Không Có File Này Thì Sao?

* Cơ sở dữ liệu sẽ đứng trước nguy cơ bị phá hủy bởi các câu lệnh DDL/DML do LLM bị tấn công Prompt Injection sinh ra.
* Mô hình có thể đọc trộm các file bí mật trong hệ điều hành máy chủ.

