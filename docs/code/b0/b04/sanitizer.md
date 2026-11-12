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
* Xóa bỏ các khối suy luận `<think>...</think>` nếu còn sót lại trong chuỗi đầu vào.
* Sử dụng `re.findall(r"```(?:sql)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)` và lấy **khối markdown cuối cùng (`matches[-1]`)** để tránh chạy nhầm khối SQL nháp khi LLM sinh nhiều đoạn code giải thích.
* Gỡ bỏ các comment cuối câu (`/* ... */`, `-- ...`) trước và sau khi cắt dấu chấm phẩy thừa (`r";+\s*$"`).
* Ném `EmptyQueryError` nếu sau khi bóc tách chuỗi rỗng.

### 2.4. Hàm `validate_read_only_sql(sql: str) -> str`
Quy trình kiểm tra an toàn tĩnh gồm 5 bước:

1. **Làm sạch & che mặt nạ chuỗi literal (`_mask_literals_and_comments`):** Gọi `extract_clean_sql(sql)` và tạo bản sao đã xóa nội dung bên trong dấu nháy đơn `'...'`, nháy kép `"..."` và comment để không bao giờ chặn nhầm các từ khóa nhạy cảm nằm trong chuỗi lọc dữ liệu (ví dụ `WHERE trang_thai = 'update'`).
2. **Phân tích AST trước & Kiểm tra Multi-statement Injection:**
   * Sử dụng `sqlglot.parse(cleaned_sql, read="duckdb")`.
   * Nếu danh sách statements trả về có độ dài `> 1` (ví dụ: `SELECT 1; DROP TABLE customers;`), ném ngay `SecurityViolation`.
3. **Kiểm tra Node Gốc (`ALLOWED_ROOT_NODES` & `SYNTAX_FRAGMENT_NODES`):**
   * Câu lệnh gốc phải thuộc `ALLOWED_ROOT_NODES` (`Select`, `Union`, `Intersect`, `Except`, `Subquery`) hoặc `SYNTAX_FRAGMENT_NODES` (để các lỗi gõ nhầm như `SELEC * FORM t` đi tiếp xuống DuckDB lấy thông báo lỗi cú pháp chính xác, miễn là từ đầu câu không nằm trong `NON_QUERY_LEADING_WORDS` hay `FORBIDDEN_KEYWORDS`).
4. **Quét sâu đệ quy cây cú pháp (`stmt.walk()`):**
   * Duyệt qua toàn bộ các node con:
     * Nếu bắt gặp bất kỳ node nào trong `FORBIDDEN_AST_NODES`: ném `SecurityViolation`.
     * Nếu bắt gặp hàm/bảng trong `FORBIDDEN_FUNCTIONS` hoặc hàm hệ thống bắt đầu bằng `duckdb_*`: ném `SecurityViolation`.
5. **Fallback quét Regex đã xóa literal khi `ParseError`:**
   * Chỉ khi `sqlglot` ném `ParseError`, hàm mới dùng `_strip_literals_and_comments(cleaned_sql)` để kiểm tra dấu `;`, `FORBIDDEN_FUNCTIONS`, `duckdb_*`, `FORBIDDEN_KEYWORDS` và `NON_QUERY_LEADING_WORDS` trên phần code thuần túy (đã loại bỏ chuỗi literal).

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

