# Giải Thích Mã Nguồn: `rule_compiler.py` (B0.2)

**Đường dẫn file:** `src/datamate/b0/b02/rule_compiler.py`  
**Thuộc module:** B0.2 Context Extractor & Business Rules  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `rule_compiler.py` đảm nhận việc **Tiếp nhận tài liệu Markdown (Rulebook/README) và Biên dịch Quy tắc sang biểu thức SQL an toàn**.

Nó chuyển đổi các câu văn quy tắc tự nhiên (tiếng Việt hoặc Markdown) thành:
1. Danh mục quy tắc có định danh ổn định (SHA-256 hash).
2. Biểu thức DSL có cấu trúc (`structured expression`).
3. Câu lệnh SQL fragment kèm các tham số ràng buộc (`bound parameters`) để chống SQL Injection.

---

## 2. Chi Tiết Lớp & Thuật Toán Lõi

### 2.1. Lớp `BusinessRuleCompiler`

#### A. Phương thức `ingest_documents(paths, business_id, schema)`
* Đọc danh sách các tệp Markdown.
* Bóc tách từng đoạn văn (paragraph) và từng dòng trong bảng Markdown (`| col1 | col2 |`).
* **Xác định Scope & Precedence tự động**:
  * Nếu nằm dưới tiêu đề `# Doanh nghiệp ...` ➔ `scope = "business"`, `precedence = 300`.
  * Nếu nằm dưới tiêu đề `# Ngành ...` ➔ `scope = "industry"`, `precedence = 200`.
  * Mặc định: `scope = "split_default"`, `precedence = 100`.
* **Sinh Rule ID tất định**:
  Sử dụng SHA-256 băm từ chuỗi đã chuẩn hóa Unicode NFC và gộp khoảng trắng:
  ```python
  rule_id = hashlib.sha256(normalized_text.encode("utf-8")).hexdigest()[:12]
  ```
  *Ý nghĩa*: Đảm bảo cùng một đoạn văn quy tắc thì dù chạy lại bao nhiêu lần vẫn sinh ra đúng ID đó (100% Deterministic).

#### B. Ngôn ngữ DSL có cấu trúc (`_RULES`)
Hỗ trợ tập hợp các toán tử an toàn:
* So sánh: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `is_null`.
* Logic: `and`, `or`, `not`.
* Số học: `add`, `sub`, `mul`, `div`.
* Tập hợp: `sum`, `count_distinct`, `count_rows`.

#### C. Phương thức `compile_rule(rule, schema)`
* Kiểm tra `rule.status == "validated"`. Nếu rule bị lỗi hoặc chưa thẩm định ➔ Từ chối biên dịch (`ValueError`).
* Duyệt cây biểu thức DSL để sinh ra:
  * `sql_fragment`: Chuỗi SQL hợp lệ với các placeholder tham số (ví dụ: `"orders"."status" = ?`).
  * `parameters`: Tuple các giá trị thực truyền vào tham số để tránh SQL Injection.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Chuẩn hóa Unicode NFC**:
   Tiếng Việt trong Markdown có thể ở dạng tổ hợp (NFD) hoặc dựng sẵn (NFC). Nếu không chuẩn hóa NFC, hai chuỗi nhìn giống hệt nhau sẽ cho ra 2 mã hash SHA-256 khác nhau, làm mất tính ổn định của rule ID.
2. **Tham số hóa câu truy vấn (Parameterized SQL)**:
   Thay vì ghép chuỗi thô `f"WHERE status = '{val}'"`, hệ thống sinh ra `status = ?` và trả về danh sách parameters. Điều này bảo vệ an toàn 100% trước các chuỗi độc hại trong tài liệu.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* Cung cấp danh mục quy tắc sạch cho `RuleResolver`.
* Cung cấp các biểu thức SQL mẫu để LLM (B0.3) hoặc Rule Template Binder (B0.2) tham khảo và gắn kết.

---

## 5. Nếu Không Có File Này Thì Sao?

* Hệ thống buộc phải ném nguyên văn bản Markdown thô vào Prompt của LLM, làm tăng vọt số lượng token và khiến LLM dễ bị nhầm lẫn quy tắc.
* Không có ID quy tắc ổn định để theo dõi vết (provenance / audit log) khi kết quả trả lời bị sai.

