# Thư Mục Tài Liệu Kỹ Thuật Module Question Grounding (Component C)

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Vị trí tài liệu:** [`docs/code/grounding/`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/grounding)  
**Vị trí mã nguồn:** [`src/datamate/grounding/`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding)  
**Tài liệu kiến trúc tổng thể:** [`docs/architecture/grounding/GROUNDING_ARCHITECTURE.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/architecture/grounding/GROUNDING_ARCHITECTURE.md)

---

## 1. Mục Đích Của Thư Mục Này

Thư mục này chứa bộ tài liệu giải thích chi tiết chuyên sâu cho **từng file mã nguồn** bên trong package `src/datamate/grounding/` (Component C: Question Grounding).

Mỗi tài liệu phân tích rõ:
* Vai trò của file trong luồng Question Grounding (C1 $\rightarrow$ C5).
* Chi tiết từng Class, Enum, Dataclass, Protocol và thuật toán bên trong.
* **Tại sao lại thiết kế & code như vậy?** (Những cân nhắc kỹ thuật gắn liền với quy chế Penalized Accuracy của Zalo AI Challenge 2026).
* Mối liên hệ với các module khác (B0.1, B0.2, B0.3, B0.5).
* **Nếu không có file này thì sao?** (Rủi ro ảo giác SQL, nhân dòng fanout, lệch ngày, bị trừ điểm PA).

---

## 2. Sơ Đồ Tương Tác Giữa Các File (Dependency & Call Graph)

```text
                       ┌───────────────────────────────────┐
                       │           contracts.py            │
                       │ (Enums & Immutable Data Schemas)  │
                       └─────────────────┬─────────────────┘
                                         │
                                         ▼
                       ┌───────────────────────────────────┐
                       │           protocols.py            │
                       │ (BusinessContext & 3B LLM Specs)  │
                       └─────────────────┬─────────────────┘
                                         │
        ┌────────────────┬───────────────┼───────────────┬────────────────┐
        ▼                ▼               ▼               ▼                ▼
rules_matcher.py    temporal.py   schema_grounder.py  value_grounder.py  answerability.py
(C1 Fast-Path)     (C2 Calendar)   (C3 BFS Join &     (C4 Alias & Sample (C5 Capability &
        │                │          Fact Ranking)       Value Linker)     Full Fallback)
        ▼                │               │               │                │
 llm_fallback.py         │               │               │                │
 (C1 3B Model)           │               │               │                │
        │                │               │               │                │
        ▼                │               │               │                │
    parser.py            │               │               │                │
  (C1 Coordinator)       │               │               │                │
        │                │               │               │                │
        └────────────────┴───────────────┼───────────────┴────────────────┘
                                         ▼
                                     engine.py
                             (QuestionGroundingEngine)
                                         │
                         ┌───────────────┴───────────────┐
                         ▼                               ▼
                 mock_provider.py                   adapters.py
            (Standalone Dev/Test Data)       (Bridge B0.2 <-> C <-> B0.3/B0.5)
                                                         │
                                                         ▼
                                                    __init__.py
                                                  (Public Facade)
```

---

## 3. Bảng Mục Lục Các File Giải Thích Chi Tiết

| Tên file tài liệu | File mã nguồn tương ứng | Tóm tắt vai trò & Trọng tâm giải thích |
|---|---|---|
| [**`contracts.md`**](contracts.md) | [`src/datamate/grounding/contracts.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/contracts.py) | Hợp đồng dữ liệu trung tâm: `OperationKind`, `AnswerTypeHint`, `CoverageStatus`, `QuestionRequest`, `GroundedQuestion`. |
| [**`protocols.md`**](protocols.md) | [`src/datamate/grounding/protocols.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/protocols.py) | Giao diện trừu tượng độc lập: `BusinessContextProtocol`, `LLMParserProtocol` và các descriptor nhẹ (`TableSpec`, `MetricSpec`). |
| [**`mock_provider.md`**](mock_provider.md) | [`src/datamate/grounding/mock_provider.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/mock_provider.py) | Kho ngữ cảnh giả lập: Tạo môi trường F&B có ca/topping và bán lẻ ẩn danh để phát triển/kiểm thử không phụ thuộc B0.1/B0.2. |
| [**`normalizer.md`**](normalizer.md) | [`src/datamate/grounding/normalizer.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/normalizer.py) | Tiền xử lý dùng chung: mở rộng viết tắt tiếng Việt theo whole-token allowlist trước C1–C5. |
| [**`rules_matcher.md`**](rules_matcher.md) | [`src/datamate/grounding/rules_matcher.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/rules_matcher.py) | C1 Fast-Path: Bộ nhận diện mẫu câu tiếng Việt, số đếm chữ ("một".."mười"), metric, điều kiện `HAVING` ("ít nhất N đơn"). |
| [**`llm_fallback.md`**](llm_fallback.md) | [`src/datamate/grounding/llm_fallback.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/llm_fallback.py) | C1 Fallback: Bộ kết nối mô hình 3B (`Qwen2.5-3B-Instruct`) trích xuất JSON có cấu trúc cho câu hỏi phức tạp. |
| [**`parser.md`**](parser.md) | [`src/datamate/grounding/parser.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/parser.py) | C1 Coordinator: Điều phối kết hợp giữa `VietnameseRuleMatcher` và `StructuredLLMParser` theo ngưỡng `fallback_threshold`. |
| [**`temporal.md`**](temporal.md) | [`src/datamate/grounding/temporal.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/temporal.py) | C2 Temporal Resolver: Phân giải ngày tương đối theo `as_of_date`, sự kiện Tết âm lịch, kỳ so sánh YoY/MoM và `DateRole`. |
| [**`schema_grounder.md`**](schema_grounder.md) | [`src/datamate/grounding/schema_grounder.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/schema_grounder.py) | C3 Schema Grounder: Xếp hạng bảng ưu tiên Fact Table, chọn cột liên quan, tìm đường nối BFS ngắn nhất và cảnh báo fanout 1-N. |
| [**`value_grounder.md`**](value_grounder.md) | [`src/datamate/grounding/value_grounder.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/value_grounder.py) | C4 Value Grounder: Chuẩn hóa Unicode NFC, khử dấu tiếng Việt và đối chiếu thực thể với giá trị thực tế trong DB. |
| [**`answerability.md`**](answerability.md) | [`src/datamate/grounding/answerability.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/answerability.py) | C5 Answerability Precheck: Kiểm tra `CapabilityMatrix` kết hợp quét toàn cục catalog để bắt `unanswerable` sớm và chống False UA. |
| [**`engine.md`**](engine.md) | [`src/datamate/grounding/engine.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/engine.py) | Trái tim điều phối: `QuestionGroundingEngine` kết nối C1 $\rightarrow$ C2 $\rightarrow$ C3 $\rightarrow$ C4 $\rightarrow$ C5 tạo ra `GroundedQuestion`. |
| [**`adapters.md`**](adapters.md) | [`src/datamate/grounding/adapters.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/adapters.py) | Cầu nối tích hợp: `B02ContextAdapter` (nhận B0.2) và `GroundingToPlannerAdapter` (xuất prompt hint cho B0.3 & `EvidenceProof` cho B0.5). |
| [**`init.md`**](init.md) | [`src/datamate/grounding/__init__.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/__init__.py) | Giao diện xuất khẩu (Public API Facade) của package `datamate.grounding`. |
