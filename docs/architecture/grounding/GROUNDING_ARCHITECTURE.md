# Kiến Trúc Chi Tiết Module Question Grounding (Component C)

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)  
**Nhóm thực hiện:** UIT Last Dance  
**Package triển khai:** [`src/datamate/grounding/`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding)  
**Bộ kiểm thử:** [`tests/grounding/`](file:///home/kiet97/uit-last-dance-aizalo26/tests/grounding)  
**Tài liệu mã nguồn từng file:** [`docs/code/grounding/README.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/grounding/README.md)

---

## 1. Bối Cảnh & Động Lực Thiết Kế (Context & Motivation)

Trong bài toán Vietnamese Tabular QA của cuộc thi **Zalo AI Challenge 2026**, hệ thống tiếp nhận câu hỏi tiếng Việt cùng ngày tham chiếu `as_of_date` trên kho dữ liệu đa dạng của từng doanh nghiệp (CSV, XLSX, SQLite, README, Rulebook, Calendar).

Qua đánh giá thực nghiệm trên tập Public Test (xem [`PUBLIC_TEST_BASELINE_B01_EVALUATION.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/PUBLIC_TEST_BASELINE_B01_EVALUATION.md)), kiến trúc Baseline B0 lộ rõ nút thắt cổ chai khi ép một LLM 9B duy nhất vừa phải đọc toàn bộ schema/rulebook thô, vừa phải tự tính ngày tháng, tự đoán tên thực thể và viết SQL trong một bước duy nhất:
1. **Ảo giác Schema & Join Fanout**: LLM chọn nhầm bảng hoặc join trực tiếp bảng `orders` với `order_items` (quan hệ 1-N) gây nhân bản doanh thu.
2. **Sai lệch thời gian**: LLM tính nhầm ngày tương đối ("tháng này", "7 ngày gần đây", "cùng kỳ năm ngoái", "dịp Tết") hoặc nhầm lẫn giữa ngày đặt đơn (`order_date`) và ngày thu tiền thực tế (`payment_date`).
3. **Không khớp giá trị thực tế (Value Mismatch)**: Người dùng hỏi `"ca tối"`, `"CK"`, `"Cà phê sữa (L)"` nhưng trong DB lưu `"Ca tối"`, `"Chuyển khoản"`, dẫn đến truy vấn trả về tập rỗng (`0`).
4. **Rủi ro bị trừ điểm Penalized Accuracy ($\text{PA} = \frac{\text{Đúng} - \text{Sai}}{N}$)**: Khi doanh nghiệp thiếu trường dữ liệu bắt buộc (ví dụ không lưu thông tin khách hàng hoặc giá vốn), LLM tự suy diễn dẫn đến câu trả lời sai (**-1 điểm**) hoặc báo `unanswerable` cảm tính (False Positive UA).

**Component C (Question Grounding)** được xây dựng để giải quyết triệt để 4 vấn đề trên trước khi gọi Agent Planner (Component D).

---

## 2. Sơ Đồ Kiến Trúc Tổng Thể Component C

