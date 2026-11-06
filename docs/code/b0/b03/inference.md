# Giải Thích Mã Nguồn: `inference.py` (B0.3)

**Đường dẫn file:** [`src/datamate/b0/b03/inference.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/inference.py)  
**Thuộc module:** B0.3 Text-to-SQL LLM Layer  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `inference.py` đóng vai trò là **Kịch bản thực thi mẫu (Demonstration & Verification Script)** cho module B0.3. File này minh họa trực quan cách nạp cấu hình, khởi tạo mô hình suy luận `VLLMModel`, thực hiện hội thoại đơn giản, và sử dụng `Text2SQLGenerator` để sinh câu truy vấn SQL hoàn chỉnh từ một ngữ cảnh dữ liệu mẫu.

---

## 2. Chi Tiết Luồng Thực Thi

```python
def run_sample_inference(config_path: str | Path = "configs/qwen3_5_9b.toml") -> None:
```

### Các bước thực thi bên trong:
1. **Nạp cấu hình:**
   * Gọi `load_config(config_path)` để đọc các tham số GPU và sampling từ file TOML.
2. **Khởi tạo và tải mô hình:**
   * Tạo instance `model = VLLMModel(config, options)`.
   * Gọi `model.load()` để tải trọng số cục bộ vào VRAM.
3. **Thử nghiệm Chat đơn giản (Direct Chat):**
   * Gửi cặp thông điệp chào hỏi và yêu cầu giải thích khái niệm Text-to-SQL để xác nhận mô hình đang phản hồi bằng tiếng Việt trơn tru.
4. **Thử nghiệm Text-to-SQL cấp cao (High-Level Generation):**
   * Khởi tạo `generator = Text2SQLGenerator(model)`.
   * Cung cấp một `dummy_context` đại diện cho bảng `orders` (các cột `order_id`, `order_date`, `amount`).
   * Gửi câu hỏi nghiệp vụ: *"Tổng doanh thu năm 2025 là bao nhiêu?"* với ngày tham chiếu `as_of_date = "2026-01-01"`.
   * In ra cấu trúc `Text2SQLResult` thu được gồm `status`, `answer_type` và câu lệnh `sql`.

### Bảo vệ thực thi:
* Tệp có khối bảo vệ tiêu chuẩn:
  ```python
  if __name__ == "__main__":
      run_sample_inference()
  ```
  giúp tệp không vô tình tự kích hoạt khi được import vào các module khác.

---

## 3. Tại Sao Lại Code Như Vậy?

* **Hướng dẫn sử dụng thực tế (Living Documentation):**
  Lập trình viên mới hoặc các thành viên khác trong nhóm có thể mở ngay file này để hiểu cách sử dụng đúng API của B0.3 chỉ trong 30 giây mà không cần đọc hết toàn bộ tài liệu lý thuyết.
* **Kiểm tra tích hợp nhanh (Smoke Test) trên Server:**
  Khi vừa tải xong mô hình trên server GPU mới, chỉ cần chạy `python -m datamate.b0.b03.inference` là có thể xác nhận ngay máy chủ đã sẵn sàng cho pipeline chính hay chưa.

---

## 4. Tương Thích & Mối Liên Hệ

* Tích hợp toàn diện các thành phần của B0.3:
  * [`config.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/config.md) (`load_config`)
  * [`vllm_model.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/vllm_model.md) (`VLLMModel`)
  * [`types.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/types.md) (`ChatMessage`)
  * [`generator.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/generator.md) (`Text2SQLGenerator`)

---

## 5. Nếu Không Có File Này Thì Sao?

* Thiếu một điểm kiểm tra tích hợp mẫu độc lập để xác minh nhanh môi trường phần cứng GPU và thư viện vLLM trước khi tích hợp vào toàn bộ pipeline B0 lớn.

