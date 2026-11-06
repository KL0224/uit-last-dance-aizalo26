# Giải Thích Mã Nguồn: `parser.py` (B0.3)

**Đường dẫn file:** [`src/datamate/b0/b03/parser.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py)  
**Thuộc module:** B0.3 Text-to-SQL LLM Layer  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `parser.py` là **Bộ giải mã kiên cố (Robust Output Parser)** chuyển đổi chuỗi văn bản tự do sinh ra từ LLM thành đối tượng dữ liệu có cấu trúc [`Text2SQLResult`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/types.md). Trong thực tế chạy benchmark, các mô hình LLM có thể sinh ra JSON chuẩn, JSON bọc trong markdown code fence, câu lệnh SQL thô, hoặc văn bản tự nhiên giải thích từ chối. `parser.py` đóng vai trò phòng vệ kiên cố, đảm bảo toàn bộ các biến thể đầu ra đều được chuẩn hóa an toàn mà không làm sập pipeline.

---

## 2. Chi Tiết Các Hàm Chức Năng

### 2.1. Hàm `clean_markdown_block(text: str) -> str`
* Bóc tách nội dung thuần túy nằm bên trong các khối markdown ` ```json ... ``` ` hoặc ` ```sql ... ``` ` hoặc ` ``` ... ``` `.
* Tự động loại bỏ các khoảng trắng thừa đầu cuối.

### 2.2. Hàm `extract_tables_from_sql(sql: str) -> tuple[str, ...]`
* Sử dụng Regular Expression (`r"\b(?:FROM|JOIN)\s+([\"`]?[\w\.]+[\"`]?)"`) để bóc tách tên các bảng được truy vấn trong câu lệnh SQL.
* Loại trừ các từ khóa SQL nhầm lẫn (như `SELECT`, `WHERE`, `GROUP`, `ORDER`), tự động gỡ bỏ dấu ngoặc kép hoặc backticks bọc quanh tên bảng.

### 2.3. Hàm `infer_answer_type_from_sql(sql: str) -> str`
* Heuristic suy đoán kiểu câu trả lời (1 trong 9 types của B0.5) dựa vào các hàm tập hợp trong mệnh đề `SELECT`:
  * Có `COUNT`, `SUM`, `AVG`, `MIN`, `MAX` $\rightarrow$ gán `"number"`.
  * Có hàm thời gian `DATE`, `STRFTIME`, `STRPTIME` $\rightarrow$ gán `"date"`.
  * Có `LIMIT 1` và chọn đơn cột $\rightarrow$ gán `"string"`.
  * Còn lại $\rightarrow$ gán `"table"`.

### 2.4. Hàm `parse_text2sql_response(raw_text: str) -> Text2SQLResult`
Đây là hàm cốt lõi xử lý theo chiến lược đa tầng (Multi-tier Strategy):

1. **Kiểm tra rỗng:** Nếu chuỗi rỗng hoặc chỉ có whitespace, ném ngay `Text2SQLParseError`.
2. **Tầng 1: Giải mã JSON chuẩn hoặc JSON nhúng trong văn bản:**
   * Thử `json.loads(cleaned_text)`. Nếu thất bại, dùng regex `r"\{[\s\S]*\}"` để tìm kiếm object JSON đầu tiên trong chuỗi.
   * Nếu thành công:
     * Kiểm tra trường `status`:
       * Nếu `"unanswerable"`: Trích xuất `reason`, trả về `Text2SQLResult(status="unanswerable", reason=...)`.
       * Nếu `"answerable"`: Làm sạch câu SQL, trích xuất `tables_used` (nếu thiếu thì gọi `extract_tables_from_sql`), suy luận `answer_type` nếu thiếu, trả về `Text2SQLResult(status="answerable", ...)`.
3. **Tầng 2 (Fallback Heuristic): Model chỉ sinh câu lệnh SQL mà quên bọc JSON:**
   * Nếu chuỗi bắt đầu bằng `SELECT` hoặc `WITH`, parser hiểu rằng LLM đã sinh đúng câu truy vấn nhưng bỏ qua vỏ bọc JSON.
   * Parser tự động gỡ bỏ dấu chấm phẩy thừa, tự động trích xuất bảng và suy luận kiểu câu trả lời, trả về `Text2SQLResult(status="answerable", ...)`.
4. **Tầng 3 (Fallback Textual): Model trả lời bằng văn bản từ chối:**
   * Nhận diện các cụm từ tiếng Việt hoặc tiếng Anh đặc trưng: *"không thể trả lời"*, *"không đủ dữ liệu"*, *"thiếu cột"*, *"thiếu bảng"*, *"unanswerable"*.
   * Tự động phân loại thành `status = "unanswerable"` và lấy toàn bộ đoạn văn bản đó làm lý do (`reason`).
5. **Tầng 4 (Fail-safe):**
   * Nếu tất cả các tầng trên đều không xử lý được, ném ngoại lệ `Text2SQLParseError` với nội dung tóm tắt để phục vụ logging.

---

## 3. Tại Sao Lại Code Như Vậy?

* **Độ bền bỉ thực chiến (Production Robustness):**
  Trong quá trình chạy batch hàng nghìn câu hỏi của cuộc thi, ngay cả các model lớn được prompt chặt chẽ đôi khi vẫn có tỷ lệ nhỏ bị rò rỉ cú pháp (sinh raw SQL hoặc chèn thêm lời dẫn). Một bộ parser cứng nhắc chỉ gọi `json.loads` đơn thuần sẽ làm crash toàn bộ batch. Cơ chế fallback đa tầng này cứu vãn được hàng trăm ca truy vấn hợp lệ.
* **Tự động điền metadata thiếu:**
  Nếu LLM sinh đúng câu SQL nhưng quên ghi trường `"tables_used"` hoặc `"answer_type"`, parser tự động bù đắp thông tin qua việc phân tích cú pháp SQL tĩnh, giúp tầng thực thi B0.4 và kiểm duyệt B0.5 hoạt động trơn tru.

---

## 4. Tương Thích & Mối Liên Hệ

* Chuyển đổi chuỗi thô từ [`BaseLLM.chat`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/base.md) thành [`Text2SQLResult`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/types.md).
* Được tích hợp trực tiếp trong [`Text2SQLGenerator`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/generator.md).
* Ném ra ngoại lệ [`Text2SQLParseError`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/errors.md).

---

## 5. Nếu Không Có File Này Thì Sao?

* B0.3 chỉ có thể trả về một chuỗi văn bản thô vô định hình.
* B0.4 Executor sẽ không biết đâu là câu SQL để chạy vào DuckDB.
* B0.5 Output Gate không thể nhận diện được `answer_type` hay trạng thái `unanswerable`, khiến pipeline hoàn toàn gãy đổ.

