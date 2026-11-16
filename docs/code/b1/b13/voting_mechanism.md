# Voting cho Planner và Execution

Triển khai ngày 2026-11-14. Voting là tính năng **opt-in**: không bật thì pipeline vẫn chạy một candidate và tối đa một retry như trước.

## 1. Luồng xử lý đã triển khai

Context và grounding được chuẩn bị một lần cho mỗi câu hỏi. Fast-path xác nhận thiếu dữ liệu vẫn trả trực tiếp qua gate, không gọi planner để voting.

Với câu hỏi cần planner:

1. Sinh `k=4` hoặc `k=8` candidate, thinking **tắt**. Dùng sampling thay vì cấu hình greedy `temperature=0` trong TOML hiện tại.
2. Execute và kiểm tra từng candidate qua gate hiện có. Nếu lỗi được phép sửa, gọi planner repair tối đa **hai lần**: attempts `0, 1, 2`.
3. Gom các đáp án cuối cùng, tính vote. Một candidate chỉ có tối đa một phiếu, dù đã chạy ba attempts.
4. Nếu có nhóm thắng đạt threshold (`>=`), dùng outcome của candidate có ID nhỏ nhất trong nhóm đó làm đại diện.
5. Nếu chưa có nhóm thắng, sinh thêm đúng **4 candidate mới**, thinking **bật**. Repair của các candidate này cũng bật thinking.
6. Vote lại trên toàn bộ **k+4 candidate**. Nếu vẫn chưa đạt threshold hoặc hòa nhóm dẫn đầu, trả `abstain`, reason code `VOTING_THRESHOLD_NOT_MET`.

Vòng hai dùng cùng input/context/grounding, không đưa kết quả vòng một vào prompt. Không có LLM judge hoặc trọng số ưu tiên cho candidate thinking.

### Phiếu được tính như thế nào?

| Trạng thái cuối của candidate | Tử số | Mẫu số |
| --- | --- | --- |
| Có đáp án được gate chấp nhận | +1 cho nhóm đáp án | +1 |
| `unanswerable` được gate xác nhận | +1 cho nhóm unanswerable chung | +1 |
| Parse lỗi, lỗi execution hết retry, hoặc gate bác bỏ | Không có phiếu | +1 |

`ratio = số phiếu của nhóm / tổng số candidate đã sinh`.

Điều kiện thắng là **`ratio >= threshold`**. Nếu nhiều nhóm cùng đạt threshold thấp, chọn nhóm có nhiều phiếu nhất; nếu hòa ở vị trí cao nhất thì chưa có winner. Phép so sánh threshold dùng Decimal để tránh sai số float ở ranh giới.

Ví dụ threshold `0.5`:

- `3 A + 1 lỗi`: A thắng, `3/4 > 0.5`.
- `2 A + 1 B + 1 lỗi`: A thắng vì `2/4 == 0.5` và dẫn đầu duy nhất.
- `2 A + 2 B`: hòa, chuyển vòng hai.
- Sau vòng hai có `4 A + 4 lỗi`: A thắng vì `4/8 == 0.5`.
- Sau vòng hai có `4 A + 4 B`: hòa, abstain.
- `3 unanswerable + 1 A`: unanswerable thắng nếu cả ba được gate xác nhận.
- Model tự nói unanswerable nhưng thiếu bằng chứng: gate trả abstain, candidate không có phiếu.

### So sánh đáp án

Khóa nhóm gồm loại đáp án và giá trị **sau gate/formatter**, không dùng SQL hoặc raw rows làm khóa. Vì vậy SQL khác nhau nhưng trả cùng đáp án được gom chung.

- Số `1` và `1.0` cùng nhóm; boolean và number khác nhóm.
- Giữ nguyên chữ hoa/thường, dấu tiếng Việt theo formatter.
- List/table giữ thứ tự; `[1,2]` và `[2,1]` khác nhóm.
- Các reason khác nhau của unanswerable không tách nhóm.
- Không fuzzy matching hoặc gộp số gần nhau ngoài làm tròn đã có trong formatter.

Candidate được lấy mẫu độc lập và **được phép trùng SQL**. Không có vòng generate bổ sung để ép đủ k SQL khác nhau. Seed cố định được tách theo vị trí trong batch ở backend; vòng hai có offset seed riêng. Đổi batch size không đảm bảo cùng bộ candidate trên model thật.

## 2. Chỉnh cấu hình ở đâu?

### CLI local: `scripts/run_pipeline.py`

```bash
.venv/bin/python scripts/run_pipeline.py \
  --split-dir data/train \
  --bundles-dir artifacts/bundles/train \
  --output-dir artifacts/runs/voting_trial \
  --config configs/qwen3_5_9b.toml \
  --voting \
  --voting-candidates 4 \
  --voting-threshold 0.5 \
  --voting-temperature 0.7 \
  --voting-top-p 0.8 \
  --voting-top-k 20
```

