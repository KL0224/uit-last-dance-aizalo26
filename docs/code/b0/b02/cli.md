# Giải Thích Mã Nguồn: `cli.py` (B0.2)

**Đường dẫn file:** `src/datamate/b0/b02/cli.py`  
**Thuộc module:** B0.2 Context Extractor & Business Rules  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `cli.py` cung cấp giao diện dòng lệnh (Command Line Interface - CLI) để chuẩn bị và kết xuất `BusinessContext` JSON từ metadata JSON của Data Foundation và danh sách tài liệu Rulebook/README.

---

## 2. Chi Tiết Lệnh & Cách Sử Dụng

```bash
python3 -m datamate.b0.b02.cli \
  --metadata examples/foundation_metadata.json \
  --business-id example_shop \
  --document examples/README.md
```

### Các tham số:
* `--metadata`: Đường dẫn tệp JSON metadata v1.0 từ Data Foundation (bắt buộc).
* `--business-id`: Mã định danh doanh nghiệp (bắt buộc).
* `--document`: Đường dẫn tới tệp Rulebook hoặc README Markdown (có thể lặp lại nhiều lần).

---

## 3. Tại Sao Lại Code Như Vậy?

* **Ghi JSON ra stdout**: Cho phép các tiến trình khác hoặc pipeline shell pipe kết quả dễ dàng (`> context.json`).
* **Báo lỗi ra stderr**: Nếu có lỗi validation hoặc thiếu file, thông báo lỗi được ghi ra `stderr` và tiến trình thoát với exit code `1`, không làm bẩn luồng dữ liệu chuẩn `stdout`.

