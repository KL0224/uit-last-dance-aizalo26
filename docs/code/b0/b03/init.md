# Giải Thích Mã Nguồn: `__init__.py` (B0.3)

**Đường dẫn file:** [`src/datamate/b0/b03/__init__.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/__init__.py)  
**Thuộc module:** B0.3 Text-to-SQL LLM Layer  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `__init__.py` đóng vai trò là **Điểm tiếp xúc công khai duy nhất (Public API Boundary)** cho toàn bộ module B0.3. Nhiệm vụ chính của file là chọn lọc và tái xuất khẩu (re-export) các lớp, hàm và ngoại lệ cần thiết cho các tầng khác mà **hoàn toàn không kích hoạt nạp runtime GPU** (vLLM, PyTorch hoặc CUDA).

---

## 2. Danh Mục Các Biểu Tượng Xuất Khẩu (`__all__`)

```python
__all__ = [
    # 1. Base LLM Interfaces & Model
    "BaseLLM",
    "VLLMModel",
    "load_config",
    # 2. Dataclasses & Data Types
    "ChatMessage",
    "GenerationOptions",
    "GenerationResult",
    "ModelConfig",
    "Text2SQLResult",
    # 3. Prompt & Parsing Tools
    "build_text2sql_messages",
    "build_repair_messages",
    "format_context_for_prompt",
    "parse_text2sql_response",
    "extract_tables_from_sql",
    "infer_answer_type_from_sql",
    # 4. High-level Orchestration
    "Text2SQLGenerator",
    # 5. Exceptions
    "LLMError",
    "ModelLoadError",
    "ModelNotLoadedError",
    "InferenceError",
    "Text2SQLParseError",
]
```

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Lazy Loading Runtime & GPU Isolation:**
   Nếu `__init__.py` trực tiếp `import vllm` hoặc `import torch`, bất kỳ script kiểm thử đơn vị hoặc module nào import `datamate.b0.b03` đều sẽ cố gắng kết nối tới driver NVIDIA/CUDA. Trên máy dev không có GPU hoặc môi trường CI, lệnh import sẽ thất bại ngay lập tức (`ImportError` hoặc `CUDA driver not found`). Vì vậy, `__init__.py` chỉ nạp các file Python thuần túy.
2. **Nguyên tắc đóng gói (Information Hiding):**
   Người dùng bên ngoài (như B0.2, B0.5 hoặc pipeline chính) chỉ cần gọi `from datamate.b0.b03 import Text2SQLGenerator, Text2SQLResult` mà không cần quan tâm cấu trúc chi tiết các file con bên trong (`generator.py`, `parser.py`, `prompt.py`).
3. **Explicit `__all__`:**
   Khai báo tường minh danh sách `__all__` giúp các công cụ phân tích tĩnh (linter, mypy, IDE autocompletion) nhận biết chính xác public symbols, đồng thời ngăn chặn rò rỉ các module nội bộ ngoài ý muốn.

---

## 4. Tương Thích & Ảnh Hưởng Đến Các Module Khác

* **Với B0.2 Context:** B0.2 hoặc Orchestrator có thể import `build_text2sql_messages` và `Text2SQLGenerator` để truyền thẳng `BusinessContext` vào sinh prompt.
* **Với B0.4 Executor:** B0.4 nhận câu lệnh SQL sạch sau khi được bóc tách từ `Text2SQLResult.sql`.
* **Với B0.5 Output Gate:** B0.5 có thể nhận trực tiếp đối tượng kết quả thông qua adapter `Text2SQLResult.to_b05_generation_result()`.

---

## 5. Nếu Không Có File Này Thì Sao?

* Python sẽ coi thư mục `b03` là một namespace package lỏng lẻo; các lệnh import dạng `from datamate.b0.b03 import ...` sẽ ném lỗi `ImportError: cannot import name ... from datamate.b0.b03`.
* Code ở các module khác buộc phải import sâu vào từng tệp (`from datamate.b0.b03.generator import ...`), làm mất tính trừu tượng và gây vỡ code diện rộng nếu tái cấu trúc nội bộ.

