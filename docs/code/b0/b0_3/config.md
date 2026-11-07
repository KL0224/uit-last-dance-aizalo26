# `config.py` — Đọc cấu hình TOML

> **Summary:** File cung cấp `load_config()` để đọc TOML và trả về hai object: `ModelConfig` cho bước nạp engine và `GenerationOptions` cho sampling mặc định. Đường dẫn weights tương đối được tính từ thư mục chứa file TOML.

**File nguồn:** [`src/llm/config.py`](../../../../src/llm/config.py).

## Mục đích và ý nghĩa

File tách việc đọc cấu hình ra khỏi backend inference. Nó dùng `tomllib` trong thư viện chuẩn, không import vLLM hay khởi tạo GPU. Các kiểm tra giá trị cấu hình được thực hiện tiếp trong dataclass của [`types.py`](types.md).

TOML được tổ chức thành hai section:

| Section | Ý nghĩa | Bắt buộc |
| --- | --- | --- |
| `[model]` | Các trường dùng tạo `ModelConfig`, gồm `model_path` | Có |
| `[generation]` | Các trường dùng tạo `GenerationOptions` | Không; nếu thiếu sẽ dùng toàn bộ mặc định |

Các section ngoài `model` và `generation` bị từ chối. Khóa không đúng tên trong hai section cũng không bị bỏ qua: constructor của dataclass sẽ báo lỗi.

## `load_config(path: str | Path) -> tuple[ModelConfig, GenerationOptions]`

### Tác dụng

Đọc một file TOML, chuẩn hóa đường dẫn model và tạo các object cấu hình đã qua bước kiểm tra của dataclass.

### Input

| Tham số | Kiểu | Ý nghĩa |
| --- | --- | --- |
| `path` | `str` hoặc `pathlib.Path` | Đường dẫn file TOML; chấp nhận `~`. Nếu tương đối, đường dẫn **file TOML** được tính từ thư mục làm việc hiện tại. |

Các giá trị bên trong TOML phải phù hợp với các trường của `ModelConfig` và `GenerationOptions`; type annotation không thay thế việc kiểm tra schema đầy đủ.

### Luồng xử lý

1. Chuyển `path` thành `Path`, mở rộng `~` rồi gọi `resolve()`.
2. Mở file ở chế độ nhị phân `rb` và đọc bằng `tomllib.load()`.
3. Kiểm tra section lạ; nếu có, phát sinh `ValueError` chứa tên các section đó.
4. Sao chép section `model` sang dictionary và lấy `model_path`.
5. Mở rộng `~` trong `model_path`. Nếu đường dẫn này tương đối, nối nó với thư mục chứa TOML.
6. Tạo `ModelConfig(**model_values)` và `GenerationOptions(**document.get("generation", {}))`.

`ModelConfig.__post_init__()` tiếp tục chuyển đường dẫn model thành đường dẫn tuyệt đối. Hàm này chưa kiểm tra snapshot có tồn tại hoặc nạp được không; bước đó nằm trong `VLLMModel.load()`.

### Output

Tuple gồm hai phần tử theo đúng thứ tự:

```python
(model_config, generation_options)
```

- `model_config: ModelConfig`: Cấu hình đường dẫn weights và tham số engine.
- `generation_options: GenerationOptions`: Bộ tùy chọn sampling mặc định, dùng giá trị mặc định cho các trường không khai báo.

### Lỗi có thể phát sinh

Hàm không bắt và bọc lại exception:

| Lỗi | Trường hợp tiêu biểu |
| --- | --- |
| `OSError` và subclass như `FileNotFoundError`, `PermissionError` | Không mở hoặc đọc được file cấu hình |
| `tomllib.TOMLDecodeError` | Nội dung không đúng cú pháp TOML |
| `ValueError` | Có section lạ hoặc giá trị vi phạm kiểm tra của dataclass |
| `KeyError` | Thiếu section `model` hoặc khóa `model_path` |
| `TypeError` | Khóa không được constructor hỗ trợ hoặc giá trị không phù hợp với phép xử lý bên trong |

### Ví dụ

```python
from llm import VLLMModel, load_config

config, defaults = load_config("configs/qwen3_5_9b.toml")
model = VLLMModel(config, default_options=defaults)
model.load()
```

Nếu TOML tại `/project/configs/model.toml` khai báo `model_path = "../.models/checkpoint"`, đường dẫn weights sau chuẩn hóa là `/project/.models/checkpoint`, bất kể thư mục làm việc khi gọi hàm.
