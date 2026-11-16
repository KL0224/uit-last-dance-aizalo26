# neo_backend.py

Source: [neo_backend.py](../../../../src/datamate/grounding/neo_backend.py).

`QwenStructuredBackend` sở hữu đúng một VLLMModel Qwen2.5-3B, dùng lại giữa các request. Constructor probe API StructuredOutputsParams trước khi load weights; backend không tương thích là lỗi startup, không tự fallback text decoding.

`chat(system,user,schema)` dùng `GenerationOptions.json_schema`. VLLMModel._sampling_params chuyển thành `SamplingParams(structured_outputs=StructuredOutputsParams(json=schema))`. API theo [vLLM offline structured outputs](https://docs.vllm.ai/en/stable/features/structured_outputs/#offline-inference). Không đưa guided_json API cũ vào đường chạy.

JSON schema theo business/request được truyền cho sampler để giới hạn field/enum/ID refs/list bounds. Hết output token vẫn có thể truncate; engine bắt finish_reason=length trước parse. Schema đúng không chứng minh ngày được hiểu đúng hay nguồn doanh thu đúng.

`count_tokens` dùng đúng model chat template; lỗi đếm token là lỗi thật, không fallback ước lượng ký tự. last_generation lưu input/output tokens, finish_reason và max_new_tokens. Khi debug, NeoGroundingEngine lưu prompt, raw_response, decoding_schema và reference_map; mặc định không lưu các phần này.

GenerationOptions.json_schema mặc định None nên Planner và các caller legacy giữ sampling cũ. Không thêm model instance thứ hai. Không cài/import vLLM khi chỉ import module hoặc chạy kiểm thử CPU.

Kiểm thử CPU dùng fake vLLM API/model để xác nhận schema thực sự vào sampler, model load đúng một lần và metadata trả về; chưa compile grammar hay chạy model thật trên GPU trong phiên sửa này.
