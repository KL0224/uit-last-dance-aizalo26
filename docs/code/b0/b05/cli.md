# Giải Thích Mã Nguồn: `cli.py`
**Đường dẫn file:** `src/datamate/b05/cli.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `cli.py` cung cấp **Giao diện dòng lệnh độc lập (Standalone Command-Line Runner)** cho module B0.5.

Vai trò then chốt: Cho phép chạy thử nghiệm, benchmark và kiểm chứng toàn bộ quy trình của B0.5 trên tệp dữ liệu giả lập JSONL (`b05_cases.jsonl`) **ngay cả khi chưa có các module B0.1, B0.2, B0.3, B0.4** hoặc khi không có kết nối internet/máy chủ GPU.

Lệnh thực thi:
```bash
PYTHONPATH=src python3 -m datamate.b05.cli \
    --fixtures tests/fixtures/b05_cases.jsonl \
    --result-dir /tmp/b05_output
```

---

## 2. Chi Tiết Các Hàm

### 2.1. `run_pipeline(fixtures_path: Path, result_dir: Path) -> Dict[str, Any]`
Hàm điều phối luồng xử lý toàn bộ tệp fixtures:

1. **Khởi tạo bộ ghi**: `writer = SubmissionWriter(result_dir=result_dir)`.
2. **Khởi tạo bộ đếm thống kê**:
   * `total`: Tổng số câu hỏi.
   * `answer`: Số câu nộp đáp án.
   * `unanswerable`: Số câu xác nhận thiếu dữ liệu.
   * `abstain`: Số câu bỏ qua an toàn.
   * `retry_attempts`: Số lượt sửa lỗi SQL.
3. **Vòng lặp đọc từng dòng JSONL**:
   * **Bảo vệ chống crash (Resilience)**:
     ```python
     try:
         req = adapt_gate_request(raw_record)
     except Exception as c_err:
         # Gặp lỗi format hợp đồng -> Chuyển thành abstain ngay lập tức
         outcome = GateOutcome(action="FINAL", decision="abstain", reason_code="CONTRACT_ERROR", ...)
         writer.write_final(outcome)
         continue
     ```
     *Nếu 1 dòng trong file bị lỗi cú pháp, cả batch 1,000 câu vẫn tiếp tục chạy mượt mà, không bị dừng đột ngột.*
   * **Ghi nhận vết attempt 0**: `writer.record_attempt(attempt=0, ...)`.
   * **Đánh giá lượt đầu**: `outcome = evaluate_gate(req)`.
   * **Xử lý Bounded Retry mô phỏng**:
     * Nếu `outcome.action == GateAction.RETRY`:
       * Tăng biến đếm `retry_attempts`.
       * Mô phỏng lượt sửa lỗi (`attempt = 1`): Cập nhật câu lệnh SQL mới hoặc dữ liệu đã sửa, ghi nhận vết lượt 1 qua `writer.record_attempt(attempt=1, ...)`.
       * Đánh giá lại lượt 1: `outcome = evaluate_gate(req1)`.
   * **Ghi nhận kết quả cuối cùng**: `writer.write_final(outcome)`.
4. **Trả về kết quả thống kê**: Tổng số lượng, phân loại đáp án và tổng thời gian tính bằng giây.

---

### 2.2. `main()`
* Định nghĩa tham số dòng lệnh qua `argparse`:
  * `--fixtures`: Đường dẫn tới tệp JSONL chứa các ca thử nghiệm (bắt buộc).
  * `--result-dir`: Thư mục lưu kết quả nộp bài `submission.jsonl` và thư mục `logs/` (mặc định `/result`).
* In ra bảng thống kê chi tiết trên terminal sau khi chạy xong.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Tuân thủ nguyên tắc Contract-First & Tách biệt module**:
   * Trong quá trình làm việc nhóm 4 người, người làm Gate (B0.5) không cần phải ngồi đợi người làm Text-to-SQL (B0.3) viết xong code thì mới test được. `cli.py` cho phép tự kiểm thử 100% logic Gate với các kịch bản synthetic data độc lập.
2. **Đo lường thời gian thực thi (Latency Measurement)**:
   * Giới hạn bài thi của Zalo AI Challenge là 6 giờ. `cli.py` dùng `time.monotonic()` để đo chính xác thời gian chạy (khoảng ~0.14 ms / câu), khẳng định module B0.5 chạy siêu nhanh và hoàn toàn không gây tắc nghẽn hệ thống.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **Điểm nối cho các bài kiểm thử End-to-End**: Hàm `run_pipeline()` được gọi trực tiếp trong `tests/test_gate_e2e.py::test_cli_pipeline_run` để kiểm chứng toàn bộ quy trình từ đọc file, evaluate, retry đến ghi đĩa.
* **Mẫu tham khảo cho Orchestrator tổng thể**: Khi nhóm ghép nối B0.1, B0.3, B0.4 thành pipeline hoàn chỉnh, code của file `cli.py` này chính là khung mẫu chuẩn để gọi B0.5.

---

## 5. Nếu Không Có File Này Thì Sao?

* Đội thi không có công cụ dòng lệnh để test nhanh B0.5. Mỗi lần muốn thử một trường hợp lỗi mới, lập trình viên sẽ phải mở Python interactive hoặc chạy cả pipeline nặng nề, tốn rất nhiều thời gian và khó phát hiện lỗi hồi quy (regression bugs).