| Tham số CLI | Mặc định | Ý nghĩa |
| --- | --- | --- |
| `--voting` | Tắt | Bật cơ chế hai vòng |
| `--voting-candidates` | 4 | Số candidate vòng đầu, chỉ 4 hoặc 8 |
| `--voting-threshold` | 0.5 | Ngưỡng chung hai vòng, hữu hạn trong `[0,1)` |
| `--voting-temperature` | 0.7 | Sampling cả hai vòng và repair, phải > 0 |
| `--voting-top-p` | 0.8 | Sampling cả hai vòng |
| `--voting-top-k` | 20 | Sampling cả hai vòng; -1 để tắt top-k |
| `--batch-size` | 1 | Số câu hỏi mỗi chunk; mỗi câu lại có k candidate |
| `--timeout-sec` | 10 | Timeout mỗi execution |
| `--max-rows` | 10000 | Giới hạn rows mỗi execution |

Không thêm section `[voting]` vào TOML model: loader hiện vẫn chỉ nhận `[model]` và `[generation]`. Threshold và k được truyền qua CLI hoặc Python, độc lập với cấu hình model.

### Thinking và token budget: `configs/qwen3_5_9b.toml`

```toml
[model.chat_template_kwargs]
enable_thinking = true

[generation]
max_new_tokens = 8192
thinking_token_budget = 4096
```

- Khi **bật voting**, vòng một luôn override `enable_thinking=false` và bỏ thinking budget; vòng hai luôn override `enable_thinking=true`, dùng budget từ `[generation]`.
- `max_new_tokens` là tổng ngân sách output, gồm thinking và JSON/SQL. `thinking_token_budget` phải là số nguyên dương nhỏ hơn `max_new_tokens`.
- Bỏ `thinking_token_budget` khỏi TOML nếu không muốn giới hạn thinking riêng; vòng hai vẫn bật thinking, còn giới hạn tổng output vẫn áp dụng.
- `--enable-thinking` hoặc giá trị trong `[model.chat_template_kwargs]` không đổi lịch false/true của voting. Chúng điều khiển mặc định khi không có override theo request.
- Không load thêm model khi chuyển vòng; model config không bị mutate. Với vLLM offline, muốn dùng thinking budget thì engine phải được load với default budget ngay từ đầu như cơ chế hiện có.
- Sampling voting ghi đè temperature/top-p/top-k của TOML. Penalty, stop, token limit và seed vẫn kế thừa generation options.

Lịch thinking hai vòng, số candidate bổ sung `4`, và số repair `2` hiện là hành vi cố định trong `src/datamate/voting.py`, chưa có CLI để đổi. Muốn đổi thuật toán này thì sửa `VotingConfig.options()` và `run_voting()` cùng các test tương ứng.

### Gọi qua Python

```python
from datamate.pipeline import DataMatePipeline
from datamate.planner import Text2SQLGenerator, load_config
from datamate.voting import VotingConfig

model_config, generation_options = load_config("configs/qwen3_5_9b.toml")
# llm phải được khởi tạo/load theo model_config và generation_options.
pipeline = DataMatePipeline(
    generator=Text2SQLGenerator(llm),
    options=generation_options,
    voting=VotingConfig(
        enabled=True,
        initial_candidates=8,
        threshold=0.6,
        temperature=0.7,
        top_p=0.8,
        top_k=20,
    ),
)
```

Muốn đổi giá trị mặc định của thư viện: `VotingConfig` trong `src/datamate/voting.py`. Muốn đổi mặc định trên runner: cập nhật các default tương ứng ở `scripts/run_pipeline.py` và `scripts/modal_run_pipeline.py`.

### Modal và API backend

```bash
modal run scripts/modal_run_pipeline.py \
  --voting --voting-candidates 4 --voting-threshold 0.5
```

Modal entrypoint và GPU function chuyển tiếp cùng bộ tham số voting/sampling về runner. Các thay đổi được áp dụng ở runner này; không sửa `main.py`.

`OpenAICompatibleLLM` cũng truyền override thinking, budget, seed và sampling tới endpoint vLLM-compatible. Không thực hiện fallback bỏ thinking override nếu endpoint báo lỗi. Endpoint cần hỗ trợ các tham số tương ứng; chưa kiểm thử tích hợp trên endpoint thật.

## 3. Code được thay đổi

