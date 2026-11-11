# Báo cáo: giới hạn thinking và bổ sung diagnostics cho invalid generation

Ngày: 10/11/2026. Model mục tiêu: Qwen3.5-9B.

## 1. Vấn đề và phạm vi xử lý

Hệ thống đang dùng giới hạn context 32.768 token và output 8.192 token. Khi bật thinking, reasoning và final cùng sử dụng ngân sách output. Reasoning kéo dài có thể dùng hết ngân sách trước khi model sinh JSON/SQL hoàn chỉnh, khiến parser thất bại và pipeline trả `abstain`.

Trước thay đổi, backend đã nhận `finish_reason` và số token từ vLLM nhưng generator chỉ chuyển `text` sang parser. Khi parse lỗi, thông báo cuối của parser chỉ chứa 300 ký tự đầu của phản hồi. Thông tin này chưa đủ để phân biệt lỗi inference, lỗi định dạng và generation bị giới hạn độ dài.

Hai việc đã triển khai:

1. Đặt thinking budget 4.096 token để dành phần output còn lại cho final.
2. Lưu diagnostics đầy đủ xuyên suốt từ model/generator đến log từng attempt.

Logic retry, chính sách abstain, parser fallback và định dạng submission được giữ nguyên. Không đổi model, sampling hay cơ chế chọn context.

## 2. Giới hạn thinking

### 2.1. Cấu hình

Trong [configs/qwen3_5_9b.toml](../../../../configs/qwen3_5_9b.toml):

```toml
[model]
max_model_len = 32768

[model.chat_template_kwargs]
enable_thinking = true

[generation]
max_new_tokens = 8192
thinking_token_budget = 4096
```

Đoạn trên chỉ trích các khóa liên quan; file cấu hình thực tế vẫn giữ các tham số model và sampling khác.

Ngân sách được hiểu như sau:

```text
input + thinking + final <= 32768
        thinking + final <= 8192
        thinking budget  = 4096
```

Model có thể tự kết thúc thinking sớm. Nếu reasoning chạm budget, engine ép đóng reasoning và tiếp tục generation để sinh final trong giới hạn output còn lại. Phần token chuyển tiếp cũng nằm trong output; đây không phải hai quota độc lập, mỗi quota luôn được dùng đủ 4.096 token.

### 2.2. Kiểu dữ liệu và validation

Trong [types.py](../../../../src/datamate/b0/b03/types.py), `GenerationOptions` có thêm:

```python
thinking_token_budget: int | None = None
```

Khi có giá trị, budget phải là số nguyên dương và nhỏ hơn `max_new_tokens`. Các giá trị như `0`, số âm, boolean, số thực hoặc budget bằng/lớn hơn giới hạn output bị từ chối. Cấu hình cũ không khai báo budget tiếp tục dùng mặc định `None`.

### 2.3. Backend offline vLLM

[VLLMModel](../../../../src/datamate/b0/b03/vllm_model.py) đã được bổ sung:

- Khi default options có budget, kiểm tra `SamplingParams.thinking_token_budget` và `ReasoningConfig` trước khi tạo engine.
- Khởi tạo engine với ranh giới reasoning `<think>` và `</think>`.
- Truyền budget của từng request vào `SamplingParams` cùng `max_tokens` và các tham số sampling hiện có.
- Báo lỗi rõ ràng nếu vLLM không hỗ trợ cơ chế này; không âm thầm bỏ qua budget.
- Nếu engine được load không có default budget, request bật budget về sau bị từ chối. Cần cấu hình reasoning ngay khi load engine; sau đó request có thể chọn budget khác.
- Khi budget đang bật và áp dụng chat template thất bại, trả lỗi có diagnostics thay vì thử lại template bằng cách bỏ tùy chọn đã cấu hình.

Không thêm `stop=["</think>"]`: stop sequence tại đây sẽ dừng cả generation trước phần final.

### 2.4. Đường chạy qua API

Trong [scripts/run_b0_pipeline.py](../../../../scripts/run_b0_pipeline.py), `OpenAICompatibleLLM` cũng chuyển `thinking_token_budget` và `chat_template_kwargs` vào `extra_body` của request. CLI truyền cấu hình template đã đọc từ TOML sang client.

Client nhận reasoning từ cả trường `reasoning_content` và `reasoning`, ghép với content để dùng chung parser và diagnostics. Khi server không trả usage, số token được giữ là `None`/`null`, thay vì ghi `0` gây hiểu nhầm.

