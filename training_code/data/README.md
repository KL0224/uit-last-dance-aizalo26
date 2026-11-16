# SFT Training Data Packaging Note

Thư mục này chứa bản sao hoàn chỉnh của dữ liệu huấn luyện SFT `planner.v1.2` (`data/finetuning/` trong repo nguồn):

- `train_v1_2.jsonl` (`84 MB`, `2,448` mẫu chuẩn hóa `{"id", "messages": [system, user, assistant]}`, SHA-256: `4a5a45275357790c517c120ab7c6406b9f673111cd9529a620a38a91c378c6fe`)
- `manifest.json` (siêu dữ liệu kiểm định L2/L3 trên 24 doanh nghiệp tập `train`, SHA-256: `612da7875fe0b9e40d6fa78c3490966f76b35871fae6688176967526f0562365`)
- `planner_output.schema.json` (JSON Schema Draft 2020-12 cho `Plan + SQL`, SHA-256: `03baa42519748a726784dd2926a265289945325ec13af9dd81654c94f144914f`)
- `splits/{train_ids.json, val_ids.json, holdout_ids.json}` (phân tách disjoint theo `business_id`: `2,448 / 276 / 276`)

Trong kho Git, `*.jsonl` được giữ tại `data/finetuning/` (ignored bởi `.gitignore`) để tránh làm phình lịch sử Git; khi build Docker image, `Dockerfile` thực hiện `COPY data/finetuning/ /code/training_code/data/` để đóng gói đầy đủ toàn bộ tập SFT bên trong container tại `/code/training_code/data/`.
