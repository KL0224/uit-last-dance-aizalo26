# `errors.py` — Các exception của tầng LLM

> **Summary:** File định nghĩa bốn class exception giúp ứng dụng phân biệt lỗi chưa load model, lỗi nạp model và lỗi inference. Các class không phụ thuộc vLLM; caller có thể bắt toàn bộ lỗi thuộc nhóm này qua `LLMError`.

**File nguồn:** [`src/llm/errors.py`](../../../../src/llm/errors.py).

## Mục đích và ý nghĩa

Ứng dụng không cần import exception riêng của inference engine. Backend chuyển các lỗi thích hợp sang các kiểu chung trong file này để caller xử lý theo giai đoạn xảy ra lỗi.

Quan hệ kế thừa:

```text
RuntimeError
└── LLMError
    ├── ModelNotLoadedError
    ├── ModelLoadError
    └── InferenceError
```

## Các class

| Class | Ý nghĩa | Nơi phát sinh trong backend hiện tại |
| --- | --- | --- |
| `LLMError(RuntimeError)` | Lỗi chung của tầng model; class cha để bắt cả nhóm | Các class con kế thừa từ đây |
| `ModelNotLoadedError(LLMError)` | Caller yêu cầu inference khi engine chưa được khởi tạo | `VLLMModel._require_loaded()` |
| `ModelLoadError(LLMError)` | Không thể nạp model: snapshot thiếu/không hợp lệ, manifest chưa hoàn tất, thiếu dependency hoặc engine khởi tạo thất bại | `VLLMModel.load()` |
| `InferenceError(LLMError)` | Quá trình sinh hoặc chuyển đổi kết quả inference thất bại | `VLLMModel._convert_outputs()`, `generate_batch()` và `chat()` |

## Function, constructor, input và output

File **không định nghĩa function hay method riêng**, kể cả `__init__`. Bốn class kế thừa constructor và hành vi exception từ `RuntimeError`.

- **Tác dụng khi khởi tạo:** Tạo một object exception để có thể `raise` hoặc kiểm tra trong `except`.
- **Input:** Các đối số vị trí của constructor exception; trong project thường là một chuỗi thông báo, ví dụ `ModelLoadError("Missing model snapshot")`.
- **Output:** Instance của class exception tương ứng; các đối số được lưu trong thuộc tính `args`. Khởi tạo object tự nó chưa làm chương trình phát sinh lỗi; lệnh `raise` mới phát sinh exception.

Khi backend dùng `raise ... from exc`, exception gốc được giữ trong `__cause__`. Cơ chế này do Python cung cấp, không phải logic riêng trong các class. Những lỗi được tạo trực tiếp, như snapshot không hợp lệ hoặc số output sai, có thể không có nguyên nhân gốc được chain.

## Cách sử dụng

```python
from llm import InferenceError, LLMError, ModelLoadError, ModelNotLoadedError

try:
    model.load()
    result = model.generate("Xin chào")
except ModelNotLoadedError as exc:
    print(f"Model chưa được load: {exc}")
except ModelLoadError as exc:
    print(f"Không nạp được model: {exc}")
except InferenceError as exc:
    print(f"Sinh nội dung thất bại: {exc}")
```

Nếu không cần phân biệt từng nhóm, dùng `except LLMError as exc` để bắt chung.

**Phạm vi bắt lỗi:** Không phải mọi lỗi từ public API đều là `LLMError`. Kiểm tra kiểu input và sampling trước khi gọi engine có thể phát sinh trực tiếp `TypeError` hoặc `ValueError`; `load_config()` cũng để nguyên lỗi đọc file, TOML và cấu hình. Xem [`config.md`](config.md) và [`vllm.md`](vllm.md).
