# Giới hạn thinking 4.096 token và bổ sung log chẩn đoán

## Thay đổi cấu hình và backend

- Thêm thinking_token_budget: int | None = None vào GenerationOptions; khi có giá trị phải là số nguyên dương và nhỏ hơn max_new_tokens.
- Cấu hình Qwen giữ enable_thinking=true, max_model_len=32768, max_new_tokens=8192; thêm thinking_token_budget=4096.
- Backend offline vLLM sử dụng ReasoningConfig với ranh giới <think> / </think> và truyền budget vào SamplingParams. Khi hết ngân sách thinking, engine chuyển sang final và tiếp tục generation trong giới hạn output còn lại.
- Kiểm tra khả năng hỗ trợ của vLLM khi khởi tạo; nếu không hỗ trợ, báo lỗi rõ ràng thay vì âm thầm chạy không có budget. Cấu hình không khai báo budget giữ hành vi cũ.
- Giữ nguyên sampling hiện tại. Không thêm stop sequence tại </think>.

## Log đầy đủ nguyên nhân

- Thêm cấu trúc diagnostics dùng chung, truyền cùng kết quả sinh SQL hoặc exception khi inference/parse thất bại; các trường mới có mặc định để tương thích caller và mock hiện có.
- Mỗi attempt lưu: raw response đầy đủ, input_tokens, output_tokens, finish_reason, thinking đang bật hay tắt, budget thinking, giới hạn output, trạng thái parse và chi tiết lỗi.
- Phân biệt trong diagnostics: lỗi inference, lỗi parse và lỗi parse sau khi generation chạm giới hạn độ dài. Giữ nguyên GENERATION_INVALID và RETRY_EXHAUSTED ở kết quả pipeline.
- Với exception, lưu loại lỗi, thông báo và traceback có chuỗi nguyên nhân. Dữ liệu không nhận được từ engine được ghi là không có; không suy đoán token usage hoặc nguyên nhân thiếu VRAM.
- Ghi diagnostics vào audit log từng câu và detailed_log.jsonl, áp dụng cho generate/repair, chạy đơn và batch. Giữ thông tin lỗi batch dẫn đến fallback hiện có.
- Không chỉ dựa vào thông báo parser đang cắt raw response ở 300 ký tự; lưu raw response bằng trường riêng. Không thay đổi định dạng submission.jsonl.