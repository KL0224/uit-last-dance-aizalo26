# Đặc Tả Kỹ Thuật & Hướng Dẫn Tích Hợp Module Grounding (Component C)

**Tài liệu kiến trúc chi tiết:** [`docs/architecture/grounding/GROUNDING_ARCHITECTURE.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/architecture/grounding/GROUNDING_ARCHITECTURE.md)  
**Mục lục giải thích từng file code:** [`docs/code/grounding/README.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/grounding/README.md)

---

## 1. Hướng Dẫn Dành Cho Thành Viên Phụ Trách B0.1 / B0.2 (Upstream Producer)

Component C nhận ngữ cảnh doanh nghiệp thông qua [`B02ContextAdapter`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/adapters.py) hoặc bất kỳ đối tượng nào thỏa mãn [`BusinessContextProtocol`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/protocols.py). Để C2, C3, C4, C5 đạt độ chính xác tối đa, khi nâng cấp B0.1/B0.2 cần lưu ý cung cấp:
1. **`TableMetadata.profile_rows`**: Cung cấp tối thiểu 5–15 dòng mẫu để `B02ContextAdapter` tự động trích xuất `sample_values` cho C4 Value Grounder.
2. **`BusinessContext.answerability_constraints`**: Đặt rõ `"supported"` hoặc `"unsupported"` cho các khóa năng lực: `"customers"`, `"cost"`, `"historical_stock"`, `"payments"`, `"sales_by_product"`, `"expiry"`, `"warranties"`.
3. **`BusinessContext.business_metadata`**:
   * `"calendar_events"`: Danh sách các kỳ lễ/Tết từ `calendar.csv`.
   * `"value_aliases"`: Từ điển ánh xạ cụm từ viết tắt/đồng nghĩa tiếng Việt sang `(table_name, column_name, db_value)`.

---

## 2. Hướng Dẫn Dành Cho Thành Viên Phụ Trách B0.3 / B0.5 (Downstream Consumer)

1. **Khi `grounded.is_directly_unanswerable == True`**:
   * Không gọi LLM 9B (B0.3) và không chạy DuckDB (B0.4).
   * Gọi `proof = GroundingToPlannerAdapter.to_b05_evidence_proof(grounded)` và truyền thẳng vào `GateRequest` của B0.5 để xuất đáp án `"type": "unanswerable"`.
2. **Khi `grounded.is_directly_unanswerable == False`**:
   * Gọi `hint = GroundingToPlannerAdapter.format_grounded_hint_for_planner(grounded)` và nối vào cuối prompt ngữ cảnh của B0.3 để hướng dẫn mô hình 9B dùng đúng khoảng ngày, đúng bảng Fact chính và đúng giá trị lọc trong DB.