```text
┌────────────────────────────────────────────────────────────────────────────┐
│                   INPUTS: QuestionRequest + BusinessContext                │
│  1. QuestionRequest: {question_id, business_id, question, as_of_date}      │
│  2. BusinessContextProtocol: Tables, Joins, Metrics, Rules, Capabilities,  │
│                              CalendarEvents, ValueAliases                  │
└─────────────────────────────────────┬──────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                  COMPONENT C: QUESTION GROUNDING ENGINE                    │
│                      (src/datamate/grounding/engine.py)                    │
│                                                                            │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ N0. VietnameseQuestionNormalizer (normalizer.py)                    │  │
│  │   - NFC + allowlist viết tắt: DT/SL/SP/KH, hnay/h.nay, thg này      │  │
│  │   - Bản chuẩn hóa được dùng thống nhất cho C1 → C5                  │  │
│  └──────────────────────────────────┬───────────────────────────────────┘  │
│                                     ▼                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ C1. QuestionIntentParser (parser.py)                                 │  │
│  │   ├─ Fast-Path: VietnameseRuleMatcher (rules_matcher.py) [< 2ms]     │  │
│  │   └─ Fallback:  StructuredLLMParser (llm_fallback.py) [Model 3B]     │  │
│  │   => Output: QuestionIntent (operation, metrics, filters, group_by,  │  │
│  │                    top_k, answer_type_hint, normalized_question?)    │  │
│  └───────────────┬──────────────────────────────────────┬───────────────┘  │
│                  │                                      │                  │
│                  ▼                                      ▼                  │
│  ┌───────────────────────────────┐      ┌───────────────────────────────┐  │
│  │ C2. QuestionTemporalResolver  │      │ C3. SchemaGrounder            │  │
│  │     (temporal.py)             │      │     (schema_grounder.py)      │  │
│  │  - Anchor: as_of_date         │      │  - Metric-first fact scoring  │  │
│  │  - Calendar/Tết lookup        │      │  - BFS shortest join path     │  │
│  │  - YoY / MoM comparison range │      │  - 1-to-N fanout detection    │  │
│  │  - DateRole inference         │      │  => Output: SelectedSchema    │  │
│  └───────────────┬───────────────┘      └───────────────┬───────────────┘  │
│                  │                                      │                  │
│                  └──────────────────┬───────────────────┘                  │
│                                     │                                      │
│                                     ▼                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ C4. ValueGrounder (value_grounder.py)                                │  │
│  │   - Exact alias dictionary lookup                                    │  │
│  │   - Unicode NFC + Accent-insensitive sample matching                 │  │
│  │   - Controlled substring matching for sized/topping items            │  │
│  │   => Output: tuple[MatchedValue, ...] & Grounded FilterConditions    │  │
│  └──────────────────────────────────┬───────────────────────────────────┘  │
│                                     │                                      │
│                                     ▼                                      │
│  ┌──────────────────────────────────────────────────────────────────────┐  │
│  │ C5. AnswerabilityPrechecker (answerability.py)                       │  │
│  │   - Build mandatory EvidenceRequirements                             │  │
│  │   - Verify against CapabilityMatrix + Full Catalog Fallback Check    │  │
│  │   - Check Primary Table Temporal Coverage                            │  │
│  │   => Output: CoverageStatus (SUPPORTED | UNSUPPORTED | UNKNOWN)      │  │
│  │              + MissingEvidenceProof (catalog_verified)               │  │
│  └──────────────────────────────────┬───────────────────────────────────┘  │
└─────────────────────────────────────┼──────────────────────────────────────┘
                                      │
                                      ▼
┌────────────────────────────────────────────────────────────────────────────┐
│                        OUTPUT: GroundedQuestion Contract                   │
├─────────────────────────────────────┬──────────────────────────────────────┤
│ Nếu coverage_status == UNSUPPORTED  │ Nếu SUPPORTED hoặc UNKNOWN           │
│                 │                   │                  │                   │
│                 ▼                   │                  ▼                   │
│   GroundingToPlannerAdapter         │    GroundingToPlannerAdapter         │
│   .to_b05_evidence_proof()          │    .format_grounded_hint_for_planner │
│                 │                   │                  │                   │
│                 ▼                   │                  ▼                   │
│      [B0.5 Decision Gate]           │     [Component D / B0.3 Planner]     │
│  Xuất thẳng "unanswerable" hợp lệ   │  Sinh SQL trên schema đã tinh gọn    │
│  (Tiết kiệm 100% GPU Planner/Exec)  │  (Model 9B Fine-tuned CoT + SQL)     │
└─────────────────────────────────────┴──────────────────────────────────────┘
```

---

## 3. Các Quyết Định Kiến Trúc Trọng Tâm (Architecture Decision Records - ADRs)

