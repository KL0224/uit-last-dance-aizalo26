# Modal smoke test: 3 câu so sánh với simulated grounding

Setup chọn nguyên văn ba câu trong `synthetic_data/grounding_simulated_public_test_50/questions.jsonl`:

| ID | Business | Nội dung kiểm tra |
|---|---|---|
| q_8728cb609428 | dev_001 | Doanh thu 2/2026 so cùng kỳ năm trước |
| q_5f2d481dc5d4 | dev_003 | Doanh thu MTD đến 2025-12-09 so cùng kỳ tháng trước |
| q_621a456cc773 | dev_004 | Khách có từ 2 đơn trong tháng 1/2026 |

Bộ 50 câu không có câu Tết/lịch âm. Test này giữ đúng tập yêu cầu; lịch âm cần một lượt test riêng. Baseline là contract mô phỏng bằng assistant, không phải gold answer. Không dùng baseline trong prompt, verifier hoặc chọn binding Qwen.

## Dữ liệu đã chuẩn bị

`artifacts/neo_input/` gồm `bundles.json`, `questions.jsonl`, `rulebook.md`, `calendar.csv`, ba bundle (context/manifest/DuckDB), `selection.json` và `reference_grounding.jsonl` để đối chiếu sau inference.

Có thể tái tạo bằng:

```bash
uv run python scripts/prepare_neo_smoke.py
```

Script kiểm hash source questions/grounding/rulebook/context/manifest trước khi copy, giữ nguyên bản gốc, chỉ chấp nhận chạy lại khi dữ liệu staging giống nhau. Thư mục artifacts thường bị gitignore nên khi chuyển máy phải chạy lại script.

## Chạy thử

Cần tài khoản Modal đã đăng nhập (`uv run modal setup` nếu chưa cấu hình). Chạy từ root repository.

Preflight CPU trước, không gọi GPU:

```bash
uv run modal run scripts/modal_run_neo_grounding.py --preflight
```

Inference đúng ba câu với Qwen2.5-3B-Instruct:

```bash
uv run modal run scripts/modal_run_neo_grounding.py
```

Script sinh run name theo UTC, preflight local, gọi A100, tải model từ Hugging Face nếu cache chưa có trên volume `datamate-b0-volume`, chạy grounding, commit volume và tải kết quả về local. Lần đầu có thời gian build image/tải model ngoài thời gian inference. Không chạy Planner trong smoke test này.

Muốn đặt tên thư mục dễ nhớ:

```bash
uv run modal run scripts/modal_run_neo_grounding.py \
  --run-name neo_smoke3_run01 \
  --local-output-dir artifacts/runs/neo_smoke3_run01
```

Tên run và thư mục output phải mới. Có thể dùng `--model-path /vol/models/Qwen--Qwen2.5-3B-Instruct` để chỉ cache path. Path này dành riêng cho model Qwen2.5-3B-Instruct, không dùng snapshot model khác.

## Đọc kết quả

Trong thư mục được in ra cuối lệnh:

- `results.jsonl`: ba kết quả thật từ Qwen + verifier; failed ghi cause/message.
- `comparison.md`: xem nhanh intent, temporal_plan, assessment cạnh baseline.
- `comparison.json`: cả hai contract đầy đủ ghép theo question ID để so filter, measure, grain và source.
- `run_config.json`: model và cấu hình generation.
- `preflight.json`: fingerprint/schema business.

Xem `diagnostics.calls`, `input_tokens`, `input_budget`, `schema_tables_sent`. Nếu failed trước inference hoặc JSON bị truncate, đây là lỗi smoke test cần xử lý, không phải bằng chứng câu hỏi thiếu dữ liệu. Kết quả `partial` hiện bình thường do verifier chưa chứng minh toàn bộ ngữ nghĩa.

Đối chiếu ngày kỳ vọng:

- q_8728cb609428: `[2026-02-01, 2026-03-01)` và `[2025-02-01, 2025-03-01)`.
- q_5f2d481dc5d4: `[2025-12-01, 2025-12-10)` và `[2025-11-01, 2025-11-10)`.
- q_621a456cc773: `[2026-01-01, 2026-02-01)`; đếm đơn theo từng khách, giữ điều kiện >= 2 trước khi đếm khách.

