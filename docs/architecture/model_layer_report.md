# Báo cáo kỹ thuật: tầng model local với vLLM

## 1. Mục tiêu và trạng thái bàn giao

Đã viết tầng model Python để ứng dụng có thể dùng một interface chung cho
`load()`, `generate()`, `chat()` và `generate_batch()`. Backend đầu tiên là
`VLLMModel`, trực tiếp load weights local vào inference engine của vLLM.
Checkpoint mẫu là `Qwen/Qwen3.5-9B`.

Theo yêu cầu, chỉ viết source, cấu hình, script và tài liệu. **Chưa cài dependency,
chưa tải weights, chưa chạy example/inference, chưa chạy test hoặc benchmark.**
Vì vậy chưa có xác nhận thực nghiệm về compatibility, VRAM, tốc độ hoặc chất
lượng kết quả. Các cấu hình GPU bên dưới là điểm xuất phát để thử trên server.

Chưa triển khai agent, trích xuất rulebook, semantic KB, Schema Selector,
text-to-SQL, tool calling, structured output hoặc verifier. Dữ liệu train và
những artifact đang có không bị thay đổi.

## 2. Cấu trúc source

| Thành phần | Vai trò |
| --- | --- |
| `pyproject.toml` | Package `zaic-llm`, Python 3.12, dependency optional theo mục đích |
| `.python-version` | Gợi ý Python 3.12 cho uv |
| `src/llm/types.py` | Kiểu message, cấu hình model, sampling và kết quả |
| `src/llm/base.py` | Interface `BaseLLM` độc lập backend |
| `src/llm/vllm_model.py` | Adapter offline vLLM với lazy import/load |
| `src/llm/errors.py` | Các lỗi chung để caller bắt mà không import vLLM |
| `src/llm/config.py` | Đọc TOML, resolve model path và tạo cấu hình |
| `src/llm/__init__.py` | Export public API |
| `configs/qwen3_5_9b.toml` | Cấu hình khởi đầu cho Qwen3.5-9B |
| `scripts/download_model.py` | Tải snapshot và ghi revision/status manifest |
| `scripts/download_model.sh` | Wrapper Bash gọi downloader từ project root |
| `examples/basic_usage.py` | Ví dụ load một lần và sử dụng cả ba kiểu inference |

Code ứng dụng đi qua interface này:

```text
Ứng dụng Python
    │ BaseLLM: generate / chat / generate_batch
    ▼
VLLMModel
    │ vllm.LLM + SamplingParams
    ▼
Weights local + tokenizer/chat template → GPU
```

Không có HTTP server hoặc API provider trong đường inference này. Hugging
Face Hub chỉ được dùng khi người dùng chủ động chạy script download.

## 3. Public API và lifecycle

### 3.1 Khởi tạo và load

```python
from llm import BaseLLM, VLLMModel, load_config

config, defaults = load_config("configs/qwen3_5_9b.toml")
model: BaseLLM = VLLMModel(config, default_options=defaults)
model.load()
```

Constructor chỉ lưu cấu hình; không import vLLM, kiểm tra GPU hoặc cấp phát
VRAM. `load()` kiểm tra thư mục local và `config.json`, kiểm tra trạng thái
manifest nếu có, rồi mới import vLLM và khởi tạo engine.

`load()` gọi lại sau khi thành công là no-op. Nếu load thất bại, exception
được giữ làm nguyên nhân của `ModelLoadError`; khi engine đã lỗi nghiêm trọng,
nên kết thúc process và thử lại thay vì giả định tài nguyên đã được dọn sạch.

Một object tương ứng một engine. Dùng chung object cho nhiều vai trò agent
nếu chỉ khác prompt. Nhiều object được load có thể tạo nhiều bản weights và
làm hết VRAM. Bản này đồng bộ, chưa cam kết thread safety. Batch nội bộ do
vLLM scheduling; đó không phải hỗ trợ gọi object đồng thời từ nhiều thread.

Chưa có `unload()` vì không cam kết `del` hoặc `empty_cache()` sẽ giải phóng
toàn bộ worker/runtime của vLLM. Kết thúc process là ranh giới lifecycle.

