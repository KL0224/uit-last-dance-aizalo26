# `vllm_model.py` — Backend inference bằng vLLM

> **Summary:** `VLLMModel` triển khai `BaseLLM` bằng vLLM offline: nạp snapshot local trực tiếp trong process Python, sinh completion đơn/batch và phản hồi chat. Backend dùng kiểu dữ liệu chung, trì hoãn import vLLM đến `load()` và chuyển lỗi engine sang exception của tầng LLM.

**File nguồn:** [`src/llm/vllm_model.py`](../../../../src/llm/vllm_model.py). Tài liệu mang tên `vllm.md` theo yêu cầu; repository hiện không có file `src/llm/vllm.py`.

## Mục đích và ý nghĩa

`VLLMModel(BaseLLM)` nối interface ứng dụng với engine vLLM, không gọi HTTP API. Mỗi instance đã load sở hữu một engine; tạo và load nhiều instance sẽ tạo nhiều engine/bản weights. Khi các tác vụ chỉ khác prompt, có thể dùng chung instance. Class không hỗ trợ gọi đồng thời từ nhiều thread và không cung cấp method unload.

Luồng sử dụng chính:

```text
ModelConfig + GenerationOptions
            ↓
       VLLMModel(...)
            ↓
          load()
            ↓
generate() / generate_batch() / chat()
            ↓
GenerationResult hoặc list[GenerationResult]
```

## Từng method và property

### `VLLMModel.__init__(self, config: ModelConfig, default_options: GenerationOptions | None = None) -> None`

- **Tác dụng:** Lưu cấu hình và khởi tạo trạng thái backend, chưa import vLLM và chưa cấp phát VRAM.
- **Input:**
  - `config`: Cấu hình engine, gồm đường dẫn snapshot và giới hạn tài nguyên.
  - `default_options`: Sampling mặc định. Nếu là `None`, tạo `GenerationOptions()` mới.
- **Output:** Method trả `None`; biểu thức `VLLMModel(...)` trả instance mới.
- **Trạng thái sau khởi tạo:** `self.config` và `self.default_options` được gán; `_engine` và `_sampling_params_class` đều là `None`. Model chưa sẵn sàng inference.

### `VLLMModel.is_loaded(self) -> bool` — property

- **Tác dụng:** Cho biết `_engine` đã được gán hay chưa.
- **Input:** `self`; truy cập bằng `model.is_loaded`, không gọi `model.is_loaded()`.
- **Output:** `True` nếu `_engine is not None`, ngược lại là `False`.
- **Giới hạn:** Không kiểm tra sức khỏe GPU hay khả năng xử lý request hiện tại của engine.

### `VLLMModel.load(self) -> None`

**Tác dụng:** Kiểm tra snapshot local, import dependency và khởi tạo một engine vLLM. Nếu `is_loaded` đã là `True`, method trả về ngay, không tạo engine mới.

**Input:** `self`; dùng `self.config`, không nhận tham số riêng.

**Luồng xử lý:**

1. Kiểm tra `model_path` là thư mục và có file `config.json`. Method không tự tải weights từ model ID.
2. Nếu có `.model-download.json`, đọc JSON và yêu cầu nội dung là dictionary có `status == "complete"`. Snapshot từ nguồn khác không bắt buộc có manifest này.
3. Import `LLM` và `SamplingParams` từ `vllm` ngay trong method. Nhờ lazy import, việc import package `llm` và tạo instance không đòi môi trường GPU.
4. Tạo `LLM(...)` với các tham số sau:

| Tham số engine | Nguồn giá trị |
| --- | --- |
| `model`, `tokenizer` | `str(self.config.model_path)` |
| `dtype` | `self.config.dtype` |
| `max_model_len` | `self.config.max_model_len` |
| `gpu_memory_utilization` | `self.config.gpu_memory_utilization` |
| `tensor_parallel_size` | `self.config.tensor_parallel_size` |
| `max_num_seqs` | `self.config.max_num_seqs` |
| `trust_remote_code` | `self.config.trust_remote_code` |
| `generation_config` | Chuỗi cố định `"vllm"`, tránh để generation config của checkpoint tự thay sampling defaults của ứng dụng |

5. Chỉ sau khi khởi tạo thành công mới gán `_sampling_params_class = SamplingParams` và `_engine = engine`.

**Output:** `None`; engine được lưu trong instance và `is_loaded` trở thành `True`.

**Lỗi:**

- `ModelLoadError` nếu snapshot không có cấu trúc tối thiểu hoặc manifest không hợp lệ/chưa hoàn tất.
- `ImportError` trong khối import/khởi tạo được bọc thành `ModelLoadError` với thông báo kiểm tra dependency.
- Exception khác trong khối khởi tạo engine được bọc thành `ModelLoadError` với đường dẫn model và thông báo gốc.
- Các lỗi được bọc giữ nguyên nguyên nhân qua `raise ... from exc`. Kiểm tra snapshot không xác minh mọi file weights; lỗi còn lại có thể chỉ được engine phát hiện khi khởi tạo.

