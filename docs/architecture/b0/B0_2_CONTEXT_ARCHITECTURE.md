# Kiến Trúc Module B0.2: Context Extractor & Business Rules Engine

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Tài liệu:** `docs/architecture/B0_2_CONTEXT_ARCHITECTURE.md`  
**Phiên bản:** `b02.v1.0`  
**Trạng thái:** Production-Ready / Fully Tested

---

## 1. Tổng Quan & Vai Trò Trong Pipeline Baseline B0

Trong chu trình giải quyết bài toán DataMate của Zalo AI Challenge 2026, các bài toán kinh doanh luôn đi kèm:
- **Rulebook** (Sổ tay quy tắc kế toán / bán hàng)
- **README** của từng doanh nghiệp (Mô tả đặc thù từng shop, ngành hàng bán lẻ, F&B...)

Nếu đưa toàn bộ văn bản thô vào LLM, mô hình dễ bị hallucination (ảo giác), nhầm lẫn giữa công thức ngành này với ngành khác, hoặc áp dụng quy tắc mức thấp đè lên quy tắc ghi đè riêng của câu hỏi.

Module **B0.2 Context Extractor & Business Rules** được thiết kế để:
1. **Phân giải và Số hóa quy tắc (Rule Ingestion & DSL Compilation)**: Đọc Markdown, sinh định danh ổn định (deterministic hash ID), chuyển đổi văn bản sang ngôn ngữ DSL có cấu trúc an toàn.
2. **Giải quyết Xung đột Thứ bậc Ưu tiên (Precedence & Conflict Resolution)**: Đảm bảo quy tắc cụ thể luôn thắng quy tắc chung, chặn đứng nếu có xung đột mâu thuẫn.
3. **Gắn kết Công thức Miền (Domain Formula Template Binding)**: Hỗ trợ 3 công thức tài chính sống còn: Doanh thu (`revenue`), Lãi gộp (`gross_profit`), Số lượng bán cơ bản (`sold_qty_base`).
4. **Đóng gói Ngữ cảnh Kinh doanh Hoàn chỉnh (`BusinessContext`)**: Tạo bản hợp đồng chuẩn mực cho B0.3 Text-to-SQL và B0.5 Output Gate.

```text
========================================================================================================================
[NGUỒN TÀI LIỆU & SCHEMA]            [MODULE B0.2: CONTEXT & RULE ENGINE]            [ĐẦU RA CHUẨN HÓA]
========================================================================================================================

┌─────────────────────────────┐
│  Rulebook Markdown          │──────┐
│  (Quy chuẩn kế toán/sàn)    │      │
└─────────────────────────────┘      ▼
                              ┌─────────────────────────────────────┐
┌─────────────────────────────┐│          rule_compiler.py          │
│  Business README Markdown   ││       (BusinessRuleCompiler)       │
│  (Đặc thù từng shop/ngành)  │└──────────┬──────────────────────┬──┘
└─────────────────────────────┘           │                      │
                                          ▼                      ▼
┌─────────────────────────────┐┌─────────────────────┐┌─────────────────────┐
│  SchemaCatalog (từ B0.1)    ││  rule_resolver.py   ││  rule_templates.py  │
│  (Tables, Columns, Grain)   ││   (RuleResolver)    ││ (RuleTemplateBinder)│
└──────────────┬──────────────┘│  Precedence 100-400 ││ (Revenue/Profit/Qty)│
               │               └──────────┬──────────┘└──────────┬──────────┘
               │                          │                      │
               │                          ▼                      ▼
               │              ┌─────────────────────────────────────────────┐
               └─────────────►│            contracts.py                     │
                              │          (ContractBuilder)                  │
                              └───────────────────▲─────────────────────────┘
                                                  │ (prepare)
                              ┌───────────────────┴─────────────────────────┐        ┌────────────────────────────────┐
                              │          context_service.py                 │───────►│    BusinessContext JSON v1.0   │
                              │       (BusinessContextService)              │        │  (Schema + Rules + Constraints)│
                              └─────────────────────────────────────────────┘        └────────────────────────────────┘
========================================================================================================================
```

---

## 2. Thang Bậc Ưu Tiên Quy Tắc (Precedence Hierarchy)

Khi giải quyết các câu hỏi, hệ thống áp dụng thang điểm ưu tiên số học từ cao xuống thấp:

```text
┌────────────────────────────────────────────────────────┐
│  Mức 400: question_override (Quy tắc đính kèm câu hỏi) │ ◄── Ưu tiên cao nhất
├────────────────────────────────────────────────────────┤
│  Mức 300: business          (Quy tắc riêng từng Shop)  │
├────────────────────────────────────────────────────────┤
│  Mức 200: industry          (Quy tắc theo Ngành hàng)  │
├────────────────────────────────────────────────────────┤
│  Mức 100: split_default     (Quy tắc mặc định toàn sàn)│ ◄── Mức cơ bản
└────────────────────────────────────────────────────────┘
```

