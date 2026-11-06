# Giải Thích Mã Nguồn: `vllm_model.py` (B0.3)

**Đường dẫn file:** [`src/datamate/b0/b03/vllm_model.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/vllm_model.py)  
**Thuộc module:** B0.3 Text-to-SQL LLM Layer  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `vllm_model.py` triển khai lớp `VLLMModel` kế thừa từ `BaseLLM`. Đây là backend thực thi suy luận offline cục bộ bằng engine vLLM. Trực tiếp nạp weights từ ổ đĩa máy tính vào VRAM của GPU mà **không cần thông qua HTTP API hay server trung gian**. Tệp này đóng gói toàn bộ quy trình cấu hình bộ nhớ VRAM, thiết lập tham số lấy mẫu, kiểm tra tính toàn vẹn của snapshot tải về và kích hoạt các phương thức sinh text (`generate`, `chat`, `generate_batch`).

---

## 2. Chi Tiết Lớp `VLLMModel`

### 2.1. Hàm khởi tạo (`__init__`)
* Nhận vào `ModelConfig` và `GenerationOptions` mặc định.
* **Nguyên tắc Lazy:** Không import vLLM, không kiểm tra GPU và không cấp phát VRAM trong hàm khởi tạo. Giúp việc tạo đối tượng hoàn toàn nhẹ nhàng.

### 2.2. Phương thức `load()`
* Kiểm tra tính hợp lệ của thư mục weights (`model_path.is_dir()` và tồn tại file `config.json`).
* Kiểm tra file manifest download `.model-download.json`. Nếu file này tồn tại nhưng có trạng thái `status != "complete"`, hàm sẽ ném lỗi `ModelLoadError` ngay lập tức để ngăn việc chạy trên snapshot bị lỗi download dở dang.
* **Lazy Import vLLM:** Chỉ gọi `from vllm import LLM, SamplingParams` bên trong khối `try...except` của `load()`.
* Khởi tạo đối tượng `vllm.LLM` với các tham số khắt khe:
  * `generation_config="vllm"`: Ngăn file generation config mặc định của Hugging Face ghi đè các tham số sampling của ứng dụng.
  * Cố định độ dài ngữ cảnh (`max_model_len`), tỷ lệ VRAM (`gpu_memory_utilization`), số luồng tensor parallel.

### 2.3. Các phương thức suy luận
1. **`generate(prompt, options)`**:
   * Gọi thông qua `generate_batch([prompt])` để đảm bảo hai API có cùng hành vi đồng nhất.
2. **`generate_batch(prompts, options)`**:
   * Tận dụng khả năng lập lịch nội bộ của vLLM để xử lý đồng thời danh sách prompts.
   * Chuyển đổi đầu ra từ `RequestOutput` của vLLM sang `GenerationResult` độc lập thông qua hàm tĩnh `_convert_outputs()`.
3. **`chat(messages, options)`**:
   * Chuyển đổi danh sách `ChatMessage` thành cấu trúc dict `[{"role": m.role, "content": m.content}]`.
   * Sử dụng trực tiếp phương thức `engine.chat()` của vLLM để engine tự động áp dụng Jinja chat template của mô hình (ví dụ: Qwen Chat Template), truyền tham số `chat_template_kwargs` (như tắt thinking mode).

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Bảo vệ VRAM & Ngăn chặn Memory Leaks:**
   * Việc quản lý duy nhất một instance của `VLLMModel` trong toàn bộ vòng đời process giúp tận dụng tối đa cơ chế PagedAttention của vLLM mà không bị tràn VRAM do tạo nhiều instance trùng lặp.
2. **Kiểm tra Download Manifest:**
   * Trong thực tế, quá trình tải mô hình lớn (như Qwen 9B dung lượng ~18GB) có thể bị ngắt quãng giữa chừng khi mạng chập chờn. Nếu không kiểm tra manifest, vLLM có thể vẫn nạp được các file đầu tiên nhưng sẽ crash bất ngờ giữa chừng khi inference.
3. **Bảo tồn tính trung thực của Token Counts:**
   * `_convert_outputs()` bóc tách chính xác số lượng token đầu vào (`input_tokens = len(output.prompt_token_ids)`) và token đầu ra (`output_tokens = len(completion.token_ids)`), phục vụ việc đo lường hiệu năng và quản lý giới hạn ngữ cảnh.

---

## 4. Tương Thích & Mối Liên Hệ

* Triển khai interface [`BaseLLM`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/base.md).
* Nhận cấu hình từ [`config.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/config.md).
* Được gói và điều phối bởi [`Text2SQLGenerator`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/generator.md).

---

## 5. Nếu Không Có File Này Thì Sao?

* Hệ thống không thể chạy suy luận LLM ở chế độ offline trên máy server GPU nội bộ.
* Phải phụ thuộc vào việc bật một server HTTP riêng biệt (`vllm serve`) qua mạng nội bộ, gây trễ mạng (network overhead), tốn tài nguyên quản lý tiến trình và dễ bị lỗi timeout kết nối.