### ADR-007: Tách Biệt Phụ Thuộc Bằng `BusinessContextProtocol` & `MockBusinessContextProvider`
- **Trạng thái:** Accepted
- **Bối cảnh:** Các module chuẩn bị dữ liệu (B0.1 Data Foundation & B0.2 Semantic Knowledge) được phát triển song song. Nếu Component C import trực tiếp cấu trúc nội bộ của B0.1/B0.2, mọi thay đổi schema ở thượng nguồn sẽ làm gãy Component C.
- **Quyết định:**
  - Thiết lập `@runtime_checkable class BusinessContextProtocol` tại [`protocols.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/protocols.py).
  - Xây dựng [`B02ContextAdapter`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/adapters.py) để bọc đối tượng `BusinessContext` thực tế của B0.2 mà không cần sửa code B0.2.
  - Xây dựng [`MockBusinessContextProvider`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/mock_provider.py) cung cấp các kịch bản doanh nghiệp chuẩn (F&B có ca/topping, bán lẻ ẩn danh không lưu khách hàng) để kiểm thử độc lập 100%.

### ADR-008: Kiến Trúc C1 Hybrid (Rule-Based Fast-Path + 3B LLM Fallback)
- **Trạng thái:** Accepted
- **Bối cảnh:** Hơn 82% câu hỏi thuộc nhóm tính toán số học/tỷ lệ với cấu trúc ngữ pháp tiếng Việt đặc trưng.
- **Quyết định:**
  - Chạy [`VietnameseQuestionNormalizer`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/normalizer.py) trước C1; bản chuẩn hóa được truyền tiếp cho C2–C5, còn câu hỏi gốc được giữ trong `GroundedQuestion` để audit.
  - Tầng 1 ([`VietnameseRuleMatcher`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/rules_matcher.py)): Trích xuất xác định trong `< 2ms` các phép toán (`sum`, `count`, `count_distinct`, `avg`, `top_k`, `argmax`, `argmin`, `percent_change`, `ratio`, `existence`), chữ số tiếng Việt ("một" $\rightarrow$ 1, "năm" $\rightarrow$ 5), điều kiện `HAVING` ("ít nhất 3 đơn").
  - Bộ điều phối [`FallbackDecision`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/parser.py) kích hoạt fallback khi có ít nhất một bằng chứng thiếu: `confidence < fallback_threshold`, operation cần metric nhưng chưa có metric, nhiều metric cạnh tranh, metric ngoài registry, symbol/emoji hoặc viết tắt chưa giải nghĩa.
  - Tầng 2 ([`StructuredLLMParser`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/llm_fallback.py)): Gọi Qwen2.5-3B-Instruct qua backend vLLM dùng chung, sinh JSON có cấu trúc và có thể trả `normalized_question` cho C2–C5. Prompt được đếm token sau chat template, ưu tiên/cắt registry theo ngân sách 4096 và từ chối trước inference nếu không thể vừa context. Metric do LLM trả về phải thuộc MetricRegistry; intent xếp hạng/tổng hợp thiếu metric bị từ chối và suy giảm an toàn về kết quả rule-based.

### ADR-009: Kiến Trúc Hai Mô Hình Chuyên Biệt (Dual-Model: 3B Semantic Extractor + 9B SQL Planner)
- **Trạng thái:** Accepted
- **Bối cảnh:** Giới hạn tổng tham số suy luận của cuộc thi là $\le 15\text{B}$. Mô hình chính 9B (`Qwen3.5-9B`) sẽ được fine-tune chuyên sâu về chuỗi suy luận `<think>` và sinh Plan + DuckDB SQL. Nếu dùng mô hình 9B đã fine-tune SQL để trích xuất JSON thực thể ở C1 sẽ gây xung đột nhiệm vụ (Task Interference) và tốn latency.
- **Quyết định:**
  - Sử dụng mô hình **3B (`Qwen/Qwen2.5-3B-Instruct`)** làm **Semantic Extractor** dùng chung cho cả việc trích xuất quy tắc từ Rulebook (Pha B2 offline) và trích xuất Intent câu hỏi khó (Pha C1 runtime).
  - Giữ mô hình **9B** chuyên trách hoàn toàn cho **Agent Planner (Pha D)** và **Self-Repair (Pha F)**.
  - Tổng tham số: $3.09\text{B} + 9\text{B} = \mathbf{12.09\text{B} \le 15\text{B}}$.

### ADR-010: Giải Quyết Thời Gian Xác Định (C2 Deterministic Temporal Resolver)
- **Trạng thái:** Accepted
- **Quyết định:** Mọi biểu thức thời gian tương đối ("hôm nay", "hôm qua", "tháng này", "tháng trước", "quý này", "7 ngày gần đây", "cùng kỳ năm ngoái", "dịp Tết") được tính toán 100% bằng thuật toán lịch trong [`temporal.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/temporal.py) dựa trên câu hỏi đã chuẩn hóa, `as_of_date` và `CalendarEventSpec`, kèm suy luận vai trò cột ngày (`order_date` vs `payment_date` vs `stock_event_date`).

