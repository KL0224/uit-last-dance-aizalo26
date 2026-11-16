# Data Generation & Verification Pipeline (`planner.v1.2`)

Bộ dữ liệu huấn luyện `train_v1_2.jsonl` (`2,448` mẫu, `25,130,728` input tokens trên tokenizer `Qwen/Qwen3.5-9B`) được xây dựng **hoàn toàn từ tập `train` chính thức của BTC** (24 doanh nghiệp trong `train_ids.json`), tách biệt tuyệt đối theo `business_id` với tập `val` (`276` câu) và `holdout` (`276` câu). Tuyệt đối không sử dụng dữ liệu `public_test` hay `private_test`.

## Thành phần đóng gói tại đây
- [`prompt_v1_2.py`](prompt_v1_2.py): Snapshot mã nguồn dựng system prompt (`planner.v1.2-sys.1`, SHA-256 `5048a2c2d3ed5f102d163a7dd92f6a6a505436658a06cd0786a9bcaf9470a759`) và input payload (`planner.v1.2-input.1`).
- [`manifest_v1_2.json`](manifest_v1_2.json): Thống kê kiểm định chi tiết (`verified_l3 = 2,448 / 2,448`, phân bổ theo doanh nghiệp, loại đáp án và SHA-256 từng artifact).

## Quy trình lọc & kiểm định chất lượng
1. Sinh trace `Plan + DuckDB SQL` có cấu trúc cho từng câu hỏi hợp lệ thuộc 24 doanh nghiệp tập train (có hỗ trợ teacher model review / model-assisted synthesis từ context gốc của tập train).
2. **Level-2 Schema Validation**: Xác thực JSON output tuân thủ 100% [`planner_output.schema.json`](../configs/planner_output.schema.json) (`2,448 / 2,448` mẫu đạt, 0 lỗi).
3. **Level-3 Execution Verification**: Thực thi từng câu DuckDB SQL trên dữ liệu doanh nghiệp tương ứng của tập train và đối chiếu kết quả đáp án (`verified_l3 = 2,448 / 2,448`).
4. Định dạng chat template chuẩn non-thinking (`enable_thinking=False`) cho `train_datamate.py` với loss masking toàn bộ prompt + padding (`-100`).
