# Giải Thích Mã Nguồn: `temporal.py`

**Đường dẫn file:** [`src/datamate/grounding/temporal.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/temporal.py)  
**Thuộc module:** Component C — Question Grounding (C2 Question-level Temporal Resolver)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `temporal.py` triển khai lớp `QuestionTemporalResolver` (module con **C2**).

Trong các bài toán hỏi đáp trên dữ liệu chuỗi thời gian doanh nghiệp (Time-series Tabular QA), **sai lệch thời gian là nguyên nhân hàng đầu gây mất điểm**:
1. **Sự nhầm lẫn giữa đồng hồ hệ thống và ngày tham chiếu của câu hỏi**: Mỗi câu hỏi trong đề thi có một mốc `as_of_date` giả định khác nhau (ví dụ: `2026-08-27`). Nếu để LLM suy luận, mô hình thường có xu hướng lấy ngày hiện tại của máy tính hoặc nhầm lẫn giữa các tháng trong quá khứ/tương lai.
2. **Khái niệm "tháng này" / "quý này" tính đến ngày hiện tại**: Người dùng hỏi *"Trong tháng này doanh thu là bao nhiêu?"* với `as_of_date = 2026-08-27` thì khoảng thời gian đúng phải là từ **`2026-08-01` đến `2026-08-27` (inclusive)**, chứ không phải cả tháng 8 đến `2026-08-31` (vì các ngày sau ngày 27 là dữ liệu tương lai chưa xảy ra).
3. **Sự khác biệt ngữ nghĩa giữa các cột ngày**: Cùng một đơn hàng nhưng ngày đặt đơn (`order_date`) là ngày 25, còn ngày thu tiền mặt theo ca (`payment_date`) là ngày 27. Nếu lọc sai cột ngày, kết quả tính toán sẽ sai hoàn toàn.
4. **Các khái niệm thời gian đặc thù của Việt Nam**: Dịp Tết Âm Lịch (thay đổi theo từng năm) và các câu hỏi so sánh tăng trưởng cùng kỳ ("cùng kỳ năm ngoái", "so với tháng trước").

Module C2 giải quyết triệt để toàn bộ các vấn đề trên bằng **100% thuật toán lịch học tất định (Deterministic Calendar Algorithms)**, không phụ thuộc vào LLM.

---

## 2. Chi Tiết Các Hàm & Thuật Toán Phân Giải

### 2.1. Các Hàm Phụ Trợ Lịch Học (Calendar Helpers)

* **`_last_day_of_month(year: int, month: int) -> date`**:
  * Sử dụng `calendar.monthrange(year, month)` để lấy chính xác số ngày của tháng, xử lý an toàn tháng Hai của năm nhuận (28 hoặc 29 ngày).
* **`_quarter_bounds(year: int, quarter: int) -> tuple[date, date]`**:
  * Tính ngày đầu tiên và ngày cuối cùng của quý $Q$ ($Q \in [1, 4]$). Ví dụ Quý 3 bắt đầu từ `01/07` đến `30/09`.
* **`_shift_year_safe(d: date, years: int) -> date`**:
  * Dịch chuyển ngày theo số năm. Xử lý trường hợp biên nguy hiểm: nếu `d` là ngày `29/02` năm nhuận mà lùi 1 năm (năm không nhuận), hàm tự động chuyển về ngày `28/02` thay vì gây crash với `ValueError: day is out of range for month`.

---

### 2.2. Phương Thức `infer_date_role(...)`

```python
def infer_date_role(
    self,
    question: str,
    preferred_date_role: DateRole | None = None,
) -> DateRole:
```
* **Mục đích**: Xác định vai trò cột ngày cần áp dụng trong SQL.
* **Cơ chế**:
  * Nếu tầng trên (Engine) truyền vào `preferred_date_role` (tra cứu từ Metric Registry), hàm ưu tiên dùng ngay.
  * Nếu không, hàm tự động phân tích từ khóa câu hỏi:
    * Chứa từ khóa thu tiền (*"thực thu"*, *"thu tiền"*, *"thanh toán"*) $\rightarrow$ `DateRole.PAYMENT_DATE`.
    * Chứa từ khóa kho bãi (*"nhập kho"*, *"xuất kho"*, *"tồn kho"*) $\rightarrow$ `DateRole.STOCK_EVENT_DATE`.
    * Chứa từ khóa hạn dùng (*"hết hạn"*, *"hạn sử dụng"*) $\rightarrow$ `DateRole.EXPIRY_DATE`.
    * Mặc định thông thường $\rightarrow$ `DateRole.ORDER_DATE`.

---

### 2.3. Phương Thức `resolve(...)`

```python
def resolve(
    self,
    question: str,
    as_of_date: str,
    context: BusinessContextProtocol | None = None,
    preferred_date_role: DateRole | None = None,
) -> tuple[ResolvedTimeRange, ...]:
```

Thực hiện phân giải theo thứ tự từ trường hợp đặc thù nhất đến tổng quát:

#### 1. Tra cứu sự kiện lịch & Tết Âm Lịch:
* Nếu câu hỏi chứa từ `"tết"` và có `context`:
  * Xác định năm mục tiêu: nếu có `"năm ngoái"` $\rightarrow$ `anchor.year - 1`; nếu có số năm cụ thể (ví dụ `"tết 2025"`) $\rightarrow$ lấy đúng năm đó; mặc định là `anchor.year`.
  * So khớp với danh sách `context.get_calendar_events()` để lấy chính xác ngày bắt đầu và kết thúc của kỳ nghỉ Tết. Ví dụ Tết 2026: `2026-02-14` đến `2026-02-22`.

#### 2. Phân giải ngày cụ thể (Explicit Dates):
* Bắt định dạng `dd/mm/yyyy` hoặc `dd-mm-yyyy` (ví dụ: *"Ngày 15/08/2026..."*).
* Bắt định dạng chuẩn ISO `yyyy-mm-dd`.
* Trả về khoảng ngày đóng có `start_date == end_date`.

#### 3. Phân giải Quý hoặc Tháng cụ thể:
* Regex bắt `quý Q năm YYYY` hoặc `tháng M/YYYY`.
* **Cắt biên an toàn**: Nếu tháng/quý được hỏi chính là tháng/quý của `as_of_date`, ngày kết thúc được tự động cắt tại `as_of_date` (không vượt quá ngày hiện tại). Nếu là tháng trong quá khứ, lấy trọn vẹn đến ngày cuối tháng.

#### 4. Phân giải $N$ ngày gần đây:
* Regex bắt `(\d+)\s*ngày\s*(gần đây|qua|gần nhất)`.
* Tính toán khoảng đóng: `start = anchor - timedelta(days=N - 1)` đến `end = anchor`.
* Ví dụ: 7 ngày gần đây tính đến `27/08/2026` sẽ ra chính xác `2026-08-21` đến `2026-08-27` (đúng 7 ngày).

#### 5. Phân giải các cụm từ tương đối chuẩn:
* `"hôm nay"`: `[anchor, anchor]`.
* `"hôm qua"`: `[anchor - 1 day, anchor - 1 day]`.
* `"tháng này"`: `[ngày 01 đầu tháng, anchor]`.
* `"tháng trước"`: `[ngày 01 tháng trước, ngày cuối tháng trước]`.
* `"quý này"`: `[ngày đầu quý, anchor]`.
* `"quý trước"`: `[ngày đầu quý trước, ngày cuối quý trước]`.
* `"năm nay"`: `[01/01 năm nay, anchor]`.
* `"năm ngoái"`: `[01/01 năm ngoái, 31/12 năm ngoái]`.

#### 6. Tự động tính toán kỳ đối chiếu (Comparison Periods):
* Khi câu hỏi có cụm *"cùng kỳ năm ngoái"* hoặc *"cùng kỳ năm trước"*:
  * Tự động sinh `comparison_start_date` và `comparison_end_date` bằng cách lùi đúng 1 năm từ khoảng thời gian chính thông qua hàm `_shift_year_safe`.
* Khi câu hỏi có cụm *"so với tháng trước"* và khoảng thời gian chính là `"tháng này"`:
  * Tự động sinh kỳ đối chiếu là trọn vẹn tháng trước.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Tuyệt đối không dùng đồng hồ của máy chủ**:
   * Không dùng `datetime.now()` hay `datetime.today()`. Mọi phép tính đều neo theo `anchor = date.fromisoformat(as_of_date)`. Điều này bảo đảm câu hỏi của năm 2025 hay năm 2026 đều được tính toán chính xác tuyệt đối.
2. **Quy ước khoảng đóng (Inclusive Boundaries)**:
   * Thuật toán luôn xuất ra ngày bắt đầu và kết thúc theo chuẩn đóng `[start, end]`. Trong SQL chỉ cần viết `BETWEEN DATE 'start' AND DATE 'end'`, tránh được lỗi lệch 1 ngày khi dùng toán tử `<` hoặc `>`.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Cung cấp cho Agent Planner (B0.3)**: Planner không cần tự tính toán ngày tháng bằng các hàm DuckDB phức tạp như `DATE_SUB`, `INTERVAL`, `STRFTIME` (vốn là nơi LLM 9B hay viết sai cú pháp nhất). Planner chỉ việc chèn trực tiếp chuỗi ngày ISO vào câu lệnh SQL.
* **Cung cấp cho C5 Answerability Precheck**: C5 sử dụng `ResolvedTimeRange` để so sánh với `date_coverage_start` và `date_coverage_end` của bảng, kịp thời phát hiện các câu hỏi hỏi về khoảng thời gian mà doanh nghiệp chưa có dữ liệu.

---

## 5. Nếu Không Không Có File Này Thì Sao?

* Nếu để LLM tự viết logic lọc thời gian, mô hình sẽ mắc hàng loạt lỗi kinh điển:
  * Nhầm tháng 9/2025 với tháng 9/2026 do chỉ so sánh số tháng (`MONTH(col) = 8`) mà quên lọc năm (`YEAR(col) = 2026`).
  * Lấy sai mốc Tết Âm Lịch (vì LLM không biết chính xác mùng 1 Tết năm 2026 rơi vào ngày dương lịch nào).
  * Lọc nhầm ngày đặt đơn khi người dùng đang hỏi về ngày thu tiền ca tối.
