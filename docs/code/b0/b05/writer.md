# Giải Thích Mã Nguồn: `writer.py`
**Đường dẫn file:** `src/datamate/b05/writer.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `writer.py` chứa class **`SubmissionWriter`** — đơn vị duy nhất trong toàn bộ hệ thống được cấp quyền ghi dữ liệu vào tệp nộp bài chính thức:
`/result/submission.jsonl`

Trong môi trường thi đấu thực tế trên Docker của Ban tổ chức:
- Giới hạn thời gian chạy toàn bộ tập kiểm thử ẩn là **6 giờ**.
- Nếu chương trình bị ngắt đột ngột (out of memory, timeout, crash hệ thống) mà code chỉ đợi chạy xong hết mới ghi file một lần, toàn bộ bài thi sẽ bị mất trắng.
- Nếu ghi trùng lặp một `question_id` nhiều lần, file submission sẽ bị đánh lỗi vi phạm quy chế.

`SubmissionWriter` được thiết kế để giải quyết triệt để các rủi ro trên.

---

## 2. Chi Tiết Lớp `SubmissionWriter`

### 2.1. Khởi tạo `__init__(result_dir: Path | str = "/result")`
* Thiết lập đường dẫn thư mục xuất kết quả (mặc định `/result` theo quy định đề thi, hoặc cho phép inject thư mục tạm `/tmp` khi test).
* Khởi tạo đối tượng `AuditLogger` để ghi log chi tiết vào `/result/logs/`.
* Quản lý tập hợp `seen_ids: Set[str]`: Lưu danh sách các mã câu hỏi đã hoàn tất.
* Gọi hàm `_load_existing_ids()` để hỗ trợ tính năng **chạy tiếp (Resume Capability)**.

---

### 2.2. Phương thức `_load_existing_ids()`
* Nếu tệp `submission.jsonl` đã tồn tại từ lần chạy trước (ví dụ máy chủ GPU bị khởi động lại và pipeline chạy tiếp):
  * Đọc từng dòng, trích xuất `"id"` và nạp vào `seen_ids`.
  * Nhờ đó, pipeline có thể bỏ qua hoặc không bao giờ ghi đè lên các câu hỏi đã hoàn thành trước đó.

---

### 2.3. Phương thức `record_attempt()`
* Nhận thông tin thực thi của từng lượt thử (`attempt 0`, `attempt 1`), câu lệnh SQL, mã lỗi và thời gian thực thi để nạp vào bộ nhớ của `AuditLogger`.
* Giúp lưu lại toàn bộ tiến trình lịch sử trước khi đưa ra quyết định cuối cùng.

---

### 2.4. Phương thức `write_final(outcome, trace_meta)`
Hàm cốt lõi ghi kết quả nộp bài:

```python
# 1. Chặn tuyệt đối hành động RETRY
if outcome.action != GateAction.FINAL:
    return

# 2. Khử trùng lặp (De-duplication)
if q_id not in self.seen_ids:
    submission_dict = outcome.final_answer.to_submission_dict()
    line_str = json.dumps(submission_dict, ensure_ascii=False, allow_nan=False)

    with open(self.submission_path, "a", encoding="utf-8") as f:
        f.write(line_str + "\n")
        f.flush()  # Ép ghi dữ liệu từ bộ đệm RAM xuống đĩa cứng ngay lập tức!

    self.seen_ids.add(q_id)
```

* **Quy tắc JSON Strict**:
  * `ensure_ascii=False`: Xuất trực tiếp ký tự tiếng Việt Unicode có dấu (ví dụ `"Cà phê sữa"`), không biến thành chuỗi mã hóa ASCII xấu xí `\u0043\u00e0...`.
  * `allow_nan=False`: Nghiêm cấm xuất giá trị `NaN` hoặc `Infinity` trong JSON (vì chuẩn JSON quốc tế không hỗ trợ `NaN`).
* **Gọi `AuditLogger.write_log()`**: Luôn luôn ghi bản log kiểm toán chi tiết vào file riêng trong thư mục `/result/logs/`.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Lệnh `f.flush()` cứu mạng bài thi**:
   * Hệ điều hành Linux thường gom dữ liệu vào bộ đệm RAM (buffer) rồi mới ghi xuống ổ cứng. Nếu máy chủ bị tắt ngang, dữ liệu chưa kịp ghi sẽ mất. Gọi `.flush()` sau mỗi câu hỏi đảm bảo hễ xong câu nào là câu đó đã an toàn nằm trên đĩa cứng.
2. **Nguyên tắc "Single Writer" (Một người ghi duy nhất)**:
   * Nếu để nhiều module hoặc nhiều luồng worker tự do mở tệp `submission.jsonl` và ghi, các dòng JSON có thể bị chèn đè lên nhau, làm hỏng định dạng file. Gom việc ghi về duy nhất `SubmissionWriter` đảm bảo file luôn hợp lệ.
3. **Chống trùng ID (Idempotency)**:
   * Dù một câu hỏi có trải qua 2 lần thử (attempt 0 bị lỗi, attempt 1 thành công), thì trong file `submission.jsonl` **chỉ có duy nhất 1 dòng kết quả của attempt 1**.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **Điểm đích cuối cùng của Pipeline**: Được gọi bởi `cli.py` hoặc file điều phối chính sau khi nhận được `GateOutcome` từ `gate.py`.
* **Phối hợp với `audit.py`**: Tự động chuyển thông tin sang `AuditLogger` để lưu giữ vết kiểm toán đồng thời.

---

## 5. Nếu Không Có File Này Thì Sao?

* Dữ liệu kết quả sẽ không được lưu xuống đĩa một cách an toàn. File submission có nguy cơ bị lỗi format JSON, bị trùng lặp ID, hoặc bị mất trắng khi container của BTC gặp sự cố ngắt giữa chừng.

