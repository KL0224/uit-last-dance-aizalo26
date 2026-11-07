# `types.py` — Các kiểu dữ liệu chung

> **Summary:** File định nghĩa bốn dataclass: `ChatMessage` cho một message hội thoại, `GenerationOptions` cho sampling, `ModelConfig` cho bước nạp engine và `GenerationResult` cho kết quả. Các kiểu này không phụ thuộc PyTorch, CUDA hay vLLM.

**File nguồn:** [`src/llm/types.py`](../../../../src/llm/types.py).

## Mục đích và ý nghĩa

Các lớp dữ liệu tạo hợp đồng chung giữa ứng dụng, bộ đọc cấu hình và backend. Nhờ đó, ứng dụng không cần nhận trực tiếp object cấu hình hoặc kết quả riêng của vLLM.

Cả bốn lớp dùng `@dataclass(frozen=True)`: Python tự sinh constructor `__init__` và ngăn gán lại thuộc tính theo cách thông thường. Đây không phải bất biến sâu: dictionary `ModelConfig.chat_template_kwargs` vẫn có thể bị sửa nội dung. Type annotation cũng không tự kiểm tra mọi kiểu dữ liệu ở runtime; các kiểm tra rõ ràng nằm trong những `__post_init__()` dưới đây.

## `ChatMessage`

Biểu diễn một message văn bản. Phiên bản này chưa nhận ảnh, tool calls hoặc audio.

### Constructor do dataclass sinh

```python
ChatMessage(role: Literal["system", "user", "assistant"], content: str)
```

- **Tác dụng:** Tạo message rồi tự gọi `__post_init__()` để kiểm tra.
- **Input:** `role` là vai trò người gửi; `content` là nội dung text. Cả hai bắt buộc.
- **Output:** Instance `ChatMessage` hợp lệ, hoặc exception khi kiểm tra thất bại.

### `ChatMessage.__post_init__(self) -> None`

- **Tác dụng:** Kiểm tra `role` thuộc `system`, `user`, `assistant` và `content` là `str`.
- **Input:** `self` đã được constructor gán các trường `role` và `content`; không nhận đối số cấu hình riêng.
- **Output:** `None`; object giữ nguyên các giá trị đã truyền nếu hợp lệ.
- **Lỗi:** `ValueError` nếu role không được hỗ trợ; `TypeError` nếu content không phải chuỗi. Chuỗi content rỗng vẫn được chấp nhận.

## `GenerationOptions`

Lưu các tham số sampling cho toàn bộ một request hoặc batch; các tham số này không thay đổi weights.

### Constructor do dataclass sinh

**Input:** Các trường sau đều có thể bỏ qua để dùng mặc định:

| Trường | Kiểu | Mặc định | Ý nghĩa |
| --- | --- | --- | --- |
| `max_new_tokens` | `int` | `1024` | Giới hạn số token output |
| `temperature` | `float` | `0.7` | Điều chỉnh độ ngẫu nhiên khi chọn token; `0` dùng greedy decoding |
| `top_p` | `float` | `0.8` | Ngưỡng xác suất tích lũy của nucleus sampling |
| `top_k` | `int` | `20` | Giới hạn số ứng viên token; `-1` tắt giới hạn này |
| `repetition_penalty` | `float` | `1.0` | Hệ số điều chỉnh lặp token; `1.0` là mức trung tính |
| `presence_penalty` | `float` | `1.5` | Điều chỉnh theo việc token đã xuất hiện; giá trị dương hạn chế xuất hiện lại |
| `stop` | `tuple[str, ...]` | `()` | Các chuỗi dùng làm điều kiện dừng |
| `seed` | `int \| None` | `None` | Seed sampling nếu được cung cấp |

- **Tác dụng:** Gán các trường rồi chạy kiểm tra và chuẩn hóa `stop` trong `__post_init__()`.
- **Output:** Instance `GenerationOptions`, hoặc exception nếu kiểm tra thất bại.

`max_new_tokens` chỉ giới hạn output. Tổng token input và output vẫn phải nằm trong `max_model_len`; engine kiểm tra bằng tokenizer thực tế. Seed không đảm bảo kết quả giống từng bit giữa phần cứng hoặc phiên bản engine khác nhau.

### `GenerationOptions.__post_init__(self) -> None`

- **Tác dụng:** Kiểm tra miền giá trị và chuyển `stop` thành tuple để caller không sửa được nó thông qua list ban đầu.
- **Input:** `self` với các trường sampling vừa được khởi tạo. Dù annotation của `stop` là tuple, code cũng nhận list chuỗi từ TOML và chuyển thành tuple.
- **Output:** `None`; `self.stop` được chuẩn hóa bằng `object.__setattr__()` dù dataclass có `frozen=True`.
- **Các điều kiện được kiểm tra:**
  - `max_new_tokens >= 1`.
  - `temperature >= 0` và `0 < top_p <= 1`.
  - `top_k == -1` hoặc `top_k >= 1`.
  - `repetition_penalty > 0` và `-2 <= presence_penalty <= 2`.
  - `stop` không được là một chuỗi đơn; mỗi phần tử phải là chuỗi không rỗng. Sequence rỗng hợp lệ.