### 3.2 Các method inference

| Method | Input | Output | Hành vi |
| --- | --- | --- | --- |
| `generate(prompt, options=...)` | Một raw string | `GenerationResult` | Không áp dụng chat template |
| `chat(messages, options=...)` | Danh sách `ChatMessage` | `GenerationResult` | Áp dụng chat template của checkpoint |
| `generate_batch(prompts, options=...)` | Danh sách raw strings | Danh sách `GenerationResult` | Cùng options cho batch; giữ thứ tự input |

`generate()` dùng chung đường xử lý với batch một phần tử để tránh hai API
lệch hành vi. Sau khi load, batch rỗng trả `[]`. Mọi method inference, kể cả
batch rỗng, yêu cầu gọi `load()` trước.

`chat()` không lưu conversation history trong object. Caller truyền toàn bộ
messages cần dùng; tự thêm assistant reply vào lịch sử cho lượt tiếp theo.
Chỉ hỗ trợ role `system`, `user`, `assistant` và content text.

Ví dụ:

```python
from dataclasses import replace
from llm import ChatMessage

short = replace(defaults, max_new_tokens=128)
reply = model.chat(
    [ChatMessage(role="user", content="Khóa chính trong SQL là gì?")],
    options=short,
)
print(reply.text)
```

Với checkpoint instruct như Qwen, nên dùng `chat()` cho instruction tự nhiên.
`generate()` dành cho raw completion hoặc prompt đã được caller format.
`generate_batch()` cũng là raw completion; chưa có batch chat trong bản này.

### 3.3 Kiểu kết quả và generation options

`GenerationResult` chứa:

- `text`: completion nguyên bản, không kèm bản sao prompt.
- `input_tokens`: số token prompt thực tế; với chat gồm phần template.
- `output_tokens`: số token completion thực tế.
- `finish_reason`: lý do dừng do engine trả về, có thể là `stop` hoặc `length`.

Không trả trực tiếp object vLLM để tránh backend detail lan sang ứng dụng.
`finish_reason="length"` không bị xem là exception: caller cần kiểm tra nếu
ứng dụng đòi hỏi câu trả lời đầy đủ. Token usage không chứng minh nội dung đúng.

`GenerationOptions` có `max_new_tokens`, `temperature`, `top_p`, `top_k`,
`repetition_penalty`, `presence_penalty`, `stop`, `seed`. Options truyền vào
request thay thế nguyên object defaults, không merge từng field. Dùng
`dataclasses.replace(defaults, ...)` khi chỉ muốn override một vài field.

`max_new_tokens` chỉ giới hạn output; prompt cộng output phải vừa context.
Adapter kiểm tra output budget có chừa chỗ cho input và để engine kiểm tra
giới hạn thực tế theo tokenizer; không tự cắt prompt. Seed không đảm bảo
kết quả giống bit-for-bit giữa GPU, engine version hoặc cách scheduling batch.

### 3.4 Thinking và cấu hình riêng checkpoint

File mẫu có `[model.chat_template_kwargs] enable_thinking = false`.
Các kwargs này được gửi sang `LLM.chat()` của vLLM. Khi đổi model family, phải
xem template của model mới và bỏ/đổi kwargs không phù hợp.

Cấu hình thinking không tác động raw prompt của `generate()` hoặc
`generate_batch()`. Nếu bật thinking cho chat, `text` có thể chứa cả thinking
markers/content. Bản này không có reasoning parser hay structured JSON parser.

### 3.5 Xử lý lỗi

- `ModelNotLoadedError`: inference trước `load()`.
- `ModelLoadError`: đường dẫn/snapshot chưa đầy đủ, thiếu dependency hoặc lỗi load engine.
- `InferenceError`: lỗi inference hoặc engine trả kết quả không đúng số lượng mong đợi.
- `TypeError`/`ValueError`: input/options/config không hợp lệ.

Lỗi engine được giữ qua `raise ... from exc`. Không tự retry inference,
không tự sửa completion và không âm thầm fallback sang model khác.

## 4. Downloader và quản lý weights

