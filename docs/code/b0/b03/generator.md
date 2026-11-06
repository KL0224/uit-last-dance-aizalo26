# Giải Thích Mã Nguồn: `generator.py` (B0.3)

**Đường dẫn file:** [`src/datamate/b0/b03/generator.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/generator.py)  
**Thuộc module:** B0.3 Text-to-SQL LLM Layer  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `generator.py` định nghĩa lớp điều phối cấp cao `Text2SQLGenerator`. Đây là "trái tim" gắn kết toàn bộ các thành phần rời rạc của B0.3 (Mô hình LLM `BaseLLM`, Bộ xây dựng Prompt `prompt.py`, và Bộ giải mã `parser.py`) thành một dịch vụ đồng nhất, dễ sử dụng. Lớp này hỗ trợ cả hai luồng xử lý cốt lõi:
1. **Luồng tạo sinh ban đầu (`generate`)**: Sinh câu truy vấn SQL từ câu hỏi và ngữ cảnh dữ liệu.
2. **Luồng tự phục hồi (`repair`)**: Thực hiện 1 lần thử lại có giới hạn (**One Bounded Retry**) để sửa câu truy vấn khi bước thực thi cơ sở dữ liệu gặp lỗi.

---

## 2. Chi Tiết Lớp `Text2SQLGenerator`

```python
class Text2SQLGenerator:
    def __init__(self, model: BaseLLM) -> None:
        self.model = model

    def generate(
        self,
        context: Any,
        question: str,
        as_of_date: str,
        *,
        options: GenerationOptions | None = None,
    ) -> Text2SQLResult:
        ...

    def repair(
        self,
        context: Any,
        question: str,
        as_of_date: str,
        previous_sql: str,
        error_message: str,
        *,
        options: GenerationOptions | None = None,
    ) -> Text2SQLResult:
        ...
```

### 2.1. Phương thức `generate(...)`
* **Nhiệm vụ:** Tiếp nhận ngữ cảnh nghiệp vụ (`BusinessContext` từ B0.2 hoặc `dict` Data Contract), câu hỏi tự nhiên tiếng Việt và ngày tham chiếu `as_of_date`.
* **Quy trình:**
  1. Gọi `build_text2sql_messages(context, question, as_of_date)` để tạo cấu trúc `ChatMessage`.
  2. Gửi qua `self.model.chat(messages, options=options)`.
  3. Đưa chuỗi completion nhận được qua `parse_text2sql_response(gen_result.text)`.
  4. Trả về đối tượng [`Text2SQLResult`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/types.md).

### 2.2. Phương thức `repair(...)`
* **Nhiệm vụ:** Thực hiện One Bounded Retry khi B0.4 DuckDB Executor ném lỗi cú pháp (SyntaxError), lỗi bảng (CatalogError), hoặc lỗi cột (BinderError).
* **Quy trình:**
  1. Gọi `build_repair_messages(...)` để nhúng câu SQL bị lỗi và thông báo lỗi DuckDB chi tiết vào prompt.
  2. Kích hoạt `self.model.chat(...)` với nhiệt độ thấp (temperature thấp để greedy và thận trọng hơn).
  3. Bóc tách câu SQL mới bằng `parse_text2sql_response(...)`.
  4. Trả về kết quả `Text2SQLResult` đã được hiệu chỉnh.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Tuân thủ mẫu thiết kế Facade:**
   Thay vì caller phải tự gọi 3 bước riêng lẻ (gọi prompt builder $\rightarrow$ gọi model chat $\rightarrow$ gọi parser), `Text2SQLGenerator` đóng gói toàn bộ quy trình này thành một hàm gọi duy nhất `generator.generate(...)`.
2. **Hỗ trợ Bounded Retry có chủ đích:**
   Cơ chế Bounded Retry là một yêu cầu kỹ thuật trọng tâm của kiến trúc Baseline B0 nhằm gia tăng tỷ lệ thực thi thành công của SQL mà không làm tăng thời gian xử lý quá mức. Bằng cách thiết kế phương thức `repair(...)` tường minh, hệ thống dễ dàng kiểm soát được giới hạn thử lại (tối đa 1 lần).

---

## 4. Tương Thích & Mối Liên Hệ

* **Nhận vào:** Đối tượng [`BaseLLM`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/base.md) (có thể là `VLLMModel` trên GPU hoặc `MockLLM` khi kiểm thử).
* **Sử dụng:** [`prompt.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/prompt.md) và [`parser.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/parser.md).
* **Đầu ra:** Cung cấp kết quả trực tiếp cho pipeline chính để chuyển sang B0.4 Executor và B0.5 Output Gatekeeper.

---

## 5. Nếu Không Có File Này Thì Sao?

* Pipeline điều phối chính sẽ phải viết lại logic kết nối prompt $\rightarrow$ LLM $\rightarrow$ parser ở nhiều nơi, gây trùng lặp mã (DRY violation) và khó bảo trì khi cần thay đổi format prompt hoặc parser.
* Không có giao diện thống nhất để thực hiện bước Bounded Retry khi câu truy vấn SQL gặp sự cố thực thi.

