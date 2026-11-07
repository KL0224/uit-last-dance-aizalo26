# HƯỚNG DẪN THAO TÁC CHI TIẾT: CHẠY SO SÁNH, DOCKER & MODAL.AI
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Tài liệu dành cho:** Pair-programming / Nhà phát triển thực hành cục bộ  
**Vị trí:** `docs/code/b0/b04/USER_TESTING_GUIDE.md`

---

## 1. THÔNG TIN QUAN TRỌNG VỀ DỮ LIỆU (CÂU HỎI VỀ UPLOAD DATA)

> **CÂU HỎI:** *"Có cần upload data vào để xử lý không?"*  
> **TRẢ LỜI:** **KHÔNG CẦN UPLOAD THÊM DỮ LIỆU TỪ BÊN NGOÀI.**  
> Hiện tại, trong thư mục gốc `D:\ZALO_AI_2026\`, bạn **đã có sẵn 2 tệp zip dữ liệu chuẩn của cuộc thi**:
> 1. `train.zip` (~128 MB)
> 2. `public_test.zip` (~64 MB)
>
> Khi cần chạy thử trên dữ liệu thật, bạn chỉ cần giải nén 2 file này vào thư mục `uit-last-dance-aizalo26/data/` (chi tiết ở mục 5 bên dưới). Bộ mã nguồn và test suite đã được thiết kế sẵn Mock Data để bạn có thể chạy kiểm thử độc lập mà không cần chờ nạp dữ liệu nặng.

---

## 2. BƯỚC 1: CHẠY BENCHMARK SO SÁNH ĐỐI ĐẦU B0.4 TRƯỚC VÀ SAU CẢI TIẾN

File thực thi: [`scripts/benchmark_b04_comparison.py`](../../../scripts/benchmark_b04_comparison.py)

### Cách chạy:
Mở PowerShell tại thư mục repository:
```powershell
cd D:\ZALO_AI_2026\uit-last-dance-aizalo26
$env:PYTHONIOENCODING="utf-8"
python scripts/benchmark_b04_comparison.py
```

### Kết quả bạn sẽ nhìn thấy:
Bảng kết quả đối đầu trực tiếp trên màn hình:
```text
STT  | Tiêu chí đánh giá                             | Trước cải tiến                   | Sau cải tiến (Hiện tại)            
-----------------------------------------------------------------------------------------------------------------------------
1    | Từ khóa nhạy cảm trong chuỗi (WHERE status='update') | LỖI CHẶN NHẦM: SecurityViolation | THÀNH CÔNG: is_valid=True, rows=1  
     └─> Đánh giá: Khắc phục triệt để lỗi false-positive do quét regex thô
-----------------------------------------------------------------------------------------------------------------------------
2    | Nhiều code block markdown & comment sau dấu ';' | Lấy nhầm khối 1: 'SELECT *...'   | Lấy đúng khối 2 & chạy ra 2 dòng   
     └─> Đánh giá: Trích xuất chuẩn xác khối SQL cuối cùng của LLM
-----------------------------------------------------------------------------------------------------------------------------
3    | Schema Hint khi gặp Binder/CatalogError       | Binder Error: Referenced col...  | Có đính kèm Schema Hint (Đạt)      
     └─> Đánh giá: Cung cấp ngữ cảnh schema cho One Bounded Retry sửa đúng tên cột
-----------------------------------------------------------------------------------------------------------------------------
4    | Result Validation khi SUM/AVG trả về NULL     | is_valid=True, route='yes'       | is_valid=False, route='recoverable'
     └─> Đánh giá: Chuyển sang 'recoverable' (EmptyResultWarning) cho phép LLM sửa WHERE
-----------------------------------------------------------------------------------------------------------------------------
5    | Hiệu năng truy vấn thư mục dữ liệu thô        | Lần đầu load: 538.1ms            | Lần sau qua cache: 354.4ms         
     └─> Đánh giá: Tiết kiệm I/O đĩa và CPU khi có nhiều câu hỏi cùng doanh nghiệp