Downloader mặc định nhận model ID `Qwen/Qwen3.5-9B`, revision `main` và đích
`.models/Qwen3.5-9B`. Relative output path của Python script tính theo working
directory; wrapper Bash chủ động chuyển về project root trước khi chạy.

Quy trình downloader:

1. Resolve branch/tag thành commit SHA cụ thể qua Hub.
2. Kiểm tra thư mục đích để tránh trộn model/revision khác nhau.
3. Ghi `.model-download.json` với trạng thái `downloading`.
4. Download toàn bộ snapshot theo SHA, gồm weights, config và tokenizer/template.
5. Đổi manifest thành `complete`, ghi thời điểm UTC.

Script không load model hoặc import torch. Có thể tải trên máy không có GPU
nếu đủ dung lượng đĩa và mạng. Bộ weights BF16 của model cỡ 9B ở quy mô hàng
chục GB; tổng snapshot, cache và dung lượng RAM/VRAM khi inference là các số
khác nhau. Không coi dung lượng weights là dự đoán chính xác VRAM sử dụng.

Nếu download bị ngắt, chạy lại cùng SHA và thư mục để Hub tận dụng cache.
Nếu lần trước dùng `main` và `main` đã đổi, dùng `--revision` theo
`resolved_revision` ghi trong manifest để tiếp tục đúng snapshot. Đổi revision
thì chọn thư mục đích mới. Không chạy nhiều downloader đồng thời trên cùng đích.

Manifest ghi nguồn và trạng thái tải, không thay thế kiểm chứng nội dung hay
là cơ chế chứng thực file sau khi bị sửa thủ công. Snapshot từ nguồn khác vẫn
có thể được load nếu không có manifest riêng này và engine đọc được đầy đủ.

Nếu cần token truy cập, dùng `HF_TOKEN` hoặc Hugging Face login đã có. Script
không có trường chứa token trong source/manifest. `.models/` và `.env` đã được
loại khỏi Git; nếu lưu weights ngoài `.models/`, tự đặt đường dẫn ngoài Git
hoặc bổ sung ignore phù hợp.

## 5. Các lệnh dành cho người dùng chạy sau

**Các lệnh dưới đây chỉ là hướng dẫn; chưa được thực thi trong lần bàn giao.**
Chạy từ project root. Không cần chạy download trên laptop nếu muốn chỉ chuẩn
bị và tải weights trực tiếp trên server.

### 5.1 Chỉ tải weights, không cài GPU runtime

```bash
uv sync --extra download
bash scripts/download_model.sh
```

Để cố định snapshot và đổi thư mục:

```bash
uv run --no-sync python scripts/download_model.py \
  --model-id Qwen/Qwen3.5-9B \
  --revision YOUR_COMMIT_SHA \
  --output-dir /srv/models/Qwen3.5-9B
```

Thay `YOUR_COMMIT_SHA` trước khi chạy. Sau đó sửa `model_path` trong TOML nếu
thư mục khác mặc định. Model path tương đối trong TOML luôn được resolve từ
thư mục chứa TOML, không phụ thuộc working directory.

### 5.2 Chuẩn bị inference trên server GPU

Ban tổ chức yêu cầu Blackwell, CUDA >= 12.8 và matching PyTorch/vLLM build.
Phải đối chiếu Docker guideline trước khi chốt môi trường nộp bài. Không cài
PyTorch/CUDA riêng lẻ tùy ý rồi giả định chúng tương thích với wheel vLLM.

Nếu chuẩn bị virtualenv độc lập trên server, sau khi chọn được bộ build CUDA
phù hợp, dependency khai báo của project có thể được cài bằng:

```bash
uv sync --extra download --extra inference
```

Lệnh này là bước resolve/cài dependency, **không phải bảo đảm wheel mặc định
phù hợp với image CUDA cụ thể của ban tổ chức**. Nếu dùng image đã có vLLM và
PyTorch phù hợp, cài package ứng dụng mà không yêu cầu resolve lại GPU stack:

```bash
python -m pip install --no-deps -e .
```

Chưa tạo `uv.lock` vì không chạy dependency resolution. `pyproject.toml` hiện
khai báo khoảng phiên bản, chưa phải môi trường tái lập đã kiểm chứng. Sau khi
xác minh môi trường server, cần khóa bộ dependency thực tế; với container,
lưu thêm image digest và phiên bản driver/runtime.

