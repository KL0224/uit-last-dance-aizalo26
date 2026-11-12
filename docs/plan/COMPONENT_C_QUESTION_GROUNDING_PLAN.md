# Kế Hoạch Triển Khai Module Question Grounding (Component C)

> **Tài liệu tham chiếu:**  
> - [`temp/Zalo_AI_Challenge_2026_Track2_Kien_truc_AI_Agent.docx`](file:///home/kiet97/uit-last-dance-aizalo26/temp/Zalo_AI_Challenge_2026_Track2_Kien_truc_AI_Agent.docx) (Tài liệu kiến trúc tổng thể DataMate)  
> - [`docs/architecture/b0/B0_5_PROOF_DRIVEN_GATE_ARCHITECTURE.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/architecture/b0/B0_5_PROOF_DRIVEN_GATE_ARCHITECTURE.md) (Kiến trúc Output Gate B0.5)  
> - [`docs/plan/B0_REMEDIATION_PLAN.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/plan/B0_REMEDIATION_PLAN.md) (Kế hoạch sửa chữa toàn tuyến B0)  
> **Phương pháp áp dụng:** Vertical Slicing (`planning-and-task-breakdown`) + Architecture Decision Records (`documentation-and-adrs`)  
> **Chiến lược phụ thuộc:** Giả định đầu vào độc lập (`Mock/Protocol BusinessContext`) để phát triển song song với quá trình nâng cấp B0.1 / B0.2.

---

## 1. Tổng Quan Kế Hoạch (Overview)

Module **Question Grounding (Component C)** đóng vai trò là "cầu nối tri thức" giữa Pha Chuẩn bị Dữ liệu (Pha A & B) và Pha Lập Kế Hoạch Truy Vấn (Pha D - Agent Planner). 

Trong bài toán Vietnamese Tabular QA của DataMate:
1. **Câu hỏi mang tính đa dạng cao**: Biểu đạt ngôn ngữ tự nhiên tiếng Việt phong phú, nhiều mốc thời gian tương đối ("tháng này", "7 ngày gần đây", "Tết"), nhiều thuật ngữ nghiệp vụ ("doanh thu", "tiền thực thu", "hàng trả", "topping").
2. **Nguy cơ phạt điểm (Penalized Accuracy - PA)**: Trả lời sai bị phạt **-1 điểm**, trả lời đúng **+1 điểm**, bỏ qua (abstain) **0 điểm**. Việc để LLM Planner tự mò mẫm trên toàn bộ schema hoặc tự bịa ra câu trả lời khi dữ liệu thiếu sẽ gây sụt giảm nghiêm trọng PA.
3. **Mục tiêu của Component C**: Phân tích câu hỏi tiếng Việt, chuẩn hóa mốc thời gian, liên kết đúng bảng/cột và giá trị thực trong DB, đồng thời **kiểm tra sơ bộ tính khả thi (Answerability Precheck - C5)** để phát hiện sớm các câu hỏi thiếu bằng chứng (`unanswerable`), chuyển giao một cấu trúc chuẩn mực `GroundedQuestion` cho Agent Planner mà không tốn token suy luận thừa.

Kế hoạch này thiết kế và triển khai trọn vẹn 5 sub-modules của Component C theo kiến trúc hướng module, độc lập hoàn toàn với tiến độ chỉnh sửa của B0.1/B0.2 thông qua **Mock Provider & Protocol Contracts**.

---

## 2. Quyết Định Kiến Trúc (Architecture Decision Records - ADRs)

### ADR-007: Hợp Đồng Giao Tiếp Độc Lập (`BusinessContextProtocol` & `GroundedQuestion`)
- **Trạng thái:** Accepted
- **Bối cảnh:** B0.1 (Data Foundation) và B0.2 (Business Semantics) đang được thành viên khác trong nhóm tái cấu trúc và bổ sung. Nếu Component C phụ thuộc trực tiếp vào code cụ thể của B0.1/B0.2, việc phát triển sẽ bị nghẽn (blocked).
- **Quyết định:**
  - Định nghĩa giao diện trừu tượng `BusinessContextProtocol` chứa các phương thức và thuộc tính cần thiết: `schema_catalog`, `join_graph`, `rule_catalog`, `metric_registry`, `capability_matrix`, `calendar_resolver`.
  - Xây dựng `MockBusinessContextProvider` cung cấp dữ liệu giả lập chuẩn theo đúng spec Section 4.2 của tài liệu kiến trúc, bao gồm các kịch bản thực tế (bán lẻ F&B, chuỗi dịch vụ, garage xe).
  - Chuẩn hóa đầu ra thành dataclass bất biến `GroundedQuestion` làm Single Source of Truth cho Planner (Component D).
- **Hệ quả:** Component C có thể phát triển, viết unit test và benchmark độc lập 100%. Khi B0.1/B0.2 hoàn thành chỉ cần implement đúng `BusinessContextProtocol`.

### ADR-008: Cơ Chế Phân Tích Ý Định Hybrid (C1: Rule-Based Fast-Path + Structured Parser Fallback)
- **Trạng thái:** Accepted
- **Bối cảnh:** Hơn 82.1% câu hỏi trong tập train là dạng số và tỷ lệ (`number` + `percent`). Các câu hỏi này có nhiều mẫu câu lặp lại ("Tổng doanh thu...", "Có bao nhiêu đơn...", "Top 5 khách hàng..."). Nếu gọi LLM 7B cho toàn bộ các câu đơn giản sẽ làm tăng P95 latency và hao phí ngân sách tính toán (vốn bị giới hạn < 6 giờ cho 1.000 câu test).
- **Quyết định:**
  - Triển khai **Rule-based Fast-Path Parser**: Dùng Regex + Từ điển mẫu ngữ nghĩa tiếng Việt nhận diện ngay lập tức các operation chuẩn (`sum`, `count`, `count_distinct`, `avg`, `top_k`, `percentage`, `min_max`).
  - Triển khai **Structured LLM Parser Fallback**: Chỉ kích hoạt khi câu hỏi có độ phức tạp cao, nhiều điều kiện lồng nhau hoặc không khớp với pattern thông thường.
- **Hệ quả:** Giảm thời gian xử lý trung bình xuống < 50ms cho phần lớn câu hỏi cơ bản, tiết kiệm tài nguyên GPU cho khâu sinh SQL phức tạp ở Planner.

### ADR-009: Giải Quyết Thời Gian Xác Định (C2: Deterministic Temporal Resolver)
- **Trạng thái:** Accepted
- **Bối cảnh:** Thời gian trong bài toán phụ thuộc chặt chẽ vào `as_of_date` của từng câu hỏi và lịch hoạt động doanh nghiệp (`calendar.csv`). LLM thường tính sai mốc ngày, nhầm lẫn giữa ngày đặt đơn (`order_date`), ngày thanh toán (`payment_date`), và không hiểu các khái niệm âm lịch / Tết.
- **Quyết định:**
  - C2 được xây dựng **100% bằng code logic deterministic**, nhận `as_of_date` và `CalendarResolver` từ context.
  - Phân giải chính xác các khoảng thời gian: "hôm nay", "tháng này" (từ ngày 01 đến `as_of_date`), "7 ngày gần đây", "quý này", "Tết Nguyên Đán" thành `ResolvedDateRange(start_date, end_date, date_column_role, inclusive=True)`.
- **Hệ quả:** Loại bỏ hoàn toàn lỗi tính toán ngày tháng của LLM, bảo đảm tính tái lập (deterministic) và dễ kiểm chứng qua test case.

### ADR-010: Cắt Giảm Chi Phí & Ngăn Phạt Điểm Bằng Answerability Precheck (C5)
- **Trạng thái:** Accepted
- **Bối cảnh:** Trong cơ chế chấm điểm PA, dự đoán sai bị trừ 1 điểm. Nếu câu hỏi yêu cầu thông tin mà doanh nghiệp hoàn toàn không có dữ liệu (ví dụ hỏi "khách hàng nào..." nhưng dữ liệu không lưu định danh khách), việc cố sinh SQL sẽ dẫn đến truy vấn sai hoặc ra kết quả rỗng giả tạo.
- **Quyết định:**
  - C5 đối chiếu `evidence_requirements` thu được từ C1/C3 với `CapabilityMatrix` của doanh nghiệp.
  - Phân loại rõ ràng 3 trạng thái:
    - `SUPPORTED`: Doanh nghiệp có đầy đủ bảng, cột và độ phủ thời gian $\rightarrow$ Chuyển tiếp Planner.
    - `UNSUPPORTED`: Doanh nghiệp đã được kiểm tra toàn bộ nguồn và xác nhận thiếu thành phần cốt lõi $\rightarrow$ Đóng gói bằng chứng `MissingEvidenceProof`, gắn nhãn `unanswerable`, không gọi Planner.
    - `UNKNOWN`: Dữ liệu có thể nằm ở cột phi cấu trúc hoặc nguồn gián tiếp $\rightarrow$ Cho phép Planner tiếp tục nhưng gắn cờ rủi ro (`risk_flag=True`).
- **Hệ quả:** Tối ưu hóa PA bằng cách nhận diện chính xác các câu `unanswerable` thực sự, đồng thời tiết kiệm thời gian chạy (chạy qua C5 tốn < 10ms, bỏ qua toàn bộ Planner/Executor).

---

## 3. Kiến Trúc Chi Tiết & Data Contracts

```
┌────────────────────────────────────────────────────────────────────────┐
│                        BusinessContext (Input)                         │
│  - schema_catalog: Bảng, cột, kiểu dữ liệu, grain, mô tả              │
│  - join_graph: Các cạnh nối bảng kèm cardinality và độ tin cậy         │
│  - rule_catalog: Quy tắc nghiệp vụ, ưu tiên (precedence), ngoại lệ    │
│  - metric_registry: Định nghĩa công thức (revenue, sold_qty,...)      │
│  - capability_matrix: Danh mục khả năng đáp ứng (sales, customer,...) │
│  - temporal_metadata: calendar.csv, ngày nghỉ, sự kiện Tết            │
└───────────────────────────────────┬────────────────────────────────────┘
                                    │
                                    ▼
┌────────────────────────────────────────────────────────────────────────┐
│               COMPONENT C: QUESTION GROUNDING ENGINE                   │
│                                                                        │
│   Câu hỏi tiếng Việt + as_of_date                                      │
│                │                                                       │
│                ▼                                                       │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ C1. Question Parser & Intent Extractor                       │     │
│   │     - Operation: sum, count, argmax, top-k, compare, lookup  │     │
│   │     - Metrics & Attributes: doanh thu, tiền mặt, số lượng...  │     │
│   │     - Entities & Filters: 'ca tối', 'sản phẩm A', 'đã giao' │     │
│   │     - Output Hint: number, percent, list, date, boolean...   │     │
│   └──────────────────────────────┬───────────────────────────────┘     │
│                                  │                                     │
│                ┌─────────────────┴─────────────────┐                   │
│                ▼                                   ▼                   │
│   ┌──────────────────────────────┐   ┌─────────────────────────────┐   │
│   │ C2. Temporal Resolver        │   │ C3. Schema Grounder         │   │
│   │     - Relative date parser   │   │     - Lexical & alias match │   │
│   │     - as_of_date anchoring   │   │     - Join path candidate   │   │
│   │     - Calendar/Tết lookup    │   │     - Top-k tables/columns  │   │
│   └──────────────┬───────────────┘   └─────────────┬───────────────┘   │
│                  │                                 │                   │
│                  └────────────────┬────────────────┘                   │
│                                   │                                     │
│                                   ▼                                     │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ C4. Value Grounder                                           │     │
│   │     - Fuzzy string matching / alias normalizer               │     │
│   │     - Lookup distinct values trong bảng mẫu / từ điển        │     │
│   │     - Gán giá trị thực trong DB vào filters                  │     │
│   └──────────────────────────────┬───────────────────────────────┘     │
│                                  │                                     │
│                                   ▼                                     │
│   ┌──────────────────────────────────────────────────────────────┐     │
│   │ C5. Answerability Precheck                                   │     │
│   │     - Đối chiếu evidence cần thiết với CapabilityMatrix      │     │
│   │     - Xác định coverage status: SUPPORTED / UNSUPPORTED /    │     │
│   │       UNKNOWN                                                │     │
│   └──────────────────────────────┬───────────────────────────────┘     │
│                                  │                                     │
└──────────────────────────────────┼─────────────────────────────────────┘
                                   │
                                   ▼
┌────────────────────────────────────────────────────────────────────────┐
│                    GroundedQuestion Contract (Output)                  │
│  - question_id: ID câu hỏi                                             │
│  - intent: OperationKind (sum, count, top_k,...)                       │
│  - metrics: Danh sách metrics chuẩn cần tính                           │
│  - entities: Danh sách thực thể được trích xuất                        │
│  - filters: Danh sách điều kiện lọc đã map giá trị thực                │
│  - resolved_time_ranges: Khoảng ngày cụ thể [start, end, role]         │
│  - selected_schema: Top-k bảng, cột và gợi ý đường join                │
│  - matched_values: Mapping giữa text câu hỏi và giá trị DB             │
│  - answer_type_hint: Gợi ý kiểu đáp án (number, percent, list,...)     │
│  - evidence_requirements: Danh mục bằng chứng bắt buộc                 │
│  - coverage_status: supported | unsupported | unknown                  │
│  - unanswerable_reason: Lý do nếu coverage_status == unsupported       │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 4. Phân Rã Nhiệm Vụ (Task Breakdown & Vertical Slices)

### Giai Đoạn 1: Nền Tảng Hợp Đồng & Mock Provider (Foundation & Contracts)

#### Task 1: Khởi tạo module contracts & Mock Business Context
- **Mô tả:** Tạo package `src/datamate/grounding/`, định nghĩa toàn bộ data contracts bằng dataclass/Pydantic (`GroundedQuestion`, `QuestionIntent`, `ResolvedTimeRange`, `SchemaCandidate`, `MatchedValue`, `CoverageStatus`, `EvidenceRequirement`), và xây dựng `MockBusinessContextProvider` dựa trên spec Section 4.2 của tài liệu kiến trúc.
- **Tiêu chí chấp nhận (Acceptance Criteria):**
  - [ ] Contract `GroundedQuestion` chứa đầy đủ các trường theo đặc tả kiến trúc.
  - [ ] `BusinessContextProtocol` xác định rõ các interface cần nạp từ B0.1/B0.2.
  - [ ] `MockBusinessContextProvider` sinh được context mẫu cho ít nhất 2 bài toán tiêu biểu: F&B có ca/topping (`dev_002`/`dev_003`) và chuỗi bán lẻ có chiết khấu/khách hàng.
- **Kiểm chứng (Verification):**
  - Lệnh test: `pytest tests/grounding/test_contracts.py`
- **Tệp liên quan:**
  - `src/datamate/grounding/__init__.py`
  - `src/datamate/grounding/contracts.py`
  - `src/datamate/grounding/protocols.py`
  - `src/datamate/grounding/mock_provider.py`
  - `tests/grounding/test_contracts.py`
- **Độ phức tạp:** M (3-4 files)

#### Task 2: Triển khai C2 - Question-level Temporal Resolver
- **Mô tả:** Xây dựng module phân giải thời gian tiếng Việt, nhận vào chuỗi câu hỏi, `as_of_date` và `CalendarMetadata`. Quy đổi các biểu thức tương đối thành khoảng ngày chuẩn (ISO YYYY-MM-DD), xác định vai trò ngày (`order_date` vs `payment_date`).
- **Tiêu chí chấp nhận (Acceptance Criteria):**
  - [ ] Nhận diện chính xác: "hôm nay", "hôm qua", "tháng này", "tháng trước", "quý này", "năm nay", "7 ngày gần đây", "30 ngày qua", "cùng kỳ năm trước".
  - [ ] "Tháng này" được phân giải từ ngày đầu tháng đến đúng `as_of_date` (inclusive).
  - [ ] Hỗ trợ tra cứu mốc sự kiện đặc thù từ calendar (ví dụ "Tết", kỳ nghỉ lễ).
- **Kiểm chứng (Verification):**
  - Lệnh test: `pytest tests/grounding/test_temporal.py`
- **Tệp liên quan:**
  - `src/datamate/grounding/temporal.py`
  - `tests/grounding/test_temporal.py`
- **Độ phức tạp:** S (2 files)

---

### Checkpoint 1: Nền tảng hợp đồng & phân giải thời gian
- [ ] Tất cả unit tests trong `tests/grounding/test_contracts.py` và `test_temporal.py` chạy qua 100%.
- [ ] Không có phụ thuộc vào code chưa hoàn thiện của B0.1/B0.2.

---

### Giai Đoạn 2: Trích Xuất Ngữ Nghĩa & Liên Kết Dữ Liệu (Intent, Schema, Value)

#### Task 3: Triển khai C1 - Question Parser & Intent Extractor
- **Mô tả:** Xây dựng bộ trích xuất ý định câu hỏi tiếng Việt kết hợp rule-based fast-path và parser ngữ nghĩa. Trích xuất: phép toán chính (`sum`, `count`, `avg`, `top_k`, `argmax`, `lookup`), metrics mục tiêu, bộ lọc điều kiện (ví dụ "ít nhất 3 đơn", "đã hoàn thành"), thông số ranking (`top_k`, thứ tự sắp xếp), và gợi ý kiểu đầu ra `answer_type_hint`.
- **Tiêu chí chấp nhận (Acceptance Criteria):**
  - [ ] Phân tích chính xác câu hỏi tính tổng/đếm/trung bình/top-k.
  - [ ] Phân biệt được `count` thường và `count_distinct` (ví dụ: "bao nhiêu đơn" vs "bao nhiêu sản phẩm khác nhau").
  - [ ] Trích xuất đúng `answer_type_hint` (number, percent, list, string, date, boolean).
- **Kiểm chứng (Verification):**
  - Lệnh test: `pytest tests/grounding/test_parser.py`
- **Tệp liên quan:**
  - `src/datamate/grounding/parser.py`
  - `src/datamate/grounding/rules_matcher.py`
  - `tests/grounding/test_parser.py`
- **Độ phức tạp:** M (3 files)

#### Task 4: Triển khai C3 & C4 - Schema Grounder & Value Grounder
- **Mô tả:** 
  - C3: Dựa trên intent, metric và entities trích xuất từ C1, đối chiếu với `SchemaCatalog` để xếp hạng các bảng/cột tiềm năng nhất (top-k relevance) và tra cứu các candidate join paths từ `JoinGraph`.
  - C4: Map các giá trị điều kiện trong câu hỏi (ví dụ "ca tối", "trà sữa trân châu", "thành công") với các giá trị thực tế trong database thông qua từ điển alias và distinct value lookup.
- **Tiêu chí chấp nhận (Acceptance Criteria):**
  - [ ] C3 gợi ý đúng bảng chính và bảng liên quan (ví dụ hỏi "doanh thu theo khách hàng" chọn đúng bảng đơn hàng và bảng khách hàng, không chọn bảng nhà cung cấp).
  - [ ] C3 phát hiện cảnh báo nguy cơ nhân dòng (fanout warning) nếu join một-nhiều.
  - [ ] C4 chuẩn hóa được text biến thể (ví dụ "tiền mặt", "CK", "đã giao hàng") về đúng enum/giá trị trong DB.
- **Kiểm chứng (Verification):**
  - Lệnh test: `pytest tests/grounding/test_schema_value_grounder.py`
- **Tệp liên quan:**
  - `src/datamate/grounding/schema_grounder.py`
  - `src/datamate/grounding/value_grounder.py`
  - `tests/grounding/test_schema_value_grounder.py`
- **Độ phức tạp:** M (3 files)

---

### Checkpoint 2: Trích xuất ý định và liên kết dữ liệu hoàn chỉnh
- [ ] C1 trích xuất đúng intent trên tập 25 câu hỏi đa dạng mẫu.
- [ ] C3 chọn đúng tập bảng/cột tối thiểu phục vụ câu truy vấn, không bao hàm bảng rác.
- [ ] C4 map chuẩn các alias tiếng Việt thông dụng vào enum/giá trị database.

---

### Giai Đoạn 3: Kiểm Tra Khả Năng Trả Lời & Điều Phối Tuyến (Precheck & Engine)

#### Task 5: Triển khai C5 - Answerability Precheck
- **Mô tả:** Xây dựng module kiểm tra sơ bộ khả năng trả lời trước khi chuyển sang Planner. Đối chiếu `evidence_requirements` (các bảng/cột bắt buộc) với `CapabilityMatrix` của business. Nếu phát hiện thiếu hẳn thông tin cốt lõi $\rightarrow$ kết luận `UNSUPPORTED` kèm lý do cụ thể; nếu mơ hồ $\rightarrow$ `UNKNOWN`; nếu đầy đủ $\rightarrow$ `SUPPORTED`.
- **Tiêu chí chấp nhận (Acceptance Criteria):**
  - [ ] Nhận diện chính xác trường hợp `UNSUPPORTED`: hỏi thông tin khách hàng khi business không có bảng/cột khách hàng; hỏi tồn kho lịch sử khi chỉ có snapshot hiện tại.
  - [ ] Không đánh nhầm `UNSUPPORTED` khi thông tin có thể suy luận qua nguồn thay thế (tránh false unanswerable).
  - [ ] Xuất ra đối tượng `EvidenceMissingProof` tương thích trực tiếp với Output Gate (B0.5).
- **Kiểm chứng (Verification):**
  - Lệnh test: `pytest tests/grounding/test_answerability.py`
- **Tệp liên quan:**
  - `src/datamate/grounding/answerability.py`
  - `tests/grounding/test_answerability.py`
- **Độ phức tạp:** S (2 files)

#### Task 6: Tích hợp QuestionGroundingEngine & Pipeline Adapter
- **Mô tả:** Xây dựng class điều phối trung tâm `QuestionGroundingEngine` kết nối tuần tự C1 $\rightarrow$ C2 $\rightarrow$ C3 $\rightarrow$ C4 $\rightarrow$ C5. Xây dựng adapter `GroundingToPlannerAdapter` để chuyển đổi `GroundedQuestion` thành input format sẵn sàng cho Planner (Component D / B03) và Output Gate (B05).
- **Tiêu chí chấp nhận (Acceptance Criteria):**
  - [ ] `engine.ground(question, context)` chạy thông suốt end-to-end, trả về `GroundedQuestion` hợp lệ.
  - [ ] Tốc độ thực thi trung bình < 100ms trên môi trường máy tính cục bộ.
  - [ ] Khi C5 trả về `UNSUPPORTED`, engine xuất cờ dừng sớm để bỏ qua gọi LLM.
- **Kiểm chứng (Verification):**
  - Lệnh test: `pytest tests/grounding/test_grounding_e2e.py`
- **Tệp liên quan:**
  - `src/datamate/grounding/engine.py`
  - `src/datamate/grounding/adapters.py`
  - `tests/grounding/test_grounding_e2e.py`
- **Độ phức tạp:** M (3 files)

---

### Checkpoint 3: Hoàn thiện Component C End-to-End
- [ ] Toàn bộ test suite của `grounding` chạy thành công: `pytest tests/grounding/` (100% passed).
- [ ] Kiểm thử e2e bao phủ cả 3 nhánh: câu hỏi thông thường (`SUPPORTED`), câu hỏi thiếu dữ liệu (`UNSUPPORTED`), câu hỏi thời gian tương đối phức tạp.

---

### Giai Đoạn 4: Tài Liệu Hướng Dẫn & Tích Hợp (Documentation & Integration Guide)

#### Task 7: Viết tài liệu đặc tả và hướng dẫn tích hợp cho team
- **Mô tả:** Soạn thảo tài liệu đặc tả kỹ thuật chi tiết tại `docs/code/GROUNDING_MODULE_SPEC.md` mô tả:
  1. Hướng dẫn cho người phụ trách B0.1 / B0.2: Cách map output của B0.1/B0.2 vào `BusinessContextProtocol`.
  2. Hướng dẫn cho người phụ trách B0.3 (Planner): Cách sử dụng `GroundedQuestion` để inject vào LLM prompt và Router fast-path.
  3. Bảng phân loại intent, time rules và metric patterns được hỗ trợ.
- **Tiêu chí chấp nhận (Acceptance Criteria):**
  - [ ] Tài liệu có ví dụ code cụ thể cho cả 2 phía Producer (B0.2) và Consumer (B0.3/B0.5).
  - [ ] Có checklist kiểm tra tương thích trước khi ghép nhánh git.
- **Tệp liên quan:**
  - `docs/code/GROUNDING_MODULE_SPEC.md`
- **Độ phức tạp:** S (1 file)

---

## 5. Ma Trận Quản Trị Rủi Ro (Risk Management)

| Rủi ro | Mức độ | Biện pháp giảm thiểu |
|---|---|---|
| **B0.1 / B0.2 thay đổi cấu trúc dữ liệu** | Trung bình | Đóng băng contract qua `BusinessContextProtocol`. Mọi thay đổi của B0.1/B0.2 chỉ cần cập nhật ở tầng Adapter, không làm sửa đổi core logic của Grounding. |
| **C3 chọn sót bảng/cột (Recall thấp)** | Cao | Áp dụng chiến lược Top-K ranking mở rộng (giữ fallback 3-5 bảng tiềm năng) kèm cơ chế score threshold. Không ép chỉ chọn duy nhất 1 bảng nếu độ tin cậy chưa tuyệt đối. |
| **C5 kết luận thiếu dữ liệu quá sớm (False UA)** | Nghiêm trọng | Chỉ kết luận `UNSUPPORTED` khi thiếu cột trực tiếp VÀ không có quan hệ thay thế trong `JoinGraph`. Nếu nghi ngờ, chuyển sang trạng thái `UNKNOWN` để Planner thử giải. |
| **Tên thực thể tiếng Việt bị gõ tắt hoặc biến thể** | Trung bình | Sử dụng từ điển chuẩn hóa alias (Unidecode + fuzzy matching + lookup tập distinct value được cache từ staging). |

---

## 6. Lộ Trình Triển Khai Đề Xuất (Timeline)

- **Ngày 1 (Tasks 1 - 2):** Khởi tạo package `src/datamate/grounding/`, data contracts, mock provider và C2 Temporal Resolver.
- **Ngày 2 (Tasks 3 - 4):** Xây dựng C1 Intent Parser, C3 Schema Grounder và C4 Value Grounder; vượt Checkpoint 2.
- **Ngày 3 (Tasks 5 - 6):** Xây dựng C5 Answerability Precheck, hoàn thiện `QuestionGroundingEngine` và test suite e2e.
- **Ngày 4 (Task 7):** Hoàn thiện tài liệu tích hợp `docs/code/GROUNDING_MODULE_SPEC.md`, sẵn sàng bàn giao cho người làm B0.1, B0.2 và B0.3.

