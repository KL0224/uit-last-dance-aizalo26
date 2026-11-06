# Giải Thích Mã Nguồn: `errors.py` (B0.3)

**Đường dẫn file:** [`src/datamate/b0/b03/errors.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/errors.py)  
**Thuộc module:** B0.3 Text-to-SQL LLM Layer  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `errors.py` định nghĩa cây phả hệ các lớp ngoại lệ (Exception Hierarchy) chuyên biệt của tầng mô hình ngôn ngữ lớn và Text-to-SQL. Các ngoại lệ này hoàn toàn độc lập với vLLM hoặc PyTorch, cho phép tầng gọi bên ngoài (B0.4, B0.5 hoặc Pipeline Orchestrator) có thể bắt và xử lý lỗi một cách an toàn mà không cần import bất kỳ thư viện GPU nào.

---

## 2. Cây Phả Hệ Các Lớp Ngoại Lệ

```text
Exception
  └── RuntimeError
        └── LLMError (Gốc phân cấp cho tầng Model & Text-to-SQL)
              ├── ModelNotLoadedError (Gọi suy luận khi chưa gọi load)
              ├── ModelLoadError (Lỗi snapshot weights, GPU hoặc import engine)
              ├── InferenceError (Lỗi trong quá trình chạy generate/chat)
              └── Text2SQLParseError (Lỗi giải mã định dạng JSON/SQL từ phản hồi LLM)
```

### Chi tiết từng lớp lỗi:

1. **`LLMError(RuntimeError)`**:
   * Ngoại lệ cơ sở đại diện cho toàn bộ các lỗi phát sinh trong tầng mô hình. Bất kỳ ngoại lệ nào của B0.3 đều có thể được bắt bằng khối `except LLMError:`.
2. **`ModelNotLoadedError(LLMError)`**:
   * Được ném ra khi ứng dụng cố tình gọi các phương thức `generate()`, `chat()`, hoặc `generate_batch()` trước khi phương thức `model.load()` hoàn tất thành công.
3. **`ModelLoadError(LLMError)`**:
   * Được kích hoạt khi quá trình tải mô hình thất bại do:
     * Đường dẫn thư mục weights không tồn tại trên đĩa.
     * Thiếu file `config.json` của checkpoint Hugging Face.
     * File manifest download `.model-download.json` chưa hoàn tất (`status != 'complete'`).
     * Không cài đặt vLLM hoặc GPU không tương thích phần cứng.
4. **`InferenceError(LLMError)`**:
   * Xảy ra khi engine suy luận gặp sự cố trong quá trình tính toán (ví dụ: context length vượt ngưỡng `max_model_len`, lỗi CUDA runtime). Giữ nguyên exception gốc thông qua cơ chế Exception Chaining (`raise ... from exc`).
5. **`Text2SQLParseError(LLMError)`**:
   * Được ném ra khi văn bản sinh ra từ LLM hoàn toàn rỗng, bị cắt ngắn (truncated), hoặc cấu trúc chuỗi không thể phân tích cú pháp thành JSON/SQL hợp lệ ngay cả khi đã qua các cơ chế cứu hộ (fallback heuristics).

---

## 3. Tại Sao Lại Code Như Vậy?

* **Exception Chaining (`raise ... from exc`):** Bảo tồn nguyên vẹn stack trace của lỗi cấp thấp (từ C++/CUDA/vLLM) để phục vụ việc debug của kỹ sư mà vẫn cung cấp thông điệp lỗi trong sáng cho tầng ứng dụng.
* **Tách biệt với vLLM (`Decoupling`):** Nếu caller phải bắt lỗi `vllm.engine.async_llm.AsyncEngineDeadError`, thì caller bắt buộc phải import module vLLM đó. Việc bọc lại thành `InferenceError` giúp toàn bộ ứng dụng duy trì tính mô-đun hóa cao.

---

## 4. Tương Thích & Mối Liên Hệ

* Được ném ra bởi: [`VLLMModel`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/vllm_model.md) và [`parser.py`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/parser.md).
* Được bắt và điều hướng bởi: [`Text2SQLGenerator`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b03/generator.md) và tầng kiểm duyệt B0.5.

---

## 5. Nếu Không Có File Này Thì Sao?

* Ứng dụng sẽ phải sử dụng các ngoại lệ chung chung như `Exception` hoặc `RuntimeError`, gây khó khăn cho việc phân loại chính xác nguyên nhân lỗi (lỗi do chưa load model, lỗi do weights hỏng, hay do JSON sai cú pháp).
* Pipeline không thể xác định được lỗi nào là tạm thời (recoverable bằng retry) và lỗi nào là lỗi hệ thống nghiêm trọng (unrecoverable).