| Thành phần | Thay đổi |
| --- | --- |
| `src/datamate/voting.py` | Config, canonical result key, đếm vote, batch generation/repair, hai vòng và telemetry |
| `src/datamate/pipeline.py` | Tích hợp cùng coordinator vào `answer_question()` và `run_questions()`; truyền budget retry và candidate identity |
| `src/datamate/planner/types.py` | Thêm `GenerationOptions.enable_thinking: bool | None`; None giữ mặc định model |
| `src/datamate/planner/vllm_model.py` | Override chat template theo request, token counting cùng options, diagnostics và seed riêng từng item |
| `src/datamate/planner/generator.py` | Diagnostics phản ánh override thinking |
| `src/datamate/gate/contracts.py`, `adapters.py`, `retry.py`, `gate.py` | `GateRequest.max_retries`, mặc định 1; voting truyền 2; hỗ trợ attempt 2 qua adapter và gate |
| `src/datamate/gate/writer.py`, `audit.py` | Lưu candidate/round identity và voting summary; submission schema giữ nguyên |
| `scripts/run_pipeline.py`, `scripts/modal_run_pipeline.py` | CLI, truyền config và hỗ trợ override cho API backend |
| `tests/test_voting.py` | Unit và integration tests với execution DuckDB/gate thật, backend inference giả lập |

Batch generation được thực hiện qua API batch sẵn có, vẫn `n=1` mỗi input. Chỉ các candidate cần repair mới được đưa vào batch repair kế tiếp. Batch lỗi hoặc thiếu output sẽ fallback chạy từng item; không tính output batch bị bỏ thành phiếu. Có thể phát sinh thêm inference thực tế do fallback nhưng số candidate không đổi. Không gọi chung vLLM engine từ nhiều thread.

Các lỗi retryable như SQL syntax/schema và parse/generation errors được sửa trong ngân sách. Security, timeout và các lỗi gate đánh dấu không retryable kết thúc candidate ngay; không làm dừng những candidate khác.

## 4. Đọc log để kiểm tra voting

`submission.jsonl` vẫn chỉ có một final answer cho mỗi câu hỏi. Candidate không tự ghi submission.

`logs/<question>.json` và `detailed_logs.jsonl` có trường `voting`:

- `rounds`: round ID, thinking mode, threshold, total candidates, các nhóm phiếu/ratio/candidate IDs, candidate đại diện và next action.
- `candidates`: trạng thái cuối, reason code và số repair của từng candidate.
- `total_repairs`: tổng repair của tất cả candidate, khác với `retry_count` của outcome đại diện.
- `input_tokens`, `output_tokens`: tổng token quan sát được qua diagnostics. Nếu `tokens_complete=false`, tổng này chưa đầy đủ; không nên dùng làm tổng chi phí thực tế khi batch fallback hoặc backend không cung cấp usage.
- `llm_generation_ms`: tổng thời gian generation được phân bổ đều theo số item của từng batch.
- `evaluation_ms`: tổng thời gian execution + gate, không gồm generation.

Mỗi attempt có `candidate_id` (bắt đầu từ 0), `round_id` (1 hoặc 2), `attempt` (0, 1, 2), SQL, lỗi, execution time và generation diagnostics. Câu hỏi đi fast-path hoặc voting tắt có `voting=null`.

## 5. Kiểm thử và giới hạn

Kết quả kiểm thử: `.venv/bin/python -m pytest -q` → **456 passed, 2 skipped, 15 subtests passed**. CLI local `--help` và kiểm tra cú pháp hai runner cũng chạy thành công.

Các test mới bao phủ inclusive threshold (`>=`), mẫu số có lỗi, tie, unanswerable, canonical values, k=4/8, vòng thinking cộng dồn, hai repair cùng candidate, parse retry exhaustion, lỗi security không repair, batch fallback, lỗi từng item, parity single/batch, chat-template override, token counting, seed và retry budget gate v1/v2.

Chưa chạy Qwen thật trên GPU, Modal remote, endpoint thật hoặc benchmark accuracy/latency/token. Vì vậy chưa kết luận voting cải thiện accuracy và chưa bật mặc định. Tokenizer/endpoint vẫn cần thực sự hỗ trợ `enable_thinking`; diagnostics ghi lại chế độ đã yêu cầu, không chứng minh model tuân thủ nếu backend tự bỏ qua tham số.

Tradeoff cần đo: candidate có thể cùng sai, repair có thể làm các SQL hội tụ, và với k=8 thì bốn candidate thinking mới có thể không lật được đa số sai vòng đầu. Worst case không tính batch fallback là 24 attempts (k=4) hoặc 36 attempts (k=8).

Benchmark tiếp theo: cùng tập câu hỏi và snapshot dữ liệu, so baseline một candidate với voting k=4 và k=8; ghi accuracy, answer coverage, precision unanswerable, tỉ lệ vòng hai, tokens, latency và số execution. Chỉ cân nhắc bật mặc định sau benchmark.
