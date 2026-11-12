# Giải Thích Mã Nguồn: `rules_matcher.py`

**Đường dẫn file:** [`src/datamate/grounding/rules_matcher.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/rules_matcher.py)  
**Thuộc module:** Component C — Question Grounding (C1 Deterministic Fast-Path)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `rules_matcher.py` triển khai lớp `VietnameseRuleMatcher` — **Động cơ phân tích nhanh xác định (Deterministic Rule-Based Engine)** của module C1.

Trong bài toán hỏi đáp dữ liệu tiếng Việt của DataMate:
* Hơn **82% câu hỏi** là các câu hỏi tính toán số học hoặc tỷ lệ (`number` + `percent`) với các mẫu ngữ pháp lặp lại rõ rệt (*"Tổng doanh thu..."*, *"Có bao nhiêu đơn..."*, *"Top 5 sản phẩm..."*, *"Tăng bao nhiêu phần trăm..."*).
* Nếu gọi mô hình LLM lớn cho toàn bộ các câu hỏi này sẽ gây lãng phí nghiêm trọng về thời gian (latency) và tài nguyên tính toán (GPU budget < 6 giờ cho 1.000 câu test).

`VietnameseRuleMatcher` giải quyết triệt để vấn đề này bằng cách:
1. Chuẩn hóa chuỗi Unicode NFC và bóc tách các thành phần cấu trúc câu chỉ trong thời gian **dưới 2 miligiây**.
2. Phân loại chính xác phép toán giải tích (`OperationKind`), chỉ số mục tiêu (`target_metrics`), chiều gom nhóm (`group_by`), điều kiện lọc (`filters`), và gợi ý kiểu đầu ra (`answer_type_hint`).
3. Đánh giá điểm tự tin (`confidence`). Nếu câu hỏi khớp rõ ràng với mẫu ngữ nghĩa, nó trả về kết quả với độ tự tin cao (`0.90`), cho phép bỏ qua hoàn toàn việc gọi mô hình LLM 3B.

---

## 2. Chi Tiết Các Hằng Số & Thuật Toán Phân Tích

### 2.1. Các Hằng Số & Mẫu Ngữ Nghĩa Cốt Lõi

#### `_VN_NUMBER_WORDS`
Từ điển ánh xạ chữ số tiếng Việt sang số nguyên:
```python
{"một": 1, "hai": 2, "ba": 3, "bốn": 4, "năm": 5, "sáu": 6, "bảy": 7, "tám": 8, "chín": 9, "mười": 10}
```
* **Mục đích**: Bắt các câu hỏi diễn đạt số bằng chữ, ví dụ: *"năm sản phẩm được ưa chuộng nhất"* hoặc *"ít nhất ba đơn hàng"*. Nếu không có từ điển này, hệ thống sẽ bỏ sót giá trị $K=5$ hoặc điều kiện lọc `COUNT >= 3`.

#### `_BUILTIN_METRIC_PATTERNS`
Bộ mẫu từ vựng đặc trưng nhận diện 8 nhóm chỉ số kinh doanh:
1. `cash_collected`: *"tiền thực thu"*, *"tiền mặt thu được"*, *"thu được bao nhiêu tiền"*, *"thực thu"*, *"thu tiền mặt"*.
2. `distinct_product_orders`: *"được ưa chuộng"*, *"xuất hiện trong nhiều đơn"*, *"nhiều đơn mua nhất"*.
3. `sold_qty`: *"bán chạy"*, *"bán được bao nhiêu ly"*, *"bán được bao nhiêu phần"*, *"số lượng bán"*, *"tổng số lượng"*.
4. `revenue`: *"doanh thu"*, *"doanh số"*, *"mua nhiều tiền nhất"*, *"chi tiêu nhiều nhất"*, *"tổng thành tiền"*.
5. `order_count`: *"bao nhiêu đơn"*, *"số đơn hàng"*, *"tổng số đơn"*, *"số lượng hóa đơn"*, *"mấy đơn"*.
6. `cost`: *"chi phí"*, *"giá vốn"*, *"tiền vốn"*.
7. `gross_profit`: *"lợi nhuận gộp"*, *"lãi gộp"*, *"lợi nhuận"*.
8. `historical_stock`: *"tồn kho đầu kỳ"*, *"tồn kho cuối ngày"*, *"tồn kho lịch sử"*.

---

### 2.2. Chi Tiết Các Phương Thức Phân Tích

#### `extract_top_k(q_norm: str) -> int | None`
* Bắt cấu trúc số nguyên trực tiếp: `\btop\s+(\d+)\b` (ví dụ: `"Top 3"`, `"top 10"`).
* Bắt cấu trúc số + danh từ thực thể: `(\d+)\s+(sản phẩm|món|khách hàng|nhân viên)...` (ví dụ: `"5 sản phẩm bán chạy nhất"`).
* Bắt cấu trúc chữ số tiếng Việt + danh từ: `(năm|ba|mười)\s+(sản phẩm|khách hàng)...` qua từ điển `_VN_NUMBER_WORDS`.

#### `extract_metrics(q_norm: str, context: BusinessContextProtocol | None) -> list[str]`
* **Ưu tiên 1**: Tra cứu các `MetricSpec` có trong `context.get_metrics()` nếu alias của metric xuất hiện trong câu hỏi.
* **Ưu tiên 2**: Quét qua `_BUILTIN_METRIC_PATTERNS`.
* **Cơ chế phân giải xung đột nghiệp vụ tối quan trọng**:
  * Khi người dùng hỏi *"ca tối thu được bao nhiêu tiền mặt"*, cả cụm từ của `cash_collected` và `revenue` đều có thể bị kích hoạt.
  * Nếu trong câu hỏi **không xuất hiện chữ "doanh thu"**, hệ thống chủ động loại bỏ `revenue`, chỉ giữ lại `cash_collected`. Điều này ngăn Planner viết nhầm truy vấn tính doanh thu đặt hàng thay vì tiền mặt trong ca.

#### `extract_group_by(q_norm: str) -> list[str]`
* Nhận diện chiều gom nhóm từ chủ ngữ hoặc mệnh đề "theo...":
  * `"khách hàng nào"`, `"khách nào"`, `"theo khách hàng"` $\rightarrow$ `["customer"]`.
  * `"sản phẩm nào"`, `"món nào"`, `"sản phẩm được ưa chuộng"` $\rightarrow$ `["product"]`.
  * `"ngày nào"`, `"vào ngày mấy"`, `"theo ngày"` $\rightarrow$ `["date"]`.
  * `"ca nào"`, `"theo ca"` $\rightarrow$ `["shift"]`.

#### `extract_filters_and_entities(question, q_norm, context) -> tuple[list[FilterCondition], list[str]]`
1. **Trích xuất điều kiện `HAVING`**:
   * Bắt các cụm: `(?:ít nhất|tối thiểu|từ)\s+(\d+|chữ_số)\s+đơn`.
   * Tạo đối tượng `FilterCondition(field_hint="order_count", operator=">=", raw_value=val, is_having=True)`.
2. **Đối chiếu từ điển Alias thực thể từ Context**:
   * Nếu cụm từ alias (ví dụ `"ca tối"`, `"ck"`, `"đã hủy"`) xuất hiện trong câu hỏi, hệ thống tạo sẵn `FilterCondition` kèm `grounded_column` và `grounded_value`.
3. **Trích xuất tên sản phẩm có kèm kích cỡ**:
   * Regex chuyên dụng: `([A-ZÀÁ...][^?.,;]*?\([SMLsml]\))`.
   * Nhận diện chính xác tên món bán cấu trúc như `"Cà phê sữa (L)"` mà không làm mất thông tin size.

#### `match(question: str, context: BusinessContextProtocol | None) -> QuestionIntent`
Hàm điều phối logic phân tích tổng hợp:
* Xác định `OperationKind` theo thứ tự ưu tiên:
  1. `PERCENT_CHANGE`: có cụm *"bao nhiêu phần trăm"*, *"tăng hay giảm"*.
  2. `RATIO`: có cụm *"chiếm tỷ lệ"*, *"tỷ trọng"*.
  3. `EXISTENCE`: có dạng *"Có ... không?"* mà không hỏi số lượng $\rightarrow$ `AnswerTypeHint.BOOLEAN`.
  4. `TOP_K`: khi `top_k is not None` $\rightarrow$ `AnswerTypeHint.LIST`.
  5. `ARGMAX` / `ARGMIN`: khi có *"cao nhất"*, *"nhiều nhất"*, *"thấp nhất"*. Tự động suy luận kiểu đáp án: nếu gom nhóm theo ngày $\rightarrow$ `DATE`, nếu theo thực thể $\rightarrow$ `STRING`.
  6. `AVG`: khi có *"trung bình"*, *"bình quân"*.
  7. `COUNT_DISTINCT`: khi có *"bao nhiêu khách hàng"*, *"bao nhiêu mặt hàng khác nhau"*.
  8. `COUNT`: khi có *"có bao nhiêu đơn"*, *"tổng số đơn"*.
  9. `SUM`: các câu hỏi tính tổng thông thường.
* **Định lượng độ tự tin (`confidence`)**:
  * Các câu hỏi khớp mẫu chuẩn: `confidence = 0.90`.
  * Câu hỏi mơ hồ không nhận diện được operation hoặc câu hỏi tính toán mà không khớp được metric nào: `confidence` bị hạ xuống `0.45`–`0.55` để báo hiệu cho `QuestionIntentParser` kích hoạt tầng 3B LLM Fallback.

---

## 3. Tại Sao Lại Thiết Kế & Code Như Vậy?

1. **Chuẩn hóa Unicode NFC trước khi so khớp**:
   * Tiếng Việt có hai chuẩn gõ: Unicode tổ hợp (NFD) và Unicode dựng sẵn (NFC). Nếu người dùng gõ `"tháng"` dạng tổ hợp mà regex viết dạng dựng sẵn, so khớp chuỗi sẽ thất bại hoàn toàn. Lệnh `unicodedata.normalize("NFC", question)` ở dòng đầu tiên đảm bảo tính tương thích tuyệt đối.
2. **Khóa chặt tính tất định (100% Deterministic)**:
   * Thuật toán Regex luôn trả về cùng một kết quả cho cùng một đầu vào trên mọi môi trường chạy, loại bỏ sự bất định ngẫu nhiên (sampling randomness) của LLM.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Cung cấp đầu vào cho C2 và C3**: `target_metrics` và `entities` do Rule Matcher trích xuất được C2 dùng để chọn `DateRole` và được C3 dùng để chấm điểm xếp hạng bảng Fact Table.
* **Cung cấp gợi ý cấu trúc cho C1 Coordinator**: Giá trị `confidence` quyết định việc có cần tốn thêm thời gian gọi mô hình 3B hay không.

---

## 5. Nếu Không Có File Này Thì Sao?

* Nếu không có fast-path này, 100% câu hỏi (kể cả những câu đơn giản nhất như *"Hôm nay có bao nhiêu đơn hàng?"*) đều phải gửi prompt vào mô hình ngôn ngữ lớn. Điều này sẽ khiến thời gian xử lý toàn tuyến tăng vọt gấp **50 đến 100 lần**, dễ dẫn đến nguy cơ bị Ban tổ chức chấm điểm Timeout (vượt quá ngân sách thời gian chạy cho phép).
