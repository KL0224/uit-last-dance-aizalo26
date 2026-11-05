# Giải Thích Mã Nguồn: `formatter.py`
**Đường dẫn file:** `src/datamate/b05/formatter.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `formatter.py` là **Bộ chuyển đổi và định dạng dữ liệu đầu ra có kiểu (Typed Output Formatter)**.

Sau khi Validator xác nhận kết quả truy vấn SQL có cấu trúc hợp lệ, Formatter nhận nhiệm vụ ép kiểu và chuẩn hóa giá trị đó sao cho khớp 100% với định dạng mà máy chấm thi tự động của Ban tổ chức Zalo AI Challenge mong đợi.

File này giải quyết những bài toán hóc búa nhất về mặt dữ liệu:
- Sai số dấu phẩy động (Floating-point precision issues).
- Quy tắc làm tròn số nửa lên (`ROUND_HALF_UP`) của kế toán.
- Đơn vị phần trăm (điểm phần trăm vs tỷ lệ thập phân).
- Chuẩn hóa chuỗi tiếng Việt Unicode NFC mà không làm mất dấu hay viết hoa/thường.
- Giữ nguyên trật tự danh sách và bảng biểu.

---

## 2. Chi Tiết Các Hàm

### 2.1. `normalize_match_key(value: str) -> str`
* **Mục đích**: Chuẩn hóa chuỗi dùng cho việc so khớp đáp án trong đánh giá Local CV.
* **Logic**: NFC ➔ chuyển chữ thường (`lower()`) ➔ thay ký tự đặc biệt thành khoảng trắng ➔ gộp khoảng trắng liên tiếp ➔ cắt tỉa 2 đầu (`strip()`).
* **Lưu ý tối quan trọng**: Hàm này **chỉ dùng nội bộ để so sánh ground-truth**, tuyệt đối không dùng để sửa chuỗi nộp bài trong `submission.jsonl`.

---

### 2.2. `_to_decimal(value: Any) -> Decimal`
* **Mục đích**: Chuyển đổi an toàn giá trị số sang `Decimal` của thư viện chuẩn Python.
* **Tại sao không dùng `float()` thông thường?**
  * Trong Python, `float(0.1) + float(0.2) = 0.30000000000000004`. Sai số dấu phẩy động này sẽ làm sai lệch kết quả làm tròn ở các chữ số cuối cùng. `Decimal` đảm bảo độ chính xác số học tuyệt đối.
* **Cơ chế phòng thủ**:
  * Kiểm tra `isinstance(value, bool)`: Trong Python, `bool` là lớp con của `int` (`isinstance(True, int) == True`). Nếu không chặn, `Decimal(True)` sẽ thành `1`. Hàm lập tức ném `FormattingError`.
  * Chặn `None`, `NaN`, `Infinity`.

---

### 2.3. `format_number(value, semantics) -> int | float`
* **Xử lý theo ngữ nghĩa `numeric_kind`**:
  * `count`: Bắt buộc là số nguyên. Nếu có phần thập phân (`125.5`), ném lỗi `FormattingError`. Output là `int`.
  * `money_vnd` & `average_money_vnd`: Làm tròn về đơn vị đồng VND bằng quy tắc nửa lên `ROUND_HALF_UP` (ví dụ `1250000.5` ➔ `1250001`). Output là `int`.
  * `average_nonmoney`: Làm tròn đúng 2 chữ số thập phân (`Decimal('0.01')`, `ROUND_HALF_UP`). Output là `float`.
  * `quantity` & `generic`: Nếu chia hết cho 1 thì trả về `int`, ngược lại làm tròn 2 chữ số thập phân và trả về `float`.

---

### 2.4. `format_percent(value, semantics) -> int | float`
* **Quy chuẩn điểm phần trăm (Percentage Points)**:
  * Trong đề thi, `-12.45` biểu thị cho `-12.45%`. Tuyệt đối không xuất chuỗi có ký tự `%` hoặc `-0.1245`.
  * Nếu `percent_unit == "fraction"`: Giá trị là tỷ lệ (ví dụ `0.125`), hàm nhân cho 100 đúng 1 lần duy nhất để ra `12.5`.
  * Làm tròn 2 chữ số thập phân bằng `ROUND_HALF_UP`.
  * **Tránh `-0.0` trong JSON**: Nếu sau khi làm tròn giá trị bằng `0.00`, hàm ép về số `0` nguyên để tránh sinh ra chuỗi `-0.0` bị máy chấm thi từ chối.

---

### 2.5. `format_string(value) -> str`
* Chuẩn hóa Unicode sang chuẩn `NFC` (chuẩn dựng sẵn tiếng Việt của VNG/Zalo).
* Cắt tỉa khoảng trắng 2 đầu (`strip()`).
* **Bảo toàn 100% chữ hoa, chữ thường và dấu tiếng Việt** (ví dụ giữ nguyên `"Cà phê sữa"`, không biến thành `"ca phe sua"`).
* Bắt lỗi nếu chuỗi rỗng `""`.

---

### 2.6. `format_date(value, semantics) -> str`
* Nếu là đối tượng `datetime.date` hoặc `datetime.datetime`: chuyển thành chuỗi ISO qua `.isoformat()`.
* Kiểm tra định dạng qua regex: `^\d{4}-\d{2}-\d{2}$` hoặc `^\d{4}-\d{2}$` (dành cho câu hỏi tháng).
* Kiểm tra tính hợp lệ trên lịch: Ngăn chặn ngày ảo (`2026-02-30`) hoặc tháng ảo (`2026-13`).

---

### 2.7. `format_boolean(value) -> bool`
* Chỉ chấp nhận kiểu `bool` chuẩn của Python (`True` hoặc `False`).
* Từ chối số nguyên `1`, `0` hoặc chuỗi `"true"`, `"false"`.

---

### 2.8. `format_list(value, semantics) -> List[Any]`
* Nhận danh sách các giá trị từ truy vấn 1 cột.
* **Bảo toàn thứ tự tuyệt đối**: Không dùng `set()` làm mất thứ tự, không gọi `sort()` làm đảo lộn ranking.
* Chuẩn hóa Unicode NFC cho từng phần tử chuỗi bên trong list.

---

### 2.9. `format_table(value, semantics) -> Dict[str, Any]`
* Kiểm tra cấu trúc: `{"columns": [...], "rows": [[...], ...]}`.
* Kiểm tra tính toàn vẹn: Không cho phép bất kỳ ô nào chứa `NULL` hoặc `NaN`.
* Giữ nguyên tên cột và thứ tự dòng từ SQL.

---

### 2.10. `format_answer(answer_type, value, semantics) -> Any`
* Hàm điều phối trung tâm: Nhận `answer_type` và gọi hàm format con tương ứng.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Tuân thủ quy chuẩn số học tài chính**:
   * Tiền tệ VND không có đơn vị xu/hào lẻ. Việc dùng `Decimal` và `ROUND_HALF_UP` đảm bảo số tiền nộp lên không bị lệch dù chỉ 1 đồng so với đáp án của ban tổ chức.
2. **Không tự ý làm sạch quá đà (Over-cleaning)**:
   * Nhiều bạn thường viết hàm `clean_text()` tự động xóa dấu tiếng Việt hoặc chuyển hết thành chữ thường (`lower()`). Điều này sẽ làm sai đáp án dạng chuỗi (ví dụ: tên riêng khách hàng `"Anh Kiệt"` bị biến thành `"anh kiet"`). `format_string()` chỉ chuẩn hóa mã Unicode NFC và giữ nguyên văn bản gốc.
3. **Phân biệt `fraction` và `percent_points`**:
   * Nếu không có cờ `percent_unit`, code không thể biết con số `0.15` là `0.15%` hay là `15%`. Việc yêu cầu siêu dữ liệu ngữ nghĩa giúp việc tính toán chính xác 100%.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **Được gọi bởi `gate.py`**: Khi Validator pass, `gate.py` chuyển giá trị ứng viên vào `format_answer()`.
* **Gắn vào `FinalAnswer`**: Giá trị trả về từ hàm này chính là giá trị nằm trong trường `"answer"` của tệp `submission.jsonl`.
* **Xử lý ngoại lệ**: Nếu ném ra `FormattingError`, `gate.py` sẽ bắt lấy và kích hoạt Bounded Retry (nếu ở attempt 0) hoặc chuyển sang `abstain`.

---

## 5. Nếu Không Có File Này Thì Sao?

* Kết quả nộp bài sẽ bị dính các lỗi kinh điển: số float bị sai số `125.000000000001`, chuỗi Unicode bị lỗi font tổ hợp, số tiền VND bị lẻ thập phân, phần trăm bị nhầm giữa 0.12 và 12%. Điều này khiến bài thi bị máy chấm đánh rớt hầu hết các câu tính toán.