### `VLLMModel._require_loaded(self) -> None`

- **Tác dụng:** Chặn inference khi chưa có engine.
- **Input:** `self`; đọc property `is_loaded`.
- **Output:** `None` nếu đã load.
- **Lỗi:** `ModelNotLoadedError("Call model.load() before inference.")` nếu chưa load.
- **Nơi sử dụng:** Đầu `generate_batch()` và `chat()`; `generate()` đi qua kiểm tra này gián tiếp qua batch.

### `VLLMModel._sampling_params(self, options: GenerationOptions | None) -> Any`

**Tác dụng:** Chọn sampling cho request và chuyển sang object `vllm.SamplingParams`.

**Input:**

- `self`: Chứa cấu hình context, sampling mặc định và class `SamplingParams` lấy từ `load()`.
- `options`: Nếu khác `None`, dùng nguyên object này; nếu là `None`, dùng `self.default_options`. Không trộn từng trường với bộ mặc định của instance.

Trước khi chuyển đổi, method yêu cầu `max_new_tokens < self.config.max_model_len` để còn chỗ cho input. Đây chỉ là kiểm tra sơ bộ; chưa tính số token prompt thực tế.

| Tham số `SamplingParams` | Giá trị |
| --- | --- |
| `n` | `1`, chỉ sinh một candidate cho mỗi request |
| `max_tokens` | `selected.max_new_tokens` |
| `temperature`, `top_p`, `top_k` | Trường cùng tên của `selected` |
| `repetition_penalty`, `presence_penalty` | Trường cùng tên của `selected` |
| `stop` | `list(selected.stop)` nếu có phần tử; ngược lại `None` |
| `seed` | `selected.seed` |

**Output:** Instance `SamplingParams`; annotation là `Any` để module không phải import vLLM ở cấp file.

**Lỗi:** `ValueError` nếu output budget không chừa context cho input. Lỗi từ constructor `SamplingParams` cũng được truyền trực tiếp ra ngoài. Method không tự gọi `_require_loaded()`; các public method đảm bảo đã load trước khi dùng nó.

### `VLLMModel._convert_outputs(outputs: list[Any], expected: int) -> list[GenerationResult]` — static method

**Tác dụng:** Chuyển output engine sang kết quả chung và kiểm tra engine không bỏ sót request.

**Input:**

- `outputs`: Danh sách kết quả vLLM. Mỗi phần tử cần có `prompt_token_ids` và danh sách `outputs` chứa đúng một completion; completion cần có `text`, `token_ids`, `finish_reason`.
- `expected`: Số kết quả mong đợi, tương ứng số prompt hoặc bằng `1` khi chat.
- Đây là `@staticmethod`, không nhận `self` và không dùng trạng thái engine.

**Xử lý:**

1. Yêu cầu `len(outputs) == expected`.
2. Với mỗi request, yêu cầu có đúng một candidate và `prompt_token_ids` khác `None`.
3. Tạo `GenerationResult` từ candidate đó:

| Trường kết quả | Cách lấy |
| --- | --- |
| `text` | `completion.text` |
| `input_tokens` | `len(output.prompt_token_ids)` |
| `output_tokens` | `len(completion.token_ids)` |
| `finish_reason` | `completion.finish_reason` |

**Output:** Danh sách `GenerationResult` theo thứ tự của `outputs`; method không tự sắp xếp lại theo request ID.

**Lỗi:** `InferenceError` nếu số kết quả sai, số candidate khác `1` hoặc thiếu prompt token IDs. Nếu object thiếu các thuộc tính cần thiết, lỗi truy cập thuộc tính cũng có thể phát sinh; khi đi qua public API, lỗi chuyển đổi trong khối `try` sẽ được bọc thành `InferenceError`.

### `VLLMModel.generate(self, prompt: str, *, options: GenerationOptions | None = None) -> GenerationResult`

- **Tác dụng:** Sinh completion cho một raw prompt bằng cách gọi `generate_batch([prompt], options=options)[0]`, dùng cùng luồng kiểm tra và inference với batch.
- **Input:**
  - `prompt`: Chuỗi đầu vào, không được tự thêm chat template.
  - `options`: Sampling cho request, truyền bằng tên; `None` dùng bộ mặc định của instance.
- **Output:** Một `GenerationResult` lấy từ phần tử đầu của kết quả batch.
- **Lỗi:** Truyền tiếp các lỗi từ `generate_batch()`, gồm chưa load, prompt sai kiểu, sampling không hợp lệ và lỗi inference.

