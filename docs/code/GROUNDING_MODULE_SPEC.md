# Đặc Tả Kỹ Thuật & Hướng Dẫn Tích Hợp Module Grounding (Component C)

**Tài liệu kiến trúc chi tiết:** [`docs/architecture/grounding/GROUNDING_ARCHITECTURE.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/architecture/grounding/GROUNDING_ARCHITECTURE.md)  
**Mục lục giải thích từng file code:** [`docs/code/grounding/README.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/grounding/README.md)

---

## 1. Hướng Dẫn Dành Cho Thành Viên Phụ Trách B0.1 / B0.2 (Upstream Producer)

Component C nhận ngữ cảnh doanh nghiệp thông qua [`B02ContextAdapter`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/adapters.py) hoặc bất kỳ đối tượng nào thỏa mãn [`BusinessContextProtocol`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/protocols.py). Để C2, C3, C4, C5 đạt độ chính xác tối đa, khi nâng cấp B0.1/B0.2 cần lưu ý:
1. **Trạng thái JOIN (`JoinEdge.status`)**: Đảm bảo các cạnh quan hệ đáng tin cậy được gắn cờ `status="validated"` (thông qua review manifest hoặc SQL profile toàn bảng). Cạnh `uncertain`, `candidate`, `invalid` sẽ tự động bị Grounding bỏ qua.
2. **Khóa Nối Phức Hợp (`JoinEdge.additional_key_pairs`)**: Khi nối 2 bảng qua nhiều cột, khai báo đầy đủ các cặp khóa phụ. Grounding sẽ tự động bảo toàn và render mệnh đề `AND` đầy đủ cho Planner.
3. **`TableMetadata.profile_rows` & `data_profiling`**:
   - Runtime: Cung cấp tối thiểu 5–15 dòng mẫu trong `profile_rows`.
   - File JSON (Contract 1.0/1.1): Khi `profile_rows` bị `pop()`, đảm bảo mẫu được lưu tại `data_profiling[table]["samples"]` và khoảng thời gian tại `observed_min`/`observed_max`.
4. **Nạp trực tiếp từ JSON (`from_dict`)**: Có thể nạp thẳng từ dictionary của file JSON qua `B02ContextAdapter.from_dict(payload)` (tự động gọi `BusinessContextSchemaReader`).
5. **`BusinessContext.answerability_constraints`**: Đặt rõ `"supported"` hoặc `"unsupported"` cho các khóa năng lực: `"customers"`, `"cost"`, `"historical_stock"`, `"payments"`, `"sales_by_product"`, `"expiry"`, `"warranties"`.
6. **`BusinessContext.business_metadata`**:
   - `"calendar_events"`: Danh sách các kỳ lễ/Tết từ `calendar.csv`.
   - `"value_aliases"`: Từ điển ánh xạ cụm từ viết tắt/đồng nghĩa tiếng Việt sang `(table_name, column_name, db_value)`.
   - `"schema_mapping"`: Bảng ánh xạ nguồn sang đích kèm `role` (`identifier`, `date`, `money`, `quantity`, `text`).

> [!NOTE] Chi tiết các thay đổi đồng bộ kiến trúc giữa B0.1/B0.2 và Grounding được ghi lại chi tiết tại [`docs/change/B01_B02_GROUNDING_COMPATIBILITY_CHANGELOG.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/change/B01_B02_GROUNDING_COMPATIBILITY_CHANGELOG.md).

---

## 2. Hướng Dẫn Dành Cho Thành Viên Phụ Trách B0.3 / B0.5 (Downstream Consumer)

1. **Khi `grounded.is_directly_unanswerable == True`**:
   * Không gọi LLM 9B (B0.3) và không chạy DuckDB (B0.4).
   * Gọi `proof = GroundingToPlannerAdapter.to_b05_evidence_proof(grounded)` và truyền thẳng vào `GateRequest` của B0.5 để xuất đáp án `"type": "unanswerable"`.
2. **Khi `grounded.is_directly_unanswerable == False`**:
   * Gọi `hint = GroundingToPlannerAdapter.format_grounded_hint_for_planner(grounded)` và nối vào cuối prompt ngữ cảnh của B0.3 để hướng dẫn mô hình 9B dùng đúng khoảng ngày, đúng bảng Fact chính và đúng giá trị lọc trong DB.