Đồng thời bổ sung `load`, `generate` và `generate_batch` để lớp client đáp ứng các abstract method của `BaseLLM`. Đây là lỗi tương thích có sẵn khiến client chưa khởi tạo được; các phương thức mới chuyển tiếp sang luồng chat hiện có, còn việc load weights thuộc server.

Server vẫn phải hỗ trợ budget và cấu hình ranh giới reasoning. Việc client gửi tham số không đủ chứng minh mọi server tương thích OpenAI đều thực thi budget.

## 3. Diagnostics và luồng ghi log

### 3.1. Cấu trúc mới

`GenerationDiagnostics` được định nghĩa trong [types.py](../../../../src/datamate/b0/b03/types.py), được export qua API B0.3 và gắn tùy chọn vào cả `GenerationResult` lẫn `Text2SQLResult`. Exception có thể mang cùng diagnostics để dữ liệu không bị mất khi parse thất bại.

| Trường | Ý nghĩa |
| --- | --- |
| `raw_response` | Toàn bộ completion dùng để parse, không cắt ở 300 ký tự. Với API, đây là reasoning và content được client ghép lại, không phải toàn bộ HTTP response. |
| `input_tokens` | Số input token backend cung cấp. |
| `output_tokens` | Tổng output token backend cung cấp; không phải riêng final. |
| `finish_reason` | Lý do kết thúc generation, ví dụ `stop` hoặc `length`. |
| `thinking_enabled` | Thiết lập thinking của request nếu biết. |
| `thinking_token_budget` | Budget thinking được cấu hình/gửi đi. |
| `max_new_tokens` | Giới hạn tổng output của request. |
| `parse_success` | `true`/`false`, hoặc `null` khi chưa có kết quả để parse. |
| `failure_kind` | Nhóm lỗi generation chi tiết. |
| `error_type` | Tên lớp exception. |
| `error_message` | Thông báo lỗi. |
| `traceback` | Traceback có chuỗi nguyên nhân exception. |

Các trường không quan sát được được giữ là `null`. Không suy đoán token usage, số token thinking thực tế hoặc nguyên nhân thiếu VRAM.

### 3.2. Phân loại lỗi

[generator.py](../../../../src/datamate/b0/b03/generator.py) và helper [diagnostics.py](../../../../src/datamate/b0/b03/diagnostics.py) bổ sung ba nhóm chẩn đoán:

| `failure_kind` | Điều kiện |
| --- | --- |
| `inference_error` | Lỗi trong quá trình gọi model/backend. |
| `parse_error` | Có phản hồi nhưng parse thất bại, không có `finish_reason="length"`. |
| `parse_error_after_length_limit` | Parse thất bại và engine báo `finish_reason="length"`. |

Tên `parse_error_after_length_limit` mô tả hai quan sát đi kèm, không chứng minh mọi lỗi parse đều do reasoning dài. Có thể phần final bị cắt hoặc output vốn đã sai định dạng.

Nếu engine báo `length` nhưng parser vẫn thu được kết quả hợp lệ, generator tiếp tục đưa kết quả qua kiểm tra SQL như trước. Không tự động từ chối chỉ dựa vào `finish_reason`.

### 3.3. Nơi lưu

Diagnostics được truyền qua [pipeline.py](../../../../src/datamate/b0/pipeline.py), `SubmissionWriter` và `AuditLogger`, rồi ghi vào từng attempt dưới khóa `generation_diagnostics` tại:

- `logs/<id>_<hash>.json`: audit log riêng của từng câu hỏi.
- `detailed_logs.jsonl`: log chi tiết của lần chạy pipeline. Tên file thực tế là số nhiều `logs`.

Áp dụng cho `generate`, `repair`, `generate_batch` và `repair_batch`, gồm cả kết quả thành công lẫn lỗi generation/parse. Thông báo parser vẫn có thể chứa đoạn preview 300 ký tự; raw response đầy đủ được giữ riêng trong diagnostics.

Nếu lỗi batch kích hoạt fallback sang gọi đơn theo cơ chế có sẵn, `batch_fallback_error` lưu diagnostics của lỗi batch trên các attempt bị ảnh hưởng, kể cả khi gọi đơn sau đó thành công. Không thêm lượt fallback hay retry mới.

## 4. Ý nghĩa các mã lỗi và hành vi được giữ nguyên

`GENERATION_INVALID` vẫn là mã chung khi pipeline không lấy được generation để tiếp tục, bao gồm lỗi inference hoặc parse. Muốn xác định chi tiết cần đọc `generation_diagnostics` của attempt đó.