Chỉ đánh giá semantic sau khi có output hợp lệ. Không dùng exact JSON equality hoặc độ giống baseline làm accuracy.

## Kiểm tra setup

Đã chạy preflight dữ liệu local, tests preparation/comparison và hồi quy grounding. Chưa gọi Modal GPU trong bước setup này; cần chạy lệnh inference trên để có kết quả thực tế.

## Chẩn đoán lượt neo_smoke3_20261116_013030_020903

Cả ba request đã gọi Qwen (`calls=1`); chưa request nào dựng được contract:

| ID | Lỗi quan sát | Kết luận |
|---|---|---|
| q_8728cb609428 | JSON EOF tại dòng 116 | Response chưa hoàn chỉnh; nghi chạm budget 768. Run cũ không lưu finish_reason/output_tokens nên chưa khẳng định được nguyên nhân dừng. |
| q_5f2d481dc5d4 | JSON invalid number, schema_tables_sent=[] | JSON không hợp lệ. Có lỗi chắc chắn ở prompt trimming: bỏ hết schema trước khi bỏ JOIN stats. Không đủ raw response để xác định chính xác token số bị lỗi. |
| q_621a456cc773 | unknown column reference: ma_don | Cột có thật nhưng model dùng bare name. Verifier yêu cầu `so_ban_hang_86875366.ma_don`. |

Đã sửa thứ tự trimming để bỏ JOIN stats trước và giữ ít nhất một schema card. Nếu phần bắt buộc vẫn không vừa budget, fail trước inference. Prompt yêu cầu compact JSON, bỏ field không dùng, dùng exact qualified column refs. Output budget được tăng lên 2048; input 5632 + output 2048 vẫn nằm dưới context 8192. Đây là thay đổi sau smoke test, chưa có số đo GPU xác nhận chất lượng/latency mới.

Chạy lại có debug bằng run name mới:

```bash
uv run modal run scripts/modal_run_neo_grounding.py --debug-model-output
```

Diagnostics mới chứa `stage`, `elapsed_ms`, `response_chars`, `output_tokens`, `finish_reason`, `max_new_tokens`. Chỉ bật `--debug-model-output` mới lưu `raw_response`. Finish reason `length` được phân loại GROUNDING_OUTPUT_TRUNCATED trước JSON parsing. Không tự thêm tên bảng cho cột trần hoặc sửa JSON lỗi vì có thể che lỗi model.

## Chạy lại với neo-compact-v3

Đã thay prompt/raw schema bằng wire proposal có ID ngắn và ví dụ độc lập. Sampler dùng StructuredOutputsParams(json=...) theo đúng visible columns; giới hạn 8 measures/time specs. Cohort giữ hai cấp tổng hợp. Debug giờ lưu cả prompt và reference_map, decoding_schema.

```bash
uv run modal run scripts/modal_run_neo_grounding.py --debug-model-output
```

Kiểm diagnostics.prompt_version=neo-compact-v3 và constrained_decoding=true trước khi so kết quả. Mỗi lần chạy tạo tên mới; dữ liệu/baseline ba câu giữ nguyên. Chưa có kết quả GPU mới sau thay đổi này nên không coi các câu đã được giải đúng chỉ từ test CPU.

## Temporal v4: chạy lượt mới

```bash
uv run modal run scripts/modal_run_neo_grounding.py --debug-model-output
```

Kiểm diagnostics.prompt_version=neo-temporal-v4 và constrained_decoding=true. Câu so hai kỳ cần hai constraints có label primary/comparison hoặc assessment.unresolved giải thích kỳ thiếu. Xem temporal_plan.completeness_status; complete là đủ theo intent/spec khai báo, không tương đương accuracy hay semantic verified. Run name tự tạo mới, dữ liệu ba câu và baseline giữ nguyên. Chưa có kết quả GPU mới cho v4 trong lúc implement.
