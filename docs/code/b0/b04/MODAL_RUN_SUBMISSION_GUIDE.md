# HƯỚNG DẪN CHI TIẾT: CHẠY PIPELINE TRÊN MODAL.AI & XUẤT SUBMISSION.JSONL
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm:** UIT Last Dance  
**Nhánh:** `feature/b1-4-executor_minh`  
**File thực thi:** [`scripts/modal_run_b0.py`](../../../scripts/modal_run_b0.py)

---

## 1. MỤC TIÊU
Sử dụng hạ tầng GPU serverless của **Modal.ai** để chạy toàn bộ quy trình:
1. Nạp mô hình ngôn ngữ lớn **Qwen/Qwen3.5-9B** qua **vLLM** (xử lý song song batch).
2. Tích hợp Module **B1.4 DuckDB Executor** mới (đã bổ sung Schema Hint, chống lỗi lọc chuỗi, chống lỗi `NULL`).
3. Xuất file kết quả chuẩn **`submission.jsonl`** để nộp trực tiếp lên hệ thống chấm điểm của Ban tổ chức.
4. Tự động chấm điểm đối chiếu với `answers.jsonl` (nếu chạy tập train) để xuất báo cáo điểm số PA Score.

---

## 2. QUY TRÌNH THỰC HIỆN TỪNG BƯỚC (STEP-BY-STEP)

### BƯỚC 1: GIẢI NÉN DỮ LIỆU CỦA BTC VÀO THƯ MỤC `data/`
Modal runner cần đọc danh sách câu hỏi và cấu trúc bảng của từng doanh nghiệp từ máy cục bộ để đồng bộ lên Volume.

Chạy lệnh trong PowerShell:
```powershell
cd D:\ZALO_AI_2026\uit-last-dance-aizalo26

# Giải nén tập Train và Public Test
Expand-Archive -Path "D:\ZALO_AI_2026\train.zip" -DestinationPath "D:\ZALO_AI_2026\uit-last-dance-aizalo26\data" -Force
Expand-Archive -Path "D:\ZALO_AI_2026\public_test.zip" -DestinationPath "D:\ZALO_AI_2026\uit-last-dance-aizalo26\data" -Force
```
*(Thư mục `data/train` và `data/public_test` đã được chặn bởi `.gitignore`, không lo bị push dữ liệu nặng lên Git).*

---

### BƯỚC 2: CÀI ĐẶT MODAL CLI VÀ ĐĂNG NHẬP (1 LẦN DUY NHẤT)

```powershell
# 1. Cài đặt thư viện modal
pip install modal

# 2. Đăng nhập tài khoản Modal.ai
modal setup
```
*Lệnh `modal setup` sẽ tự động mở trình duyệt web. Bạn chỉ cần nhấn nút **Authorize** để xác nhận liên kết tài khoản Modal của bạn với máy tính.*

---

### BƯỚC 3: CHỌN GPU PHÙ HỢP VỚI NGÂN SÁCH

Model Qwen3.5-9B cần GPU có tối thiểu **24GB VRAM**:
* **Lựa chọn 1 (Khuyên dùng khi chạy test nhỏ / Tiết kiệm nhất):**  
  `Nvidia L4` ($0.80 / h) hoặc `Nvidia A10G` ($1.10 / h).
* **Lựa chọn 2 (Khuyên dùng khi chạy Full 1,000 câu / Tốc độ nhanh nhất):**  
  `Nvidia A100` ($2.10 / h) — băng thông HBM2 cực nhanh, chạy 1,000 câu chỉ mất ~30-35 phút (chi phí khoảng $1.20).

Thiết lập trong PowerShell:
```powershell
# Chọn A100 (mặc định) hoặc A10G / L4:
$env:MODAL_GPU="A100"
# hoặc: $env:MODAL_GPU="A10G"
```

---

### BƯỚC 4: CHẠY KIỂM THỬ THỬ NGHIỆM 10 CÂU (SMOKE TEST)
Trước khi chạy hàng nghìn câu, hãy chạy 10 câu đầu để kiểm tra toàn bộ luồng kết nối và cấu trúc dữ liệu:

```powershell
cd D:\ZALO_AI_2026\uit-last-dance-aizalo26
$env:PYTHONIOENCODING="utf-8"

modal run scripts/modal_run_b0.py --split train --limit 10 --enable-thinking
```

**Quan sát quá trình:**
* Bạn xem log chạy từng câu ngay trên cửa sổ terminal hoặc mở `https://modal.com/apps` để xem đồ thị GPU.
* Lần chạy đầu tiên, Modal sẽ tải weights model vào Volume (`datamate-b0-volume`). Các lần chạy tiếp theo sẽ nạp ngay lập tức.
* Thời gian: ~1 - 2 phút. Chi phí: ~$0.04 (chưa tới 1,000 VNĐ).

---

### BƯỚC 5: CHẠY TOÀN BỘ TẬP DỮ LIỆU ĐỂ LẤY FILE NỘP BÀI

#### Trường hợp A: Chạy Full 1,000 câu của tập `public_test` (Lấy file nộp bảng xếp hạng)
```powershell
$env:MODAL_GPU="A100"
modal run scripts/modal_run_b0.py --split public_test --local-output-dir artifacts/runs/public_test_submission
```
*Thời gian dự kiến:* ~30 - 40 phút.  
*Chi phí ước tính:* ~$1.20 - $1.40.

#### Trường hợp B: Chạy Full 3,000 câu của tập `train` (Để đánh giá tổng thể độ chính xác)
```powershell
$env:MODAL_GPU="A100"
modal run scripts/modal_run_b0.py --split train --local-output-dir artifacts/runs/train_full_eval
```

---

## 3. CÁC FILE KẾT QUẢ TẢI VỀ MÁY CỦA BẠN

Sau khi chạy xong, kết quả tự động tải về thư mục máy bạn (ví dụ `artifacts/runs/public_test_submission/`):

1. **`submission.jsonl`** $\rightarrow$ **File chính để nộp lên web thi.**  
   Định dạng đúng chuẩn BTC:
   ```json
   {"id": "q_001883280e83", "type": "number", "answer": 15000000}
   {"id": "q_00195e1e4049", "type": "date", "answer": "2026-05-20"}
   ```
2. **`detailed_logs.jsonl`** $\rightarrow$ File log phân tích chi tiết:
   - Toàn bộ khối suy luận `<think>` của LLM.
   - Câu lệnh SQL sinh ra.
   - Trạng thái thực thi của B1.4 DuckDB (có bị lỗi không, có kích hoạt One Bounded Retry kèm Schema Hint không).
3. **`eval_report.json`** (khi chạy tập train) $\rightarrow$ Điểm số chi tiết:
   - Số câu Đúng (+1)
   - Số câu Sai (-1)
   - Số câu Bỏ qua / Abstain (0)
   - **Điểm PA Score cuối cùng**