`RETRY_EXHAUSTED` vẫn cho biết attempt sửa cuối cùng thất bại và pipeline đã dùng hết lượt retry cho phép. Đây là trạng thái kết thúc, không phải nguyên nhân kỹ thuật gốc. Ví dụ, log của attempt 1 có thể ghi `GENERATION_INVALID` và diagnostics lỗi parse sau giới hạn độ dài, trong khi kết quả cuối là `RETRY_EXHAUSTED`.

Luồng xử lý tiếp tục như trước:

```text
Generation lỗi ngay ở attempt 0
  -> GENERATION_INVALID -> abstain, không thêm retry

Attempt 0 có kết quả nhưng SQL/kết quả bị lỗi có thể sửa
  -> repair hiện có ở attempt 1
  -> thành công: trả kết quả
  -> lỗi thuộc luồng retry hiện có: kết thúc theo quy tắc gate/pipeline
```

Định dạng `submission.jsonl` không thêm raw response, traceback hay diagnostics. Các dữ liệu chẩn đoán chỉ được ghi vào log.

## 5. Kiểm thử đã thực hiện

Bổ sung [tests/test_thinking_budget_diagnostics.py](../../../../tests/test_thinking_budget_diagnostics.py) để kiểm tra:

- Đọc cấu hình Qwen, validation budget và mặc định tương thích cấu hình cũ.
- Cấu hình ranh giới reasoning, truyền budget và tổng output đúng cho backend offline bằng engine giả.
- Giữ prompt mở `<think>` từ chat template khi chuyển sang generate.
- Báo lỗi với vLLM thiếu hỗ trợ, lỗi template khi budget bật và request bật budget trên engine chưa cấu hình.
- Giữ raw response dài hơn 300 ký tự và metadata khi parse lỗi, ở cả generate/repair, đơn/batch.
- Phân biệt lỗi parse bình thường với parse sau `length`; không loại kết quả parse được chỉ vì `length`.
- Giữ exception chain, không tự điền token usage khi inference thất bại.
- Ghi diagnostics vào cả audit JSON và `detailed_logs.jsonl`, giữ lỗi batch trước fallback.
- Giữ nguyên số lần gọi model, `GENERATION_INVALID`, `RETRY_EXHAUSTED` và định dạng submission.
- Client API gửi budget/template, nhận reasoning và xử lý usage bị thiếu.

Lệnh kiểm thử đã chạy sau khi triển khai:

```bash
.venv/bin/python -m pytest \
  tests/test_thinking_budget_diagnostics.py \
  tests/test_b03_modular_imports.py \
  tests/test_b03_text2sql.py \
  tests/test_writer.py \
  tests/test_b0_e2e_integration.py \
  tests/test_error_retry.py \
  tests/test_gate_e2e.py \
  tests/test_remediation_b0.py -q
```

Kết quả: **146 passed**. Đây là kết quả lượt kiểm thử khi triển khai, không phải benchmark inference Qwen trên GPU. Các file Python mới/liên quan cũng đã qua `py_compile`; kiểm tra whitespace của các file thay đổi thuộc công việc này không báo lỗi.

## 6. Kiểm chứng GPU và giới hạn còn lại

Đã thêm [scripts/check_thinking_budget.py](../../../../scripts/check_thinking_budget.py). Trên máy có checkpoint và inference dependencies phù hợp, chạy từ thư mục gốc repository:

```bash
python scripts/check_thinking_budget.py --budgets 32 4096
```

Script load engine một lần, chạy qua chat template thực tế với budget nhỏ rồi budget 4.096, in SQL và diagnostics. Nó trả exit code khác 0 khi gặp exception, không thấy `</think>` hoặc generation kết thúc bằng `length`.

Script kiểm tra được dấu đóng thinking và khả năng parse final, nhưng không tự đo số thinking token thực tế hoặc chứng minh đã xảy ra forced termination. Cần đối chiếu thêm output/token khi xác minh giới hạn cứng trên model thật.

Môi trường triển khai hiện chưa có vLLM/PyTorch và chưa chạy smoke test GPU. Vì vậy:

- Chưa có số liệu trước/sau về tỷ lệ `GENERATION_INVALID`, `abstain`, độ đúng hoặc latency trên tập dữ liệu thật.
- 146 kiểm thử xác nhận tích hợp, diagnostics và tương thích luồng xử lý; chưa xác nhận hành vi suy luận của checkpoint trên GPU.
- Budget 4.096 dành dung lượng còn lại cho final nhưng không bảo đảm final luôn hoàn chỉnh hoặc đúng nghiệp vụ.
- Tổng input/output vẫn phải nằm trong context 32.768 token; thay đổi này chưa thêm cơ chế rút gọn context.
- Việc cải tiến retry được để lại theo yêu cầu, chưa triển khai trong thay đổi này.