### ADR-011: Bảo Vệ Điểm PA Bằng Answerability Precheck Có Kiểm Chứng Toàn Cục (C5)
- **Trạng thái:** Accepted
- **Quyết định:** [`AnswerabilityPrechecker`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/answerability.py) chỉ kết luận `CoverageStatus.UNSUPPORTED` khi:
  1. `CapabilityMatrix` báo `"unsupported"` cho một năng lực bắt buộc (`is_mandatory=True`), **VÀ**
  2. Hàm `_has_fallback_column_in_catalog()` đã quét qua toàn bộ các bảng/cột trong `SchemaCatalog` (`checked_all_sources=True`) mà vẫn không tìm thấy cột thay thế.
  Khi đó, hệ thống xuất `MissingEvidenceProof` chuyển đổi trực tiếp sang `EvidenceProof(source_kind="catalog_verified")` của B0.5 để dừng sớm và trả về `unanswerable` an toàn tuyệt đối.

---

## 4. Phân Tích Chi Tiết 5 Module Con (C1 → C5)

| Module | Class chính | File triển khai | Input | Output | Thời gian chạy |
|---|---|---|---|---|---|
| **N0** | `VietnameseQuestionNormalizer` | `normalizer.py` | Câu hỏi gốc | Câu hỏi NFC đã mở rộng viết tắt | `< 1ms` |
| **C1** | `QuestionIntentParser` | `parser.py`, `rules_matcher.py`, `llm_fallback.py` | Câu hỏi + `as_of_date` + `BusinessContextProtocol` | `QuestionIntent` | `< 2ms` (Fast-path) |
| **C2** | `QuestionTemporalResolver` | `temporal.py` | Câu hỏi + `as_of_date` + `DateRole` + Calendar | `tuple[ResolvedTimeRange, ...]` | `< 1ms` |
| **C3** | `SchemaGrounder` | `schema_grounder.py` | Câu hỏi + `QuestionIntent` + `BusinessContextProtocol` | `SelectedSchema` | `< 5ms` |
| **C4** | `ValueGrounder` | `value_grounder.py` | Câu hỏi + `QuestionIntent` + `SelectedSchema` | `tuple[MatchedValue, ...]`, `updated_filters` | `< 5ms` |
| **C5** | `AnswerabilityPrechecker` | `answerability.py` | `QuestionIntent` + `ResolvedTimeRange` + `SelectedSchema` | `CoverageStatus`, `MissingEvidenceProof` | `< 2ms` |

---

## 5. Ví Dụ Minh Họa End-to-End Trích Từ Bộ Đề Thi

### Ví dụ 1: Tiền mặt thực thu theo ca (`dev_003`)
* **Câu hỏi**: *"Trong tháng này, ca tối thu được bao nhiêu tiền mặt?"* với `as_of_date = 2026-08-27`.
* **C1 Intent Parser**: Xác định `operation = SUM`, `target_metrics = ("cash_collected",)`, `entities = ("ca tối", "tiền mặt")`, `answer_type_hint = NUMBER`.
* **C2 Temporal Resolver**: Thấy metric là `cash_collected` $\rightarrow$ gán `DateRole = PAYMENT_DATE`. Phân giải `"tháng này"` từ `2026-08-01` đến `2026-08-27` (inclusive).
* **C3 Schema Grounder**: Xếp hạng bảng theo `MetricRegistry` $\rightarrow$ chọn `primary_table = "shift_payments"` (+0.85 điểm). Lấy các cột `[collected_amount, payment_date, shift_name, payment_method]`.
* **C4 Value Grounder**: Tra cứu từ điển alias $\rightarrow$ map `"ca tối"` vào cột `shift_name = 'Ca tối'`, map `"tiền mặt"` vào cột `payment_method = 'Tiền mặt'`.
* **C5 Precheck**: Thấy doanh nghiệp hỗ trợ `payments` $\rightarrow$ `CoverageStatus.SUPPORTED`.
* **Prompt sinh cho Planner**:
  ```markdown
  SELECT SUM(collected_amount) FROM shift_payments
  WHERE payment_date BETWEEN DATE '2026-08-01' AND DATE '2026-08-27'
    AND shift_name = 'Ca tối' AND payment_method = 'Tiền mặt';
  ```
  *(Tuyệt đối không bị nhầm sang doanh thu theo ngày đặt đơn hay bị nhân dòng order_items).*

---

