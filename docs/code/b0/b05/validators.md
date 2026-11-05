# Giải Thích Mã Nguồn: `validators.py`
**Đường dẫn file:** `src/datamate/b05/validators.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `validators.py` đóng vai trò là **Thanh tra hình học và chất lượng kết quả (Execution & Shape Validator)** trong B0.5.

SQL chạy thành công trên DuckDB (`status == "success"`) **không đồng nghĩa** với việc kết quả đó đúng về mặt hình học hoặc có thể nộp được. Ví dụ:
- Câu hỏi cần một con số (ví dụ: tổng doanh thu), nhưng câu lệnh SQL do LLM sinh ra thiếu hàm `SUM()` dẫn đến việc trả về 10,000 dòng.
- Câu lệnh SQL trả về giá trị `NULL`, `NaN`, hoặc `Infinity`.
- Kết quả bị cắt ngắn (chỉ lấy 5 dòng preview thay vì toàn bộ bảng).

File `validators.py` chịu trách nhiệm phát hiện chính xác các sai lệch này trước khi đưa sang bộ phận Formatter.

---

## 2. Chi Tiết Hàm `validate_execution`

Hàm duy nhất và trọng tâm của file:
```python
def validate_execution(request: GateRequest) -> ValidationResult:
```

### Các bước kiểm tra tuần tự:

1. **Kiểm tra trạng thái thực thi (`status`)**:
   * Nếu `status == ERROR`: Trả về `ValidationResult(passed=False, error_code=EXECUTOR_FAILURE)` kèm thông điệp lỗi gốc của DuckDB.
   * Nếu `status == NOT_EXECUTED`: Báo chưa thực thi.
2. **Kiểm tra cờ dữ liệu cắt ngắn (`truncated`)**:
   * Nếu `truncated == True`: Lập tức từ chối với mã lỗi `TRUNCATED_RESULT`.
   * *Ý nghĩa*: Tuyệt đối không bao giờ nộp một danh sách hoặc bảng dữ liệu bị cắt dở dang (ví dụ đề yêu cầu danh sách khách hàng mà chỉ nộp 10 người đầu tiên).
3. **Phân nhánh kiểm tra theo 4 nhóm `AnswerType`**:
   * **Nhóm 1: Các kiểu vô hướng (Scalar Types: `number`, `percent`, `string`, `date`, `boolean`)**:
     * Kiểm tra số dòng: Bắt buộc `len(rows) == 1`.
       * Nếu `len(rows) == 0`: Báo lỗi `EMPTY_RESULT`.
       * Nếu `len(rows) > 1`: Báo lỗi `SCALAR_SHAPE_MISMATCH` (đây là lỗi có thể sửa được bằng cách thêm `LIMIT 1` hoặc hàm `SUM/AVG`).
     * Kiểm tra số cột: Bắt buộc dòng đầu tiên chỉ có đúng 1 phần tử `len(rows[0]) == 1`.
     * Kiểm tra giá trị ô (`candidate`):
       * Bắt lỗi `NULL`: Không bao giờ tự ý chuyển `NULL` thành số 0.
       * Bắt lỗi `NaN`/`Inf`: Chặn các giá trị chia cho 0 hoặc lỗi số thực.
       * Riêng `boolean`: Kiểm tra bắt buộc phải là kiểu `bool` thực sự.
   * **Nhóm 2: Kiểu danh sách (`list`)**:
     * Kiểm tra mỗi dòng trong `rows` phải là 1 cột duy nhất.
     * Trích xuất danh sách: `candidate = [row[0] for row in rows]`.
     * Nếu danh sách rỗng `[]`: Chỉ cho phép nếu có cờ `empty_set_policy == "allowed"`, ngược lại báo lỗi `EMPTY_RESULT`.
   * **Nhóm 3: Kiểu bảng (`table`)**:
     * Kiểm tra danh sách cột `columns` không được rỗng.
     * Duyệt từng dòng: Độ rộng của dòng (`len(row)`) bắt buộc phải bằng chính xác `len(columns)`. Nếu lệch -> báo lỗi `TABLE_SHAPE_ERROR`.
     * Kiểm tra từng ô trong bảng: Chặn các ô chứa `NULL`, `NaN`, `Inf`.
   * **Nhóm 4: Kiểu đặc biệt (`unanswerable`, `abstain`)**:
     * Không cần kiểm tra ma trận bảng, cho phép `candidate = None`.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Không đoán mò dữ liệu (Strict & Unforgiving)**:
   * Một sai lầm phổ biến của các đội thi AI là khi câu truy vấn scalar trả về nhiều dòng, code tự động lấy dòng đầu tiên `rows[0][0]`. Việc này cực kỳ nguy hiểm vì dòng đầu tiên đó có thể là một giá trị ngẫu nhiên không phản ánh đúng tổng thể. `validators.py` chọn giải pháp ném lỗi `SCALAR_SHAPE_MISMATCH` để B0.3 sửa câu SQL (thêm `SUM()`, `AVG()` hoặc `ORDER BY ... LIMIT 1`).
2. **`NULL` khác `0`**:
   * Trong kế toán và phân tích kinh doanh: "Doanh thu bằng 0đ" (có bán nhưng không thu được tiền) khác hoàn toàn với "Doanh thu là NULL" (không có dữ liệu hoặc không ghi nhận). Ép `NULL` thành `0` sẽ làm sai lệch đáp án bài thi.
3. **Bảo toàn cảnh báo (`warnings`)**:
   * Nếu B0.4 phát hiện rủi ro (ví dụ: join nhiều bảng gây nhân đôi dòng `join_fanout`), cảnh báo này được giữ nguyên trong `ValidationResult` để ghi vào audit log.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **Đầu vào cho `retry.py`**: Khi `passed == False`, mã lỗi `error_code` (như `SCALAR_SHAPE_MISMATCH`) là tín hiệu quyết định để bộ điều khiển retry biết đây là lỗi có thể khắc phục được và tạo ra `RepairRequest`.
* **Cung cấp `normalized_candidate` cho `formatter.py`**: Khi `passed == True`, giá trị đã được bóc tách an toàn khỏi ma trận `rows` để chuyển thẳng sang `formatter.py` làm tròn và format.

---

## 5. Nếu Không Có File Này Thì Sao?

* Formatter sẽ nhận trực tiếp ma trận `rows` 2 chiều, dẫn đến việc format bị crash khi cố ép kiểu `[[1], [2]]` sang float.
* Các câu SQL sinh lỗi hình học hoặc trả về tập rỗng preview sẽ bị nộp thẳng lên ban tổ chức, gây mất điểm hàng loạt.