- **Lỗi:** Các điều kiện trên không thỏa sẽ phát sinh `ValueError`. Kiểu dữ liệu không hỗ trợ phép so sánh hoặc duyệt cũng có thể gây `TypeError` trực tiếp; method không kiểm tra toàn bộ annotation, chẳng hạn không kiểm tra riêng kiểu của `seed`.

Method chưa so sánh `max_new_tokens` với `ModelConfig.max_model_len`; bước đó nằm trong `VLLMModel._sampling_params()`.

## `ModelConfig`

Lưu cấu hình khởi tạo engine và thông số truyền vào chat template.

### Constructor do dataclass sinh

**Input:**

| Trường | Kiểu | Mặc định | Ý nghĩa |
| --- | --- | --- | --- |
| `model_path` | `Path` | Bắt buộc | Đường dẫn snapshot model trên đĩa |
| `dtype` | `str` | `"bfloat16"` | Kiểu dữ liệu tính toán truyền cho engine |
| `max_model_len` | `int` | `8192` | Giới hạn context gồm input và output |
| `gpu_memory_utilization` | `float` | `0.9` | Tỷ lệ bộ nhớ GPU dành cho engine |
| `tensor_parallel_size` | `int` | `1` | Mức tensor parallelism |
| `max_num_seqs` | `int` | `4` | Giới hạn số sequence engine xử lý đồng thời |
| `trust_remote_code` | `bool` | `False` | Cho phép engine dùng custom code của model khi cần |
| `chat_template_kwargs` | `dict[str, Any]` | Dict rỗng mới cho mỗi instance | Tham số bổ sung cho chat template của checkpoint |

- **Tác dụng:** Tạo cấu hình rồi chạy `__post_init__()`.
- **Output:** Instance `ModelConfig` với đường dẫn đã chuẩn hóa và dictionary template được sao chép.

`chat_template_kwargs` chỉ có ý nghĩa theo template của checkpoint. Ví dụ `enable_thinking` chỉ tác động nếu template hỗ trợ nó; backend truyền các tham số này qua `chat()`, không áp dụng cho raw prompt.

### `ModelConfig.__post_init__(self) -> None`

- **Tác dụng:** Chuẩn hóa đường dẫn model, kiểm tra một số tham số tài nguyên và sao chép dictionary template.
- **Input:** `self` với các trường vừa được constructor gán. `model_path` có thể là giá trị được `Path(...)` chấp nhận, như chuỗi đường dẫn.
- **Xử lý:**
  1. Dùng `Path(self.model_path).expanduser().resolve()` để tạo đường dẫn tuyệt đối. Nếu tạo trực tiếp từ đường dẫn tương đối, nó được tính từ thư mục làm việc; khi dùng `load_config()`, đường dẫn đã được neo vào thư mục TOML trước đó.
  2. Kiểm tra `max_model_len`, `tensor_parallel_size`, `max_num_seqs` đều lớn hơn hoặc bằng `1`.
  3. Kiểm tra `0 < gpu_memory_utilization < 1`.
  4. Sao chép nông `chat_template_kwargs` qua `dict(...)` để việc sửa dictionary gốc không làm đổi các mục cấp đầu của cấu hình.
- **Output:** `None`; các trường `model_path` và `chat_template_kwargs` được cập nhật trong bước khởi tạo.
- **Lỗi:** `ValueError` khi các giới hạn số học không hợp lệ; các thao tác chuyển đổi hoặc so sánh có thể phát sinh lỗi khác nếu input sai kiểu.
- **Giới hạn:** Không kiểm tra snapshot tồn tại, độ tương thích GPU, giá trị `dtype` hay sự hỗ trợ của template. Dictionary sao chép nông vẫn có thể chứa object lồng nhau dùng chung với caller.

## `GenerationResult`

Đóng gói kết quả độc lập với backend, không để lộ `RequestOutput` của vLLM.

### Constructor do dataclass sinh

```python
GenerationResult(
    text: str,
    input_tokens: int,
    output_tokens: int,
    finish_reason: str | None,
)
```

- **Tác dụng:** Tạo object kết quả; class không có `__post_init__()` hay method riêng để kiểm tra giá trị.
- **Input:**
  - `text`: Completion nguyên bản, không bao gồm việc tự nối lại prompt.
  - `input_tokens`: Số token input do backend ghi nhận; với chat, tính trên prompt đã được engine định dạng.
  - `output_tokens`: Số token completion.
  - `finish_reason`: Lý do kết thúc engine trả về, có thể là `None`; constructor vẫn yêu cầu truyền trường này.
- **Output:** Instance `GenerationResult`. Type annotation không tự kiểm tra các giá trị này.

Nếu model bật thinking, `text` có thể chứa cả thinking markers và nội dung suy nghĩ. Tầng model không tự parse hoặc xóa phần đó.

## Ví dụ tạo dữ liệu

```python
from pathlib import Path
from llm import ChatMessage, GenerationOptions, ModelConfig

config = ModelConfig(model_path=Path(".models/Qwen3.5-9B"))
options = GenerationOptions(max_new_tokens=256, temperature=0)
messages = [ChatMessage(role="user", content="Giải thích tensor parallelism.")]
```
