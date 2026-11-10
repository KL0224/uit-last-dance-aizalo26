# Giải Thích Mã Nguồn: `value_grounder.py`

**Đường dẫn file:** [`src/datamate/grounding/value_grounder.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/value_grounder.py)  
**Thuộc module:** Component C — Question Grounding (C4 Value Grounder)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `value_grounder.py` triển khai lớp `ValueGrounder` (module con **C4**).

Trong bài toán Vietnamese Tabular QA, một rào cản rất lớn dẫn đến việc câu truy vấn SQL chạy thành công nhưng trả về **kết quả rỗng hoặc bằng 0** là sự sai lệch từ vựng (Vocabulary Mismatch) giữa ngôn ngữ tự nhiên và dữ liệu thực tế:
1. **Từ viết tắt & từ lóng**: Người dùng hỏi *"thanh toán CK"* hoặc *"thanh toán MoMo"*, nhưng trong database lưu chuỗi `"Chuyển khoản"` hoặc `"Ví MoMo"`. Nếu câu lệnh SQL viết `WHERE phuong_thuc = 'CK'`, truy vấn sẽ trả về 0 dòng.
2. **Khác biệt về chữ hoa/chữ thường và chuẩn gõ dấu**: Người dùng gõ không dấu hoặc viết thường `"ca toi"`, trong khi cơ sở dữ liệu lưu chữ hoa có dấu `"Ca tối"`.
3. **Dữ liệu bán cấu trúc (Semi-structured Strings)**: Tên món ăn thường bị gộp chung kích cỡ và topping vào một cột duy nhất (ví dụ câu hỏi hỏi *"Cà phê sữa (L)"*, trong DB lưu `"Cà phê sữa (L)"`; hoặc câu hỏi hỏi *"Trà sữa trân châu"*, trong DB lưu `"Trà sữa trân châu (L) + Kem cheese"`).

Module C4 đảm nhận vai trò **Liên kết thực thể với dữ liệu thực tế (Entity & Value Linker)**, chịu trách nhiệm đối chiếu và chuẩn hóa mọi thực thể được trích xuất từ câu hỏi sang đúng giá trị thực tế đang lưu trong database.

---

## 2. Chi Tiết Các Hàm & Thuật Toán Đối Chiếu

### 2.1. Các Hàm Chuẩn Hóa Chuỗi Ký Tự

* **`_normalize_text(text: str) -> str`**:
  * Chuẩn hóa chuỗi về dạng Unicode dựng sẵn `NFC` (`unicodedata.normalize("NFC", text)`), cắt tỉa khoảng trắng 2 đầu và chuyển toàn bộ về chữ thường.
* **`_strip_accents(text: str) -> str`**:
  * Thuật toán khử dấu tiếng Việt chuyên sâu:
    1. Chuyển chữ `đ` và `Đ` thành `d`.
    2. Chuyển chuỗi sang dạng Unicode tổ hợp `NFD`.
    3. Loại bỏ toàn bộ các ký tự dấu thanh thuộc danh mục `Mn` (Nonspacing Mark).
  * Cho phép so sánh chuỗi không phân biệt dấu tiếng Việt (ví dụ: `"ca toi"` khớp hoàn hảo với `"Ca tối"`).

---

### 2.2. Chiến Lược Đối Chiếu 3 Tầng (`_lookup_value`)

Khi tiếp nhận một cụm từ thực thể (`raw_phrase`), thuật toán tìm kiếm thực hiện lần lượt 3 tầng từ độ tin cậy cao nhất đến thấp nhất:

#### Tầng 1: Tra cứu từ điển Alias nghiệp vụ (`exact_alias`, confidence = `1.00`):
* So khớp cụm từ đã chuẩn hóa với danh bạ `context.get_value_aliases()`.
* Đây là các quy ước nghiệp vụ đã được biên dịch từ sổ tay (Rulebook) hoặc README của doanh nghiệp (ví dụ: `"ck"` $\rightarrow$ `("shift_payments", "payment_method", "Chuyển khoản")`, `"thành công"` $\rightarrow$ `("orders", "status", "Hoàn thành")`).
* Nếu khớp ở tầng này, kết quả được công nhận ngay lập tức với độ tin cậy tối đa.

#### Tầng 2: So khớp với tập giá trị mẫu của cột (`exact_sample` / `unaccented_sample`, confidence = `0.90`–`0.98`):
* Quét qua danh sách các giá trị mẫu `sample_values` của các cột (ưu tiên duyệt các bảng đã được C3 chọn trước).
* Nếu trùng khớp 100% sau khi chuẩn hóa chữ thường: trả về `MatchedValue` với `match_type="exact_sample"`, `confidence=0.98`.
* Nếu trùng khớp sau khi khử dấu tiếng Việt: trả về `MatchedValue` với `match_type="unaccented_sample"`, `confidence=0.90`.

#### Tầng 3: So khớp chuỗi con có kiểm soát (`substring_sample`, confidence = `0.80`):
* Dành cho các cụm từ có độ dài từ 4 ký tự trở lên.
* Nếu cụm từ của người dùng là chuỗi con nằm bên trong giá trị của cột (ví dụ: cụm từ `"trà sữa trân châu"` nằm trong giá trị mẫu `"Trà sữa trân châu (L) + Kem cheese"`).
* Giúp bắt được các món ăn/dịch vụ bị gộp thông tin chi tiết.

---

### 2.3. Phương Thức Điều Phối `ground(...)`

```python
def ground(
    self,
    question: str,
    intent: QuestionIntent,
    selected_schema: SelectedSchema,
    context: BusinessContextProtocol,
) -> tuple[tuple[MatchedValue, ...], tuple[FilterCondition, ...]]:
```

#### Quy Trình Xử Lý:
1. **Đối chiếu thực thể từ `intent.entities`**:
   * Gọi `_lookup_value()` cho từng thực thể.
   * Lưu các kết quả hợp lệ vào danh sách `matched_list` (sử dụng tập `seen_matches` để khử trùng lặp).
2. **Cập nhật và làm giàu các điều kiện lọc (`intent.filters`)**:
   * Duyệt qua từng điều kiện lọc `FilterCondition`. Bỏ qua các điều kiện lọc số học (như `raw_value=3`).
   * Với các điều kiện lọc chuỗi (ví dụ `field_hint="shift_name"`, `raw_value="ca tối"`), thuật toán đối chiếu và điền giá trị chuẩn vào:
     * `grounded_column = "shift_payments.shift_name"`
     * `grounded_value = "Ca tối"`
3. **Quét trực tiếp câu hỏi đối chiếu với tập mẫu của B0.1 (`question_sample`, confidence = `0.92`)**:
   * Quét các giá trị mẫu chuỗi (`sample_values`) của toàn bộ các cột phi số học (loại trừ `date`, `money`, `quantity`).
   * Nếu giá trị mẫu xuất hiện nguyên văn trong câu hỏi của người dùng (ví dụ: `"ShopeeFood"` hay `"KHO-HN"`), thuật toán tự động gắn kết thành `MatchedValue` tương ứng với bảng và cột đó.
4. Trả về bộ đôi: `(tuple[MatchedValue, ...], tuple[FilterCondition, ...])`.

---

## 3. Tại Sao Lại Thiết Kế & Code Như Vậy?

1. **Ưu tiên bảng đã chọn bởi C3 trước**:
   * Thay vì tìm kiếm mù quáng trên toàn bộ các cột của tất cả các bảng trong database (rất dễ gây nhầm lẫn nếu có 2 cột cùng lưu tên người), thuật toán sắp xếp thứ tự duyệt: **các bảng trong `SelectedSchema` được kiểm tra trước**, sau đó mới mở rộng ra các bảng còn lại.
2. **Khử dấu tiếng Việt thông minh (`_strip_accents`)**:
   * Người dùng khi gõ câu hỏi tiếng Việt trên điện thoại hoặc bàn phím máy tính thường hay bị lỗi bộ gõ (Unikey) dẫn đến gõ thiếu dấu hoặc sai kiểu gõ. Thuật toán khử dấu giúp hệ thống vẫn hiểu đúng ý người dùng.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Cung cấp dữ liệu cho Agent Planner (B0.3)**:
  * Planner nhận được thông tin ánh xạ rõ ràng: cụm từ `"ca tối"` trong câu hỏi ứng với cột `shift_payments.shift_name` và giá trị trong DB là `'Ca tối'`.
  * Planner không cần phải đoán giá trị, chỉ cần viết mệnh đề `WHERE shift_name = 'Ca tối'`. Điều này loại bỏ hoàn toàn lỗi truy vấn ra kết quả rỗng.

---

## 5. Nếu Không Có File Này Thì Sao?

* LLM 9B sẽ tự bịa ra giá trị để điền vào mệnh đề `WHERE` (ví dụ: `WHERE status = 'thành công'` thay vì `'Hoàn thành'`, hoặc `WHERE payment_method = 'CK'` thay vì `'Chuyển khoản'`). Khi đó câu lệnh SQL chạy rất êm, không báo lỗi cú pháp nhưng kết quả trả về luôn là `0` hoặc `NULL` $\rightarrow$ Hệ thống bị mất trọn vẹn điểm số của các câu hỏi này.