### Ví dụ 2: Top sản phẩm được ưa chuộng (`dev_002`)
* **Câu hỏi**: *"Trong tháng này, năm sản phẩm được ưa chuộng nhất là gì?"* với `as_of_date = 2026-08-27`.
* **C1 Intent Parser**: Nhận diện `"năm"` $\rightarrow$ `top_k = 5`. Nhận diện `"được ưa chuộng nhất"` $\rightarrow$ `operation = TOP_K`, `target_metrics = ("distinct_product_orders",)`, `group_by = ("product",)`, `answer_type_hint = LIST`.
* **C2 Temporal Resolver**: Phân giải `2026-08-01` đến `2026-08-27` (theo `DateRole.ORDER_DATE`).
* **C3 Schema Grounder**: Chọn `primary_table = "order_items"` chứa cột `product_name` và `order_id`.
* **C5 Precheck**: Thấy doanh nghiệp hỗ trợ `sales_by_product` $\rightarrow$ `CoverageStatus.SUPPORTED`.
* **Chỉ dẫn cho Planner**: Planner chọn `COUNT(DISTINCT order_id)` thay vì `SUM(quantity)`, đồng thời thêm `LIMIT 5` và sắp xếp `COUNT(...) DESC, product_name ASC` để bảo đảm tính tất định.

---

## 6. Báo Cáo Kiểm Chứng Thực Nghiệm & Đo Đạc Hiệu Năng

Bộ test suite độc lập của Grounding tại [`tests/grounding/`](file:///home/kiet97/uit-last-dance-aizalo26/tests/grounding) đã hoàn thành và vượt qua 100%:
* **Số lượng test case**: **54 bài test chuyên sâu** bao phủ toàn bộ các góc biên:
  * `test_contracts.py` (6 passed): Thẩm định tính bất biến, serialization và mock provider.
  * `test_temporal.py` (7 passed): Phân giải ngày âm lịch Tết 2025/2026, 7 ngày gần đây, mốc tương đối, kỳ so sánh YoY.
  * `test_parser.py` (22 passed): Fast-path, evidence-based fallback, token budget, LLM normalization, validation và suy giảm an toàn.
  * `test_normalizer.py` (5 passed): Viết tắt compact/dotted, whole-token safety, giới hạn kích thước và truyền câu chuẩn hóa qua C1–C5.
  * `test_vllm_fallback.py` (2 passed): Wiring cấu hình Qwen 3B qua backend vLLM dùng chung mà không cần GPU trong unit test.
  * `test_schema_value_grounder.py` (4 passed): Chấm điểm Fact table, tìm đường BFS và khử dấu tiếng Việt.
  * `test_answerability.py` (4 passed): Kiểm chứng `unsupported` và cơ chế chống False UA.
  * `test_grounding_e2e.py` (4 passed): Kiểm tra toàn trình, đo đạc latency, và tương thích `B02ContextAdapter`.
* **Đo đạc độ trễ (Latency)**: Toàn bộ quy trình C1..C5 chỉ tốn trung bình **12.4ms** trên CPU (ngân sách cam kết < 100ms).
* **Tính tất định (Determinism)**: Chạy lặp lại 2 lần liên tiếp trên cùng câu hỏi cho ra kết quả `g1.to_dict() == g2.to_dict()` đạt 100%.

---

## 7. Hướng Dẫn Cắm Nối Tích Hợp Toàn Tuyến (Integration Guide)

```python
from datamate.grounding import (
    B02ContextAdapter,
    GroundingToPlannerAdapter,
    QuestionGroundingEngine,
    QuestionRequest,
)

# 1. Khởi tạo Engine và nạp Qwen 3B/vLLM một lần duy nhất.
# Dùng QuestionGroundingEngine() nếu chủ động chạy chế độ không có LLM fallback.
grounding_engine = QuestionGroundingEngine.from_qwen3b_vllm(
    "configs/qwen2_5_3b_grounding.toml"
)

# 2. Bọc BusinessContext từ B0.2 qua Adapter
adapted_ctx = B02ContextAdapter(b02_business_context)

# 3. Thực thi Grounding cho câu hỏi
req = QuestionRequest(
    question_id=row["id"],
    business_id=row["business_id"],
    question=row["question"],
    as_of_date=row["as_of_date"],
)
grounded = grounding_engine.ground(req, adapted_ctx)

# 4. Nhánh rẽ quyết định sớm (Early Exit cho Unanswerable)
if grounded.is_directly_unanswerable:
    evidence_proof = GroundingToPlannerAdapter.to_b05_evidence_proof(grounded)
    # Chuyển thẳng xuống B0.5 evaluate_gate() với status="not_executed"
    # Tiết kiệm 100% chi phí gọi LLM Planner và chạy DuckDB!
else:
    # Sinh khối gợi ý ngữ nghĩa đã tinh gọn cho B0.3 Planner (Model 9B)
    planner_hint = GroundingToPlannerAdapter.format_grounded_hint_for_planner(grounded)
```
