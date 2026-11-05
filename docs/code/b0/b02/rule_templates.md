# Giải Thích Mã Nguồn: `rule_templates.py` (B0.2)

**Đường dẫn file:** `src/datamate/b0/b02/rule_templates.py`  
**Thuộc module:** B0.2 Context Extractor & Business Rules  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `rule_templates.py` là **Thư viện Gắn kết Công thức Nghiệp vụ Chuẩn (Approved Formula Template Binder)**.

Trong các bài toán phân tích kinh doanh của cuộc thi Zalo AI Challenge, có 3 công thức tài chính xuất hiện liên tục và có quy định tính toán cực kỳ chi tiết trong Rulebook:
1. **Doanh thu (`revenue`)**
2. **Lãi gộp (`gross_profit`)**
3. **Số lượng bán cơ bản (`sold_qty_base`)**

Module này nhận nhiệm vụ: đối chiếu văn bản quy tắc trong đề bài với điều khoản chuẩn, kiểm tra các điều kiện tiên quyết (bằng chứng loại trừ đơn hủy, phạm vi ngày, đơn vị bán), và gắn các cột thực tế của bảng vào các vai trò tính toán (roles).

---

## 2. Chi Tiết Các Mẫu Công Thức Được Phê Duyệt (`_APPROVED_TEXT`)

Hệ thống lưu trữ chính xác nguyên văn 3 điều khoản chuẩn đã được đội ngũ kỹ sư thẩm định:

```python
_APPROVED_TEXT = {
    "revenue": "Doanh thu một đơn | tổng **thành tiền các dòng hàng** (đã trừ giảm giá trên từng dòng)...",
    "gross_profit": "Lãi gộp | doanh thu (§1) trừ giá vốn của hàng đã bán...",
    "sold_qty_base": "Bán chạy | theo **số lượng quy về đơn vị cơ bản**, không theo số dòng hay số tiền; bỏ đơn huỷ, trả...",
}
```

### Các Vai Trò Cột Cần Thiết (`_ROLES`):
* `revenue`: Cần cột `line_amount` (thành tiền từng dòng hàng).
* `gross_profit`: Cần các cột `line_amount`, `quantity` (số lượng), `unit_cost` (giá vốn ghi trên dòng bán).
* `sold_qty_base`: Cần cột `base_quantity` (số lượng quy về đơn vị cơ bản).

### Các Yêu Cầu Bằng Chứng Nghiệp Vụ (`_REQUIREMENTS`):
* `valid_revenue_orders`: Đã loại bỏ các đơn hàng bị hủy hoặc hoàn trả toàn phần/bán phần.
* `order_date_scope`: Đã áp dụng bộ lọc ngày đơn hàng theo tham số `as_of_date`.
* `sales_line_grain`: Đúng độ chi tiết từng dòng xuất bán (không bị trùng lặp).
* Với lãi gộp: thêm `unit_cost_recorded_at_sale` (giá vốn ghi nhận tại thời điểm bán) và `quantity_and_cost_same_selling_unit`.

---

## 3. Lớp `RuleTemplateBinder` & Phương Thức `bind`

* **Cơ chế hoạt động**:
  1. **So khớp nguyên văn điều khoản**: So sánh văn bản của `source_rule` với `_APPROVED_TEXT` (sau khi chuẩn hóa Unicode NFC và khoảng trắng). Nếu không khớp chính xác ➔ Giữ nguyên trạng thái `descriptive` (chưa tự động áp công thức).
  2. **Kiểm tra vai trò cột (Role Mapping)**: Đảm bảo người gọi đã ánh xạ đủ tất cả các vai trò yêu cầu vào các cột thực tế trong cùng một bảng bán hàng.
  3. **Kiểm tra Bằng chứng (`evidence`)**: Bắt buộc phải cung cấp đủ các bằng chứng trong `_REQUIREMENTS`. Thiếu bất kỳ bằng chứng nào ➔ Gắn nhãn `status = "invalid"`.
  4. **Sinh biểu thức DSL**: Tạo biểu thức DSL tương ứng (ví dụ: `sub(line_amount, mul(quantity, unit_cost))`) và cập nhật `rule.status = "validated"`.

---

## 4. Tại Sao Lại Code Như Vậy?

1. **Chỉ so khớp văn bản chính xác, không đoán mò theo từ khóa**:
   Nếu chỉ dựa vào từ khóa `"lãi gộp"`, một shop có thể định nghĩa lãi gộp khác (ví dụ: trừ thêm chi phí vận chuyển hoặc hoa hồng sàn). Việc đối chiếu nguyên văn đảm bảo công thức toán học hoàn toàn ăn khớp với quy định của Rulebook.
2. **Yêu cầu bằng chứng rõ ràng (Traceability)**:
   Không tự tiện tính doanh thu nếu chưa có bằng chứng đã lọc bỏ đơn hủy. Việc này giúp tránh các lỗi logic nghiêm trọng trong tính toán tài chính.

---

## 5. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Module B0.3 (Text-to-SQL)**: Không cần phải tự bịa ra công thức tính lãi gộp phức tạp, mà có sẵn biểu thức SQL chuẩn đã được tham số hóa từ template binder.
* **Module B0.5 (Output Gate)**: Giúp B0.5 định dạng đáp án sang `money_vnd` và làm tròn số tiền đúng theo quy tắc tiền VND (không lấy số lẻ thập phân).

---

## 6. Nếu Không Có File Này Thì Sao?

* LLM thường xuyên nhầm lẫn giữa Lãi gộp (Gross Profit) và Lợi nhuận ròng (Net Profit), hoặc tự ý lấy giá vốn từ bảng kho thay vì giá vốn ghi nhận tại dòng bán như Rulebook yêu cầu.

