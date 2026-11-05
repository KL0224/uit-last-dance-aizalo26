# Giải Thích Mã Nguồn: `rule_resolver.py` (B0.2)

**Đường dẫn file:** `src/datamate/b0/b02/rule_resolver.py`  
**Thuộc module:** B0.2 Context Extractor & Business Rules  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `rule_resolver.py` chịu trách nhiệm **Lọc quy tắc theo phạm vi (Scope Filtering) và Phân xử độ ưu tiên (Precedence Resolution)** khi có nhiều quy tắc cùng nói về một chủ đề (topic).

Nó đảm bảo rằng:
1. Quy tắc riêng (cho từng shop hoặc từng câu hỏi) luôn đè lên quy tắc chung.
2. Khi có mâu thuẫn giữa 2 quy tắc cùng mức ưu tiên cao nhất, hệ thống sẽ chặn chủ đề đó lại (`blocked_topics`) thay vì tự ý chọn bừa.

---

## 2. Chi Tiết Lớp & Logic Phân Xử

### 2.1. Thang Điểm Ưu Tiên (`PRECEDENCE`)
```python
PRECEDENCE = {
    "question_override": 400,  # Quy tắc ghi đè riêng cho câu hỏi
    "business": 300,           # Quy tắc riêng của từng Shop
    "industry": 200,           # Quy tắc của ngành hàng (F&B, Bán lẻ...)
    "split_default": 100,      # Quy tắc mặc định chung
}
```

### 2.2. Lớp `ResolvedRules`
* Chứa kết quả sau phân xử:
  * `rules`: Danh sách các quy tắc hợp lệ đã thắng thế sau khi so sánh độ ưu tiên.
  * `blocked_topics`: Danh sách các chủ đề bị khóa do xung đột mâu thuẫn.
  * `warnings`: Các cảnh báo phát sinh trong quá trình giải quyết.

### 2.3. Lớp `RuleResolver`
* **Phương thức**: `resolve(catalog, business_id, industry, question_id) -> ResolvedRules`.
* **Luồng xử lý 3 bước**:
  1. **Bước 1: Lọc theo Scope (Scope Filtering)**:
     * Chỉ giữ lại các quy tắc thuộc về đúng `business_id`, đúng `industry`, hoặc khớp với `question_id`.
     * Quy tắc thuộc về doanh nghiệp khác sẽ bị loại bỏ hoàn toàn.
  2. **Bước 2: Gom nhóm theo Chủ đề (Topic Grouping)**:
     * Nhóm các quy tắc có cùng `topic` (ví dụ: `doanh_thu`, `trang_thai_don_hang`).
     * Quy tắc không có topic thì được giữ nguyên độc lập.
  3. **Bước 3: Chọn Quy tắc Thắng Cuộc (Pick Highest Precedence)**:
     * Sắp xếp các quy tắc trong cùng topic theo `precedence` giảm dần.
     * **Xử lý Xung đột Mâu thuẫn**: Nếu có 2 quy tắc cùng đạt điểm cao nhất nhưng có nội dung khác nhau ➔ Đưa topic vào `blocked_topics` và ghi log cảnh báo.
     * **Bảo vệ Quy tắc Lỗi**: Nếu quy tắc có điểm cao nhất có trạng thái `status == "invalid"`, hệ thống **KHÔNG** tự động fallback về quy tắc mức thấp hơn, mà coi chủ đề đó bị lỗi.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Nguyên tắc "Lọc Scope trước, Tính điểm sau"**:
   Nếu tính điểm trước khi lọc scope, một quy tắc của shop A (mức 300) có thể đè bẹp quy tắc ngành của shop B (mức 200) khi dữ liệu vô tình bị lẫn. Việc lọc scope trước loại trừ hoàn toàn nguy cơ rò rỉ quy tắc giữa các shop.
2. **Không âm thầm Fallback khi Quy tắc cao nhất bị Invalid**:
   Ví dụ: Shop có quy tắc riêng về tính doanh thu (mức 300) nhưng bị thiếu cột trong DB nên bị đánh dấu `invalid`. Nếu hệ thống tự động nhảy về quy tắc mặc định (mức 100) để tính, kết quả sẽ bị sai hoàn toàn so với ý muốn của chủ shop. Do đó, việc chặn lại là giải pháp an toàn nhất.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Module B0.3 (Text-to-SQL)**: Chỉ nhận các quy tắc đã qua giải quyết mâu thuẫn (`ResolvedRules.rules`), giúp câu prompt ngắn gọn và chính xác 100%.
* **Module B0.5 (Output Gate)**: Nếu câu hỏi rơi vào chủ đề bị khóa (`blocked_topics`), Gate sẽ đưa ra quyết định `abstain` an toàn để không bị mất điểm.

---

## 5. Nếu Không Có File Này Thì Sao?

* LLM sẽ nhận được nhiều quy tắc trái ngược nhau trong cùng một prompt, dẫn đến việc mô hình phân vân và trả lời ngẫu nhiên (chập chờn / non-deterministic).

