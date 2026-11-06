# Giải Thích Mã Nguồn: `types.py` (B0.3)

**Đường dẫn file:** [`src/datamate/b0/b03/types.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py)  
**Thuộc module:** B0.3 Text-to-SQL LLM Layer  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `types.py` chứa toàn bộ các lớp dữ liệu bất biến (Immutable Data Classes / DTOs) đại diện cho thông điệp hội thoại, tùy chọn lấy mẫu sinh văn bản (sampling options), cấu hình kỹ thuật của engine và kết quả sinh Text-to-SQL. Tệp này hoàn toàn không phụ thuộc vào PyTorch, CUDA hay vLLM, đóng vai trò là "ngôn ngữ chung" giao tiếp giữa các thành phần trong module và các module lân cận.

---

## 2. Chi Tiết Các Lớp Dữ Liệu

### 2.1. `ChatMessage`
* **Mục đích:** Đại diện cho một lượt phát biểu trong hội thoại dạng text.
* **Các trường:**
  * `role`: Phải là một trong ba giá trị nghiêm ngặt: `"system"`, `"user"`, `"assistant"`.
  * `content`: Nội dung chuỗi ký tự (`str`).
* **Bảo vệ bất biến (`__post_init__`):** Kiểm tra kiểu dữ liệu chuỗi và từ chối các role không được hỗ trợ (ném `ValueError` / `TypeError`).

### 2.2. `GenerationOptions`
* **Mục đích:** Cấu hình các tham số lấy mẫu xác suất (sampling) cho từng request/batch suy luận mà không làm thay đổi weights của mô hình.
* **Các tham số:**
  * `max_new_tokens`: Số lượng token tối đa được phép sinh ra (mặc định: 1024, bắt buộc `> 0`).
  * `temperature`: Nhiệt độ lấy mẫu (mặc định 0.7; `= 0.0` tương ứng greedy decoding).
  * `top_p`: Nucleus sampling cutoff (mặc định 0.8, nằm trong khoảng `(0, 1]`).
  * `top_k`: Top-K sampling (mặc định 20, `-1` là vô hiệu hóa).
  * `repetition_penalty`: Hệ số phạt lặp lại token (mặc định 1.0).
  * `presence_penalty`: Hệ số phạt xuất hiện từ mới (mặc định 1.5).
  * `stop`: Tuple các chuỗi ký tự dừng sinh sớm.
  * `seed`: Hạt giống sinh ngẫu nhiên giúp tái lập kết quả tương đối.
* **Bảo vệ tính bất biến:** Tự động chuyển đổi `stop` từ `list` sang `tuple` để tránh bị sửa đổi ngoài ý muốn từ bên ngoài.

### 2.3. `ModelConfig`
* **Mục đích:** Cấu hình tài nguyên để khởi tạo engine suy luận.
* **Các tham số:**
  * `model_path`: Đường dẫn cục bộ (`Path`) tới thư mục weights đã tải về.
  * `dtype`: Kiểu số thực dấu phẩy động (mặc định: `"bfloat16"`).
  * `max_model_len`: Độ dài ngữ cảnh tối đa của mô hình (mặc định 8192 tokens).
  * `gpu_memory_utilization`: Tỷ lệ VRAM tối đa cấp cho vLLM KV cache (mặc định 0.9, tức 90%).
  * `tensor_parallel_size`: Số lượng GPU phân tán tensor (mặc định 1).
  * `max_num_seqs`: Số lượng chuỗi tối đa xử lý song song trong continuous batching (mặc định 4).
  * `trust_remote_code`: Cờ cho phép chạy mã tùy biến của checkpoint (mặc định: False).
  * `chat_template_kwargs`: Các cờ tham số phụ cho Jinja template (ví dụ: `enable_thinking = False`).

### 2.4. `GenerationResult`
* **Mục đích:** Kết quả sinh chuỗi thô từ LLM ở tầng thấp.
* **Các trường:**
  * `text`: Chuỗi completion hoàn chỉnh được sinh ra.
  * `input_tokens`: Số lượng token đầu vào được tokenizer xử lý.
  * `output_tokens`: Số lượng token đầu ra được tạo ra.
  * `finish_reason`: Lý do dừng sinh (`"stop"`, `"length"`, ...).

### 2.5. `Text2SQLResult`
* **Mục đích:** Kết quả ngữ nghĩa cấp cao của tác vụ Text-to-SQL, tuân thủ đúng định dạng hợp đồng được quy định tại `docs/architecture/b0/input_output_text2sql.md`.
* **Các trường:**
  * `status`: `"answerable"` (dữ liệu có thể trả lời) hoặc `"unanswerable"` (dữ liệu thiếu thông tin).
  * `answer_type`: Loại câu trả lời dự kiến (`"number"`, `"percent"`, `"string"`, `"date"`, `"boolean"`, `"list"`, `"table"`, hoặc `None`).
  * `sql`: Chuỗi truy vấn SQL DuckDB đã làm sạch (hoặc `None` nếu unanswerable).
  * `tables_used`: Tuple tên các bảng cơ sở dữ liệu được truy vấn.
  * `assumptions`: Tuple các giả định nghiệp vụ được đặt ra.
  * `reason`: Lý do chi tiết giải thích tại sao câu hỏi không thể trả lời được.
* **Phương thức Adapter `to_b05_generation_result()`:**
  * Tự động ánh xạ chuyển đổi sang đối tượng `GenerationResult` của B0.5 Basic Output Gate, tạo sự liên kết liền mạch tuyệt đối giữa B0.3 và B0.5 mà không cần viết thêm mã glue code rườm rà.

---

## 3. Tại Sao Lại Code Như Vậy?

* **Sử dụng `@dataclass(frozen=True)`:** Biến các DTO thành đối tượng bất biến (Read-only). Khi dữ liệu di chuyển qua nhiều tầng (B0.3 $\rightarrow$ B0.4 $\rightarrow$ B0.5), không có bất kỳ hàm nào có thể vô tình làm biến đổi dữ liệu gốc, triệt tiêu các lỗi side-effects khó debug.
* **Phương thức Adapter nội tại:** Việc tích hợp `to_b05_generation_result()` trực tiếp vào `Text2SQLResult` giúp bảo đảm tính gắn kết cao (high cohesion) giữa các tầng hợp đồng của dự án.

---

## 4. Tương Thích & Mối Liên Hệ

* Được nhập bởi hầu hết các tệp trong B0.3 ([`base.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/base.md), [`prompt.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/prompt.md), [`parser.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/parser.md), [`generator.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/generator.md), [`vllm_model.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/vllm_model.md)).
* Cung cấp dữ liệu trực tiếp cho [`src/datamate/b0/b05/contracts.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/contracts.py).

---

## 5. Nếu Không Có File Này Thì Sao?

* Các module sẽ phải dùng `dict` nguyên thủy không có type-check để truyền dữ liệu qua lại, dẫn đến nguy cơ sai tên trường (`key_error`), sai kiểu dữ liệu (`type_error`) chỉ phát hiện được khi đã chạy trên dữ liệu thật.
* Không thể đảm bảo tính bất biến và toàn vẹn của kết quả suy luận.

