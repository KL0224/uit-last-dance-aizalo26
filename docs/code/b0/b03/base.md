# Giải Thích Mã Nguồn: `base.py` (B0.3)

**Đường dẫn file:** [`src/datamate/b0/b03/base.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/base.py)  
**Thuộc module:** B0.3 Text-to-SQL LLM Layer  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `base.py` định nghĩa lớp trừu tượng `BaseLLM` kế thừa từ `abc.ABC`. Đây là bản hợp đồng (Interface Contract) độc lập hoàn toàn với bất kỳ thư viện suy luận LLM cụ thể nào. Nhờ có interface này, toàn bộ logic nghiệp vụ cấp cao (prompt builder, text2sql generator, retry loops) không bao giờ bị gắn chặt (tightly coupled) vào vLLM, cho phép dễ dàng hoán đổi sang mock object khi test hoặc sang backend khác (Hugging Face TGI, llama.cpp, SGLang) mà không phải sửa một dòng code ứng dụng nào.

---

## 2. Chi Tiết Lớp `BaseLLM`

```python
class BaseLLM(ABC):
    @abstractmethod
    def load(self) -> None:
        """Khởi tạo engine và nạp weights vào bộ nhớ."""

    @abstractmethod
    def generate(self, prompt: str, *, options: GenerationOptions | None = None) -> GenerationResult:
        """Sinh completion cho một chuỗi raw prompt duy nhất (không qua chat template)."""

    @abstractmethod
    def chat(self, messages: list[ChatMessage], *, options: GenerationOptions | None = None) -> GenerationResult:
        """Sinh câu trả lời dựa trên danh sách ChatMessage có áp dụng chat template của model."""

    @abstractmethod
    def generate_batch(self, prompts: list[str], *, options: GenerationOptions | None = None) -> list[GenerationResult]:
        """Sinh completion cho một danh sách raw prompts, giữ nguyên thứ tự kết quả."""
```

### Các phương thức trừu tượng:

1. **`load()`**:
   * Chuẩn bị tài nguyên phần cứng, kiểm tra snapshot weights trên đĩa và khởi tạo engine.
   * Yêu cầu đảm bảo tính chất Idempotent: gọi nhiều lần sau khi đã load thành công sẽ là no-op.
2. **`generate(prompt, options)`**:
   * Thực hiện completion đơn lẻ từ chuỗi prompt thô. Thích hợp cho các mô hình base hoặc khi tự quản lý prompt format thủ công.
3. **`chat(messages, options)`**:
   * Tiếp nhận danh sách đối tượng `ChatMessage(role, content)`. Áp dụng chat template chuẩn (Jinja template của model checkpoint như Qwen-Chat) để sinh câu trả lời cho vai trò `assistant`.
   * Thiết kế Stateless: Không tự lưu trữ lịch sử hội thoại trong đối tượng; caller chịu trách nhiệm truyền toàn bộ messages của phiên hội thoại.
4. **`generate_batch(prompts, options)`**:
   * Tận dụng khả năng Continuous Batching của các engine hiện đại (vLLM) để xử lý đồng thời nhiều prompts, trả về danh sách `GenerationResult` bảo toàn đúng thứ tự danh sách đầu vào.

---

## 3. Tại Sao Lại Code Như Vậy?

* **Dependency Inversion Principle (DIP):** Module cấp cao (`Text2SQLGenerator`) chỉ phụ thuộc vào abstraction (`BaseLLM`), không phụ thuộc vào implementation cụ thể (`VLLMModel`).
* **Khả năng kiểm thử (Testability):** Trong môi trường kiểm thử CI/CD không có GPU, ta có thể tạo `MockLLM(BaseLLM)` trả về các chuỗi JSON/SQL giả lập để kiểm tra 100% logic của B0.3 và B0.5 với tốc độ chỉ vài mili-giây.
* **Tách biệt Stateless Inference:** Việc không lưu trạng thái hội thoại bên trong `BaseLLM` giúp mô hình an toàn, tránh race conditions khi xử lý nhiều câu hỏi khác nhau của tập benchmark.

---

## 4. Tương Thích & Mối Liên Hệ

* Được kế thừa bởi: [`VLLMModel`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/vllm_model.md) trong môi trường GPU production.
* Được sử dụng bởi: [`Text2SQLGenerator`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/generator.md) để gửi request sinh câu truy vấn SQL.
* Được triển khai giả lập bởi: `MockLLM` trong [`tests/test_b03_text2sql.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_b03_text2sql.py).

---

## 5. Nếu Không Có File Này Thì Sao?

* Mã nguồn ứng dụng sẽ phải gọi trực tiếp `vllm.LLM` ở khắp mọi nơi.
* Không thể viết unit test nếu máy không cài vLLM hoặc không có card đồ họa NVIDIA tương thích.
* Nếu cuộc thi yêu cầu chuyển đổi engine hoặc chạy inference qua endpoint tối ưu khác, ta sẽ phải sửa lại toàn bộ codebase.