> [!IMPORTANT]
> **Nguyên tắc Chống Mâu Thuẫn (Conflict Blocking):**
> Nếu trong cùng một chủ đề (topic) xuất hiện 2 quy tắc có cùng điểm ưu tiên cao nhất nhưng nội dung trái ngược nhau, hệ thống **tuyệt đối không đoán mò** mà sẽ gắn cờ `blocked_topics` để cảnh báo B0.5 hoặc người thẩm định.

---

## 3. Hợp Đồng Dữ Liệu Cốt Lõi (B0.2 Contracts)

| Lớp (Class) | Ý nghĩa nghiệp vụ | Các trường cốt lõi |
|---|---|---|
| `BusinessRule` | Một quy tắc nghiệp vụ đã số hóa | `rule_id`, `text`, `source`, `scope`, `precedence`, `status`, `required_fields`, `expression`, `topic`, `industry`, `binding_evidence` |
| `RuleCatalog` | Danh mục quy tắc của doanh nghiệp | `rules`, `warnings`, `business_id` |
| `BusinessContext` | Bản hợp đồng ngữ cảnh tối hậu | `contract_version`, `business_id`, `schema_catalog`, `rule_catalog`, `data_profiling`, `business_metadata`, `answerability_constraints` |
| `ContractBuilder` | Trình thẩm định và đóng gói | Hàm `build()` kiểm tra chéo tính hợp lệ giữa trường cần dùng của rule và cột có thực trong schema |

---

## 4. Chi Tiết Các Tệp Mã Nguồn B0.2

### 4.1. `rule_compiler.py` — Biên Dịch Quy Tắc Sang Biểu Thức DSL
* Đọc tài liệu Markdown, bóc tách các đoạn văn hoặc bảng biểu.
* Sinh hash ID dựa trên SHA-256 từ nội dung văn bản (đã chuẩn hóa Unicode NFC).
* Cung cấp DSL an toàn:
  * Phép so sánh: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `is_null`.
  * Phép logic: `and`, `or`, `not`.
  * Phép số học: `add`, `sub`, `mul`, `div`.
  * Phép tổng hợp: `sum`, `count_distinct`, `count_rows`.
* Biên dịch biểu thức thành SQL fragment có tham số hóa (`bound parameters`) để chống SQL Injection.

### 4.2. `rule_resolver.py` — Giải Quyết Ưu Tiên & Lọc Ngữ Cảnh
* Lọc danh mục rule theo `business_id`, ngành hàng (`industry`), và `question_id`.
* Lựa chọn quy tắc có `precedence` cao nhất cho mỗi topic.
* Ngăn chặn việc quy tắc bị lỗi (`invalid`) âm thầm bị thay thế bởi quy tắc thấp hơn.

### 4.3. `rule_templates.py` — Gắn Kết Công Thức Nghiệp Vụ Chuẩn
* Đối chiếu nguyên văn (Exact text match) 3 điều khoản tài chính:
  1. **Doanh thu (`revenue`)**: Tổng thành tiền các dòng hàng (đã trừ giảm giá dòng, không trừ voucher shop, không gồm VAT/phí ship).
  2. **Lãi gộp (`gross_profit`)**: Doanh thu trừ giá vốn dòng hàng (`quantity * unit_cost`).
  3. **Bán chạy (`sold_qty_base`)**: Số lượng quy về đơn vị cơ bản (bỏ đơn hủy/trả).
* Yêu cầu caller cung cấp đầy đủ bằng chứng (`evidence`): `valid_revenue_orders`, `order_date_scope`, `sales_line_grain`. Thiếu bằng chứng sẽ bị từ chối biên dịch.

### 4.4. `context_service.py` — Dịch Vụ Điều Phối (Orchestrator Service)
* Áp dụng Dependency Injection (DI): nhận `BaseMetadataProvider`, `SchemaCatalogBuilder`, `BusinessRuleCompiler`, `ContractBuilder`.
* Cung cấp hàm `prepare(business_id, documents) -> BusinessContext` chạy hoàn toàn độc lập, không phụ thuộc vào LLM hay internet, tốc độ thực thi dưới 10ms.

---

## 5. Tương Tác & Đồng Bộ Với Module B0.5 Basic Output Gate

1. **Ràng Buộc Khả Năng Trả Lời (`answerability_constraints`)**:
   Khi `BusinessContext` chứa trường `answerability_constraints`, nếu một câu hỏi vi phạm ràng buộc (ví dụ: dữ liệu chỉ có từ 2024 nhưng câu hỏi đòi số liệu 2022), thông tin này được truyền sang B0.5 để chứng minh hợp lệ câu hỏi là `unanswerable`.
2. **Định dạng Đáp án (Answer Type Hints)**:
   Nếu quy tắc áp dụng cho công thức Doanh thu/Lãi gộp, gợi ý kiểu đáp án sẽ là `number` với `numeric_kind = "money_vnd"`. B0.5 dựa vào đây để áp dụng thuật toán làm tròn `ROUND_HALF_UP` về đơn vị tiền tệ chính xác theo luật thi.