```

---

## 3. BƯỚC 2: CHẠY TOÀN BỘ BỘ UNIT TEST CỦA REPO

Để đảm bảo toàn bộ hệ thống (B0.1 -> B0.5) không bị phá vỡ sau khi tinh chỉnh:
```powershell
cd D:\ZALO_AI_2026\uit-last-dance-aizalo26
$env:PYTHONIOENCODING="utf-8"
python -m pytest tests/test_b0_4_executor.py tests/test_remediation_b0.py tests/test_b0_e2e_integration.py -v
```
**Kỳ vọng:** Toàn bộ 72 tests báo `PASSED` màu xanh lá cây (`72 passed in ~60s`).

---

## 4. BƯỚC 3: BUILD VÀ TEST THỬ DOCKER CONTAINER

File cấu hình: [`Dockerfile`](../../../Dockerfile) và [`entrypoint.sh`](../../../entrypoint.sh)

### 3.1. Build Docker Image:
```bash
docker build -t datamate_b0:v1.0 .
```

### 3.2. Chạy thử container mô phỏng môi trường chấm thi của BTC:
BTC chấm thi với 2 điều kiện ngặt nghèo:
1. `--network none`: Ngắt kết nối Internet hoàn toàn.
2. Thư mục đầu vào mount `:ro` (chỉ đọc, cấm ghi).

Lệnh chạy thử với thư mục mock test:
```bash
# Tạo thư mục output tạm
mkdir -p D:/ZALO_AI_2026/test_output

# Chạy container
docker run --rm --network none \
    -v "D:/ZALO_AI_2026/uit-last-dance-aizalo26/data/examples:/data/input:ro" \
    -v "D:/ZALO_AI_2026/test_output:/data/output:rw" \
    datamate_b0:v1.0
```

### 3.3. Kiểm tra kết quả:
Kiểm tra thư mục `D:/ZALO_AI_2026/test_output/`:
* Phải có file `submission.jsonl`.
* Không có lỗi `IOException` do DuckDB ghi file tạm (vì đã có `/tmp/duckdb_spill`).

---

## 5. BƯỚC 4: GIẢI NÉN VÀ SỬ DỤNG DỮ LIỆU THẬT (TRAIN / PUBLIC_TEST)

Khi bạn muốn chạy kiểm thử trên toàn bộ câu hỏi thật của ban tổ chức:

### 5.1. Giải nén trong PowerShell:
```powershell
# Tạo thư mục đích
New-Item -ItemType Directory -Force -Path "D:\ZALO_AI_2026\uit-last-dance-aizalo26\data\train"
New-Item -ItemType Directory -Force -Path "D:\ZALO_AI_2026\uit-last-dance-aizalo26\data\public_test"

# Giải nén train.zip và public_test.zip
Expand-Archive -Path "D:\ZALO_AI_2026\train.zip" -DestinationPath "D:\ZALO_AI_2026\uit-last-dance-aizalo26\data\train" -Force
Expand-Archive -Path "D:\ZALO_AI_2026\public_test.zip" -DestinationPath "D:\ZALO_AI_2026\uit-last-dance-aizalo26\data\public_test" -Force
```

> **Lưu ý quan trọng về Git:**  
> File `.gitignore` đã chặn thư mục `data/train` và `data/public_test` nên bạn yên tâm giải nén mà không lo bị push dữ liệu nặng lên GitHub.

---

## 6. BƯỚC 5: CHẠY KIỂM THỬ TRÊN NỀN TẢNG GPU MODAL.AI

File script: [`scripts/modal_run_b0.py`](../../../scripts/modal_run_b0.py)

### 6.1. Cài đặt và đăng nhập Modal (nếu chưa cài):
```bash
pip install modal
modal setup
```

### 6.2. Chạy thử 10 câu hỏi mẫu (tiết kiệm chi phí):
```bash
modal run scripts/modal_run_b0.py --split train --limit 10 --enable-thinking
```

### 6.3. Chạy thử riêng 1 doanh nghiệp (ví dụ `biz_105`):
```bash
modal run scripts/modal_run_b0.py --split train --business-id biz_105
```

### 6.4. Chạy toàn bộ tập `public_test` để lấy file nộp bài:
```bash
modal run scripts/modal_run_b0.py --split public_test --local-output-dir artifacts/runs/public_test_submission
```

Toàn bộ kết quả gồm `submission.jsonl`, `detailed_logs.jsonl` và `eval_report.json` sẽ tự động được tải về máy của bạn tại thư mục chỉ định.
