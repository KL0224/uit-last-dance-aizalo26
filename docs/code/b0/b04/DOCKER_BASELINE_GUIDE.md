# HƯỚNG DẪN CHI TIẾT: ĐÓNG GÓI & KIỂM THỬ DOCKER BASELINE CHO VÒNG NGHIỆM THU
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm:** UIT Last Dance  
**Nhánh:** `feature/b1-4-executor_minh`  
**File cấu hình:** [`Dockerfile`](../../../Dockerfile), [`entrypoint.sh`](../../../entrypoint.sh)

---

## 1. MỤC TIÊU & TIÊU CHUẨN CỦA BAN TỔ CHỨC (BTC)

Ở vòng nghiệm thu kỹ thuật hoặc vòng chung kết, BTC Zalo AI Challenge yêu cầu nộp **Docker Image hoàn chỉnh** để chạy kiểm tra độc lập trên hệ thống máy chủ của BTC.

### Quy định chấm thi ngặt nghèo của BTC:
1. **Ngắt kết nối mạng hoàn toàn (`--network none`):** Container cấm tuyệt đối việc gọi API ra ngoài Internet hoặc tải thêm model/dữ liệu lúc chạy.
2. **Thư mục đầu vào chỉ đọc (`/data/input:ro`):** Thư mục chứa dữ liệu bài thi bị khóa quyền ghi. Nếu code cố ghi file log hoặc file tạm vào thư mục này sẽ bị lỗi `PermissionDenied` hoặc `IOException`.
3. **Thư mục đầu ra có quyền ghi (`/data/output:rw`):** Container phải tự động chạy toàn bộ pipeline và xuất đúng file **`submission.jsonl`** vào thư mục này.
4. **Giới hạn thời gian và tài nguyên:** Phải chạy trong thời gian quy định (tránh treo máy, loop vô tận).

---

## 2. KIẾN TRÚC DOCKERFILE ĐÃ CHUẨN HÓA

Nhóm đã cấu hình sẵn trong repository:
* [`Dockerfile`](../../../Dockerfile): Base PyTorch CUDA, cài đặt sẵn `duckdb==1.1.3`, `sqlglot==25.29.0`, `pydantic`, `pandas`, `pyarrow`, `vllm`.
* **Cấu hình Sandbox DuckDB B1.4:**
  - Tự động tạo sẵn thư mục: `RUN mkdir -p /tmp/duckdb_spill && chmod -R 777 /tmp/duckdb_spill`
  - Biến môi trường: `B04_DUCKDB_TEMP_DIR="/tmp/duckdb_spill"`, `B04_DUCKDB_MAX_MEMORY="4GB"`, `B04_DUCKDB_THREADS="4"`
  - Biến môi trường Offline: `HF_HUB_OFFLINE=1`, `TRANSFORMERS_OFFLINE=1`
* [`entrypoint.sh`](../../../entrypoint.sh): Tiếp nhận tham số `--input_dir` và `--output_dir`, tự động điều phối chạy `run_b0_pipeline.py`.

---

## 3. QUY TRÌNH THỰC HIỆN TỪNG BƯỚC (STEP-BY-STEP)

### BƯỚC 1: KHỞI ĐỘNG DOCKER DESKTOP
Trên Windows, mở ứng dụng **Docker Desktop** và đảm bảo trạng thái ở góc dưới bên trái báo màu xanh lá cây (**Engine running**).

Kiểm tra bằng lệnh:
```powershell
docker info
```

---

### BƯỚC 2: BUILD DOCKER IMAGE
Mở PowerShell tại thư mục repository:
```powershell
cd D:\ZALO_AI_2026\uit-last-dance-aizalo26

# Build Docker image với tên datamate_b0:v1.0
docker build -t datamate_b0:v1.0 .
```
*(Quá trình build sẽ tải base image và cài đặt đầy đủ các thư viện cần thiết).*

---

### BƯỚC 3: CHẠY KIỂM THỬ GIẢ LẬP MÔI TRƯỜNG CHẤM THI CỦA BTC

Để chắc chắn container không bị lỗi khi nộp bài cho BTC, chạy lệnh kiểm thử với đúng 2 cờ `--network none` và `:ro`:

```powershell
# 1. Tạo thư mục output kiểm thử trên máy
New-Item -ItemType Directory -Force -Path "D:\ZALO_AI_2026\test_docker_out"

# 2. Chạy container với thư mục input chỉ đọc và ngắt mạng hoàn toàn
docker run --rm `
    --network none `
    -v "D:/ZALO_AI_2026/uit-last-dance-aizalo26/data/examples:/data/input:ro" `
    -v "D:/ZALO_AI_2026/test_docker_out:/data/output:rw" `
    datamate_b0:v1.0 `
    --input_dir /data/input --output_dir /data/output
```

**Tiêu chí nghiệm thu (Đạt chuẩn BTC):**
1. Container không bị dừng đột ngột (crash).
2. Không bị lỗi `IOException: Read-only file system` khi DuckDB cần xả bộ nhớ ra đĩa (nhờ thư mục spill `/tmp/duckdb_spill` trong B1.4).
3. Kiểm tra trong `D:\ZALO_AI_2026\test_docker_out\` xuất hiện file `submission.jsonl` hợp lệ.

---

### BƯỚC 4: XUẤT FILE NÉN `.tar.gz` ĐỂ NỘP CHO BAN TỔ CHỨC

Khi BTC mở cổng nộp Docker Image (thường qua link Google Drive hoặc upload file nén):
```powershell
# Xuất image thành file nén .tar.gz
docker save datamate_b0:v1.0 | gzip > D:\ZALO_AI_2026\uit_last_dance_datamate_b0_v1.0.tar.gz
```
File `uit_last_dance_datamate_b0_v1.0.tar.gz` này là gói nộp bài hoàn chỉnh, độc lập và có thể chạy trên bất kỳ máy chủ Linux nào có cài Docker.

