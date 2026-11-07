# `base.py` — Interface chung cho tầng LLM

> **Summary:** `BaseLLM` định nghĩa bốn thao tác mà một backend LLM phải cung cấp: nạp model, sinh completion cho một prompt, sinh phản hồi hội thoại và xử lý một batch prompt. Ứng dụng có thể dùng cùng interface khi thay đổi inference engine.

**File nguồn:** [`src/llm/base.py`](../../../../src/llm/base.py).

## Mục đích và ý nghĩa

`BaseLLM` kế thừa `ABC`; cả bốn method đều được đánh dấu `@abstractmethod`. Không thể khởi tạo trực tiếp `BaseLLM` hoặc một subclass chưa triển khai đủ các method này. File chỉ quy định hợp đồng input/output, chưa thực hiện inference hay quản lý tài nguyên.

Interface chạy đồng bộ: lời gọi trả kết quả sau khi xử lý xong. Nó không lưu lịch sử hội thoại; mỗi lần `chat()`, caller phải cung cấp toàn bộ messages cần sử dụng. Interface chưa cam kết an toàn khi gọi từ nhiều thread và không định nghĩa thao tác unload model.

Các kiểu đầu vào và kết quả được khai báo trong [`types.md`](types.md); backend hiện tại được mô tả trong [`vllm.md`](vllm.md).

## Từng method

### `BaseLLM.load(self) -> None`

- **Tác dụng:** Yêu cầu backend nạp model và khởi tạo tài nguyên cần cho inference. Sau khi đã load thành công, gọi lại phải không tạo engine mới.
- **Input:** Chỉ có `self`, tức instance backend. Cấu hình nạp model do implementation quản lý; method không nhận đường dẫn trực tiếp.
- **Output:** `None`. Kết quả chính là thay đổi trạng thái backend thành đã nạp.
- **Lưu ý:** Đây là hợp đồng trừu tượng. Việc kiểm tra weights và cách báo lỗi phụ thuộc backend; `VLLMModel` dùng `ModelLoadError`.

### `BaseLLM.generate(self, prompt: str, *, options: GenerationOptions | None = None) -> GenerationResult`

- **Tác dụng:** Sinh completion từ một raw prompt. Backend không tự thêm chat template vào prompt này.
- **Input:**
  - `prompt`: Chuỗi văn bản đầu vào cho model.
  - `options`: Tùy chọn sampling cho request; chỉ được truyền bằng tên, ví dụ `options=...`. Giá trị `None` cho phép implementation dùng cấu hình mặc định.
- **Output:** Một `GenerationResult`, chứa completion, số token input/output và lý do kết thúc.
- **Lưu ý:** Nếu cần định dạng role theo template của checkpoint, dùng `chat()`.

### `BaseLLM.chat(self, messages: list[ChatMessage], *, options: GenerationOptions | None = None) -> GenerationResult`

- **Tác dụng:** Sinh một phản hồi assistant bằng chat template đi kèm checkpoint.
- **Input:**
  - `messages`: Danh sách `ChatMessage` theo thứ tự hội thoại; mỗi message gồm `role` và `content`. Caller truyền cả lịch sử cần dùng.
  - `options`: Tùy chọn sampling của request, truyền bằng tên; mặc định `None`.
- **Output:** Một `GenerationResult` cho phản hồi mới. Method không trả lại danh sách messages đã nối thêm phản hồi.
- **Lưu ý:** Implementation chịu trách nhiệm áp dụng template; interface không tự nối các role marker và không tự lưu messages.

### `BaseLLM.generate_batch(self, prompts: list[str], *, options: GenerationOptions | None = None) -> list[GenerationResult]`

- **Tác dụng:** Sinh completion cho nhiều raw prompt trong một lần gọi, không tự thêm chat template.
- **Input:**
  - `prompts`: Danh sách chuỗi prompt.
  - `options`: Một bộ tùy chọn sampling áp dụng cho toàn bộ batch, truyền bằng tên; mặc định `None`.
- **Output:** Danh sách `GenerationResult` giữ nguyên thứ tự đầu vào: phần tử thứ `i` ứng với `prompts[i]`.
- **Lưu ý:** Interface chưa quy định xử lý batch rỗng hoặc kiểu dữ liệu sai. Backend `VLLMModel` kiểm tra cụ thể và trả `[]` cho batch rỗng sau khi xác nhận model đã load.
