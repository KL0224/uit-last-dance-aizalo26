# Giải Thích Mã Nguồn: `prompt.py` (B0.3)

**Đường dẫn file:** [`src/datamate/b0/b03/prompt.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py)  
**Thuộc module:** B0.3 Text-to-SQL LLM Layer  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `prompt.py` đóng vai trò là **Bộ kỹ thuật ngữ cảnh (Context & Prompt Engineering)** biến đổi toàn bộ hợp đồng dữ liệu phức tạp từ B0.2 Context (`BusinessContext`, `SchemaCatalog`, `RuleCatalog`, `answerability_constraints`) thành các câu lệnh prompt tiếng Việt rõ ràng, chặt chẽ, tối ưu hóa sự chú ý (attention) của mô hình ngôn ngữ lớn Qwen. Ngoài ra, tệp còn chịu trách nhiệm thiết lập prompt phản hồi lỗi (Error Feedback Prompt) cho bước **One Bounded Retry** khi tầng thực thi gặp lỗi.

---

## 2. Chi Tiết Các Thành Phần

### 2.1. `SYSTEM_INSTRUCTION`
* Hệ thống hướng dẫn định hình vai trò (Persona) cho LLM: Trợ lý chuyên gia phân tích dữ liệu và Text-to-SQL của DataMate 2026.
* Ràng buộc khắt khe:
  1. Phải phân định rõ ràng giữa `answerable` và `unanswerable`.
  2. Bắt buộc tạo câu lệnh SQL chuẩn DuckDB an toàn, chỉ dùng mệnh đề `SELECT`, cấm tuyệt đối các thao tác thay đổi dữ liệu DDL/DML.
  3. Bắt buộc trả về định dạng JSON thuần túy theo đúng cấu trúc của `docs/architecture/b0/input_output_text2sql.md`, không giải thích rườm rà ngoài JSON.

### 2.2. Hàm `format_context_for_prompt(context: Any) -> str`
* Nhận vào một đối tượng `BusinessContext` (B0.2) hoặc một `dict` Data Contract.
* Tuần tự bóc tách và định dạng Markdown thành 4 khối thông tin rõ ràng:
  1. **LƯỢC ĐỒ DỮ LIỆU (Table Schemas):** Tên từng bảng, ý nghĩa dòng (`grain`), danh sách các cột kèm kiểu dữ liệu, tính chất `NULL/NOT NULL` và các khóa chính ứng viên.
  2. **QUAN HỆ JOIN (Relationships):** Các cặp cột liên kết giữa các bảng kèm bản số quan hệ (`one_to_one`, `one_to_many`, `many_to_many`).
  3. **QUY TẮC NGHIỆP VỤ (Business Rules & Metrics):** Các mã quy tắc, mô tả nghiệp vụ và các biểu thức tính toán JSON (ví dụ công thức tính doanh thu thuần).
  4. **GIỚI HẠN DỮ LIỆU (Answerability Constraints):** Các giới hạn về phạm vi thời gian hoặc các cột bị thiếu trong dữ liệu.

### 2.3. Hàm `build_text2sql_messages(context, question, as_of_date) -> list[ChatMessage]`
* Đóng gói ngữ cảnh đã định dạng, ngày tham chiếu thời gian (`as_of_date`) và câu hỏi ngôn ngữ tự nhiên thành cặp thông điệp:
  * `ChatMessage(role="system", content=SYSTEM_INSTRUCTION)`
  * `ChatMessage(role="user", content=...)`
* Ngày tham chiếu `as_of_date` đóng vai trò cực kỳ quan trọng giúp mô hình giải quyết các khái niệm thời gian tương đối như *"hôm nay"*, *"tháng trước"*, *"quý vừa qua"*.

### 2.4. Hàm `build_repair_messages(context, question, as_of_date, previous_sql, error_message) -> list[ChatMessage]`
* Phục vụ vòng lặp **One Bounded Retry** khi B0.4 DuckDB Executor hoặc B0.5 Output Gate báo lỗi:
  * Nhúng lại toàn bộ ngữ cảnh dữ liệu và câu hỏi gốc.
  * Cung cấp lại câu lệnh SQL bị lỗi trước đó (`previous_sql`).
  * Trích xuất thông báo lỗi chính xác (`error_message` từ DuckDB Binder/Parser/Catalog) để LLM hiểu nguyên nhân thất bại và tự sửa đổi câu SQL cho đúng.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Cấu trúc hóa Markdown có tiêu đề rõ ràng:**
   * Các mô hình họ Qwen được huấn luyện rất tốt trên dữ liệu Markdown. Việc phân tách rõ ràng từng mục bằng `###` giúp mô hình tập trung sự chú ý vào đúng tên bảng và tên cột, giảm thiểu tối đa hiện tượng ảo giác (hallucination) tên cột không tồn tại.
2. **Loại bỏ profile mẫu nội bộ:**
   * Hàm tận dụng phương thức `context.to_dict()` của B0.2, vốn đã loại bỏ các dòng profile mẫu nhạy cảm, ngăn ngừa rò rỉ dữ liệu và tiết kiệm lượng token ngữ cảnh quý giá.
3. **Cơ chế Error Feedback nhắm trúng đích:**
   * Thay vì chỉ yêu cầu "Hãy thử lại", việc cung cấp chính xác lỗi của DuckDB (ví dụ: `BinderError: Column 'doanh_so' does not exist. Did you mean 'doanh_thu'?`) giúp tỷ lệ sửa lỗi thành công ở lượt retry tăng vọt.

---

## 4. Tương Thích & Mối Liên Hệ

* **Đầu vào:** Nhận `BusinessContext` trực tiếp từ [`src/datamate/b0/b02/contracts.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/contracts.py).
* **Đầu ra:** Cung cấp danh sách `ChatMessage` cho [`BaseLLM.chat`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/base.md).
* **Tích hợp:** Được sử dụng bởi [`Text2SQLGenerator`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/generator.md).

---

## 5. Nếu Không Có File Này Thì Sao?

* Mô hình LLM sẽ không nhận được lược đồ bảng hoặc quy tắc nghiệp vụ, dẫn đến việc sinh các câu SQL hoàn toàn bịa đặt, sai lệch schema.
* Không có cơ chế truyền ngày tham chiếu `as_of_date`, dẫn đến việc các câu hỏi có yếu tố thời gian tương đối sẽ bị tính toán sai mốc ngày tháng.
* Không có khả năng thực hiện Bounded Retry khi gặp lỗi thực thi.