### 5.3 Chạy example trên server

Khi dùng môi trường uv đã chuẩn bị:

```bash
CUDA_VISIBLE_DEVICES=0 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1 \
  uv run --no-sync python examples/basic_usage.py \
  --config configs/qwen3_5_9b.toml
```

Khi dùng Python environment trong container đã cài package, thay
`uv run --no-sync python` bằng `python`. Các biến offline giúp phát hiện file
local còn thiếu thay vì tải bổ sung khi chạy. Offline mode không tự bổ sung
package GPU hoặc tokenizer dependency còn thiếu trong image.

Ví dụ có main guard để phù hợp engine tạo worker process. Không nên bỏ main
guard khi viết entrypoint mới. Chỉ một process cha tạo object model rồi load;
không tạo sẵn engine trước khi fork các process ứng dụng khác.

## 6. Cấu hình baseline và cách mở rộng

File mẫu chọn BF16, `tensor_parallel_size=1`, context 8.192 token, output tối
đa 1.024 token, `gpu_memory_utilization=0.9`, `max_num_seqs=4`.

Một GPU 32 GB là mục tiêu baseline, chưa phải kết quả đo. Context, engine
overhead, cache, runtime và checkpoint thực tế đều ảnh hưởng bộ nhớ. Script
tải toàn bộ checkpoint Qwen3.5-9B; adapter chưa áp dụng tùy chọn loại bỏ vision
encoder hoặc quantization. Interface chỉ nhận text.

`max_num_seqs` là giới hạn sequence engine scheduling, không phải giới hạn số
phần tử được đưa vào `generate_batch()`. Batch lớn vẫn có overhead RAM và thời
gian chờ; caller nên chia batch theo workload khi phát triển pipeline.

Để thay checkpoint tương thích vLLM:

1. Download checkpoint mới vào thư mục riêng.
2. Tạo TOML mới với model path, context, dtype và template kwargs phù hợp.
3. Giữ nguyên code gọi `BaseLLM`.

Để thêm backend inference khác, viết subclass của `BaseLLM` và chuyển kết quả
backend đó về `GenerationResult`. Backend tự xử lý tokenizer/chat template,
không đẩy các object nội bộ ra API chung. Chưa tạo factory/registry vì hiện
chỉ có một backend; application có thể inject một `BaseLLM` bất kỳ.

Nhiều vai trò dùng cùng object không tạo thêm weights. Việc dùng replica,
adapter hoặc thêm model phụ trong tương lai phải đối chiếu cách ban tổ chức
tính tổng tham số 15B. Chưa dùng GPU thứ hai hoặc chứng nhận tuân thủ luật đầy đủ.

## 7. Những việc cần xác minh trên server sau này

Không viết/chạy test trong lần bàn giao này theo yêu cầu. Khi có server, cần
kiểm chứng tối thiểu: load checkpoint thật; generate/chat/batch; token counts
và finish reasons; chat template/thinking; context overflow; batch ordering;
VRAM và compatibility của CUDA/PyTorch/vLLM.

Mốc 6 giờ của private test là yêu cầu của toàn bộ solution, gồm load model và
các bước xử lý nghiệp vụ. Tầng model này chưa đủ để suy ra thời gian đó. Chưa
có tuyên bố về độ đúng SQL hay hiệu năng end-to-end.

## 8. Tài liệu tham khảo

- [Qwen3.5-9B model card](https://huggingface.co/Qwen/Qwen3.5-9B): checkpoint, template và sampling/thinking.
- [vLLM Qwen3.5-9B recipe](https://recipes.vllm.ai/Qwen/Qwen3.5-9B): hướng dẫn backend và mức phiên bản tối thiểu.
- [vLLM offline inference](https://docs.vllm.ai/en/stable/serving/offline_inference/): inference trực tiếp trong Python.
- [vLLM 0.17.0 LLM API](https://docs.vllm.ai/en/v0.17.0/api/vllm/entrypoints/llm/): chữ ký generate/chat và chat_template_kwargs.
