# Giải Thích Mã Nguồn: `audit.py`
**Đường dẫn file:** `src/datamate/b05/audit.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `audit.py` chứa class **`AuditLogger`** — hệ thống ghi vết kiểm toán chi tiết theo từng câu hỏi (Per-question Audit Logging) ra các tệp JSON tại thư mục:
`/result/logs/<question_id>_<hash>.json`

Theo quy định của cuộc thi và yêu cầu kỹ thuật:
- Tệp `submission.jsonl` chỉ được chứa kết quả tinh gọn tối thiểu (`id`, `type`, `answer`). Tuyệt đối không được nhồi nhét log, lý do debug, câu lệnh SQL vào file submission vì sẽ làm sai định dạng chấm thi.
- Thay vào đó, toàn bộ "hộp đen" suy luận (câu lệnh SQL của lượt 0, lỗi gì xảy ra, câu lệnh SQL sửa lại ở lượt 1, thời gian thực thi, các cảnh báo) phải được lưu vào thư mục logs riêng biệt để phục vụ việc phúc khảo, kiểm chứng tính tái lập (Reproducibility), và phân tích cải tiến mô hình.

---

## 2. Chi Tiết Lớp `AuditLogger`

### 2.1. Khởi tạo `__init__(logs_dir: Path)`
* Tạo thư mục log nếu chưa tồn tại.
* Khởi tạo bộ nhớ tạm `_history: Dict[str, List[Dict[str, Any]]]`: Lưu vết các lần thử (`attempts`) của từng câu hỏi theo mã `question_id`.

---

### 2.2. Phương thức `_safe_filename(question_id: str) -> str`
```python
slug = re.sub(r"[^a-zA-Z0-9_-]", "_", question_id)
q_hash = hashlib.sha256(question_id.encode("utf-8")).hexdigest()[:8]
return f"{slug}_{q_hash}.json"
```
* **Mục đích**: Tạo tên file an toàn tuyệt đối.
* **Tại sao code như vậy?**
  * Trong tập dữ liệu thực tế, `question_id` có thể chứa ký tự lạ, dấu gạch chéo `/`, hoặc dấu chấm `.` (ví dụ: `q/test..1`). Nếu dùng trực tiếp làm tên file, hệ điều hành sẽ hiểu nhầm là đường dẫn thư mục và gây ra lỗi **Path Traversal Vulnerability**.
  * Thay thế ký tự lạ bằng gạch dưới `_` kết hợp với **8 ký tự băm SHA-256** đảm bảo:
    1. Tên file hợp lệ 100% trên cả Linux, Windows, macOS.
    2. Triệt tiêu 100% nguy cơ trùng tên file (Hash collision-free).

---

### 2.3. Phương thức `record_attempt()`
* Ghi nhận mỗi lần SQL được chạy:
  * Lượt thử: `attempt` (0 hoặc 1).
  * Câu SQL thực thi: `sql`.
  * Trạng thái thực thi: `execution_status`.
  * Mã lỗi (nếu có): `error_code`.
  * Thời gian chạy: `execution_ms`.
  * Số dòng trả về: `result_row_count`.
* Dữ liệu được nối vào mảng `_history[question_id]` mà **không bao giờ ghi đè lịch sử cũ**.

---

### 2.4. Phương thức `write_log()`
* Xuất tệp JSON hoàn chỉnh chứa toàn bộ thông tin kiểm toán:
  * `id`, `business_id`, `contract_version`.
  * `final_decision`: Quyết định cuối cùng (`answer`, `unanswerable`, `abstain`).
  * `reason_code`: Mã lý do chuẩn hóa (ví dụ `VALID_RESULT_AFTER_RETRY`, `RETRY_EXHAUSTED`).
  * `final_answer`: Bản sao kết quả nộp bài.
  * `attempts`: Mảng chứa lịch sử chi tiết của cả 2 lần chạy.
  * `warnings`: Các cảnh báo như join fanout hay row count mismatch.
  * `total_elapsed_ms`: Tổng thời gian xử lý toàn bộ câu hỏi.
  * `model_version`, `prompt_version`: Phiên bản mô hình và prompt sử dụng.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Bảo toàn lịch sử 2 lượt thử (Immutable Attempts)**:
   * Nhiều hệ thống log thông thường mắc lỗi: khi câu hỏi retry ở lượt 1, file log bị ghi đè lên và làm mất dấu câu SQL bị lỗi ở lượt 0. `AuditLogger` lưu mảng `attempts: [attempt_0, attempt_1]` giúp lập trình viên mở file log lên là thấy ngay: *"À, lượt đầu model viết `COUNT(order_code)` bị lỗi cột không tồn tại, lượt sau model đã sửa thành `COUNT(*)` thành công!"*.
2. **Không log dữ liệu nhạy cảm hoặc quá lớn**:
   * Chỉ log `result_row_count` và các cảnh báo, không dump toàn bộ 100,000 dòng dữ liệu bảng vào file log JSON để tránh làm tràn bộ nhớ ổ cứng của server GPU.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **Được quản lý bên trong `writer.py`**: Khi `writer.write_final()` được kích hoạt, nó tự động gọi `audit_logger.write_log()`.
* **Công cụ phân tích lỗi Local CV**: Sau khi chạy xong 1 tập benchmark, team có thể viết script quét thư mục `/result/logs/` để vẽ biểu đồ: có bao nhiêu câu bị lỗi syntax, có bao nhiêu câu sửa thành công sau retry, model nào chạy nhanh nhất.

---

## 5. Nếu Không Có File Này Thì Sao?

* Toàn bộ quá trình chạy sẽ trở thành một "hộp đen". Nếu kết quả nộp bài bị điểm thấp, cả nhóm sẽ hoàn toàn không biết lỗi xảy ra ở khâu nào (do LLM viết SQL sai, do DuckDB lỗi timeout, hay do Gate từ chối) và không thể cải tiến mô hình cho các vòng sau.