### `VLLMModel.generate_batch(self, prompts: list[str], *, options: GenerationOptions | None = None) -> list[GenerationResult]`

**Tác dụng:** Gửi nhiều raw prompt cho vLLM trong một lần gọi; engine tự scheduling batch và trả kết quả theo thứ tự prompt. Backend không tự cắt ngắn prompt.

**Input:**

- `prompts`: Bắt buộc là `list`, mỗi phần tử là `str`. List rỗng được chấp nhận; chuỗi prompt rỗng không bị lớp này từ chối riêng.
- `options`: Một bộ sampling cho cả batch, truyền bằng tên; `None` dùng mặc định.

**Luồng xử lý:** Kiểm tra đã load → kiểm tra kiểu input → trả `[]` nếu batch rỗng → tạo sampling params → gọi `_engine.generate(prompts, sampling_params=params, use_tqdm=False)` → chuyển output qua `_convert_outputs()`.

**Output:** `list[GenerationResult]`, cùng số lượng và thứ tự với `prompts`. Batch rỗng chỉ trả `[]` sau khi đã xác nhận model được load; trường hợp này không tạo hoặc kiểm tra sampling params.

**Lỗi và phạm vi bắt lỗi:**

| Giai đoạn | Lỗi trả ra |
| --- | --- |
| Chưa load | `ModelNotLoadedError` |
| `prompts` không phải list hoặc có phần tử không phải chuỗi | `TypeError` |
| Tạo sampling params trước khối `try` | `ValueError` hoặc exception từ `SamplingParams`, không được bọc |
| Engine generate hoặc chuyển đổi kết quả trong khối `try` | Bọc thành `InferenceError("Batch generation failed: ...")`, giữ exception gốc trong `__cause__` |

Nếu tổng input/output vượt context, backend để engine báo lỗi thay vì tự truncate. Lỗi engine khi đó được bọc thành `InferenceError`.

### `VLLMModel.chat(self, messages: list[ChatMessage], *, options: GenerationOptions | None = None) -> GenerationResult`

**Tác dụng:** Sinh một phản hồi assistant cho hội thoại bằng chat template gốc của checkpoint. Backend không tự nối role marker và không lưu lịch sử sau lời gọi.

**Input:**

- `messages`: List không rỗng, mỗi phần tử là `ChatMessage`. Caller cung cấp đầy đủ lịch sử cần thiết theo thứ tự hội thoại.
- `options`: Sampling của request, truyền bằng tên; `None` dùng bộ mặc định.

**Luồng xử lý:**

1. Yêu cầu model đã load và kiểm tra messages.
2. Tạo sampling params, rồi chuyển messages thành payload dạng `[{"role": m.role, "content": m.content}, ...]`.
3. Gọi `_engine.chat()` với payload, sampling params, bản sao nông `dict(self.config.chat_template_kwargs)` và `use_tqdm=False`.
4. Chuyển output qua `_convert_outputs(outputs, expected=1)` rồi lấy phần tử đầu.

**Output:** Một `GenerationResult` chứa phản hồi mới. `input_tokens` được tính từ token IDs của prompt mà engine đã áp dụng template; `text` được giữ nguyên, kể cả thinking markers/content nếu có.

**Lỗi và phạm vi bắt lỗi:**

| Trường hợp | Lỗi trả ra |
| --- | --- |
| Chưa load | `ModelNotLoadedError` |
| `messages` không phải list hoặc là list rỗng | `ValueError` |
| Có phần tử không phải `ChatMessage` | `TypeError` |
| Tạo sampling params trước khối `try` | `ValueError` hoặc lỗi từ `SamplingParams`, không được bọc |
| Engine áp dụng template, sinh phản hồi hoặc chuyển đổi kết quả thất bại trong khối `try` | `InferenceError("Chat generation failed: ...")`, giữ exception gốc |

Tham số như `enable_thinking` trong `chat_template_kwargs` chỉ tác động đường `chat()` nếu template hỗ trợ; không được tự áp dụng cho `generate()` hoặc `generate_batch()`.

## Ví dụ sử dụng

```python
from llm import ChatMessage, GenerationOptions, VLLMModel, load_config

config, defaults = load_config("configs/qwen3_5_9b.toml")
model = VLLMModel(config, default_options=defaults)
model.load()

completion = model.generate("Việt Nam có thủ đô là")
batch = model.generate_batch(["1 + 1 =", "2 + 2 ="])
reply = model.chat(
    [ChatMessage(role="user", content="Giải thích ngắn gọn về LLM.")],
    options=GenerationOptions(max_new_tokens=256, temperature=0),
)
print(reply.text)
```

Trong ví dụ, `options` của `chat()` là một bộ `GenerationOptions` mới: các trường không truyền dùng mặc định của dataclass, không kế thừa từng trường từ `defaults` đọc trong TOML.
