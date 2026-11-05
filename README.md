# ZAIC 2026 — Local LLM layer

Interface Python dùng chung cho model local, backend đầu tiên là offline vLLM.
Checkpoint mẫu: `Qwen/Qwen3.5-9B`. Model chỉ được load vào GPU khi gọi `load()`.

- Cấu hình: [configs/qwen3_5_9b.toml](configs/qwen3_5_9b.toml)
- Tải weights: [scripts/download_model.py](scripts/download_model.py)
- Ví dụ generate/chat/batch: [examples/basic_usage.py](examples/basic_usage.py)
- Hướng dẫn và báo cáo kỹ thuật: [docs/model_layer_report.md](docs/model_layer_report.md)

Chưa chạy cài đặt, tải weights, inference hoặc test. Xem báo cáo trước khi
chủ động chạy các lệnh trên server GPU.
