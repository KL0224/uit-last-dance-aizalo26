# Kế hoạch cải tiến kiến trúc baseline B0.1 → B0.5 sau Public Test

**Ngày phân tích:** 2026-11-09

**Trạng thái:** Đề xuất kiến trúc (`Proposed`)

**Báo cáo đầu vào:** [PUBLIC_TEST_BASELINE_B01_EVALUATION.md](./PUBLIC_TEST_BASELINE_B01_EVALUATION.md)

**Phạm vi:** kiến trúc và luồng chạy hiện tại trong `src/datamate/b0`, từ B0.1 đến B0.5
**Mục tiêu:** tăng điểm kỳ vọng theo luật `đúng = +1`, `sai = -1`, `abstain = 0`; ưu tiên precision trước coverage

## 1. Kết luận điều hành

Baseline hiện tại không thiếu một bản vá đơn lẻ. Khoảng trống cốt lõi là hệ thống chưa có một **kế hoạch ngữ nghĩa có cấu trúc** xuyên suốt B0.1 → B0.5:

- B0.1 mô tả tốt schema vật lý, nhưng chưa chứng minh đầy đủ grain nghiệp vụ, cấp của measure và chiến lược join an toàn.
- B0.2 đã có `RuleResolver` và `RuleTemplateBinder`, nhưng pipeline runtime chưa dùng chúng để tạo metric plan; phần lớn rule vẫn là văn bản đưa thẳng vào prompt.
- B0.3 phải đồng thời đoán intent, metric, grain, join, thời gian, khả năng trả lời, kiểu output và SQL trong một lượt sinh tự do.
- B0.4 chứng minh SQL an toàn và chạy được, nhưng chưa chứng minh SQL đúng câu hỏi.
- B0.5 chủ yếu kiểm tra shape/type, nên một truy vấn sai metric nhưng chạy thành công vẫn được phát hành là `VALID_RESULT`.

Điều này khớp trực tiếp với số liệu Public Test:

- 391/481 câu sai có đúng kiểu output nhưng sai giá trị/nội dung.
- 606 câu `VALID_RESULT` chỉ có 208 câu đúng, precision 34,3%.
- 352 lỗi là `number/percent` đúng type nhưng sai số; phần lớn không thể sửa bằng formatter.
- 166 câu bị `GENERATION_INVALID`.
- 47 câu được gắn `unanswerable`, nhưng có 26 false positive.
- 38 output `table` đều sai, trong đó phần lớn là lỗi suy kiểu từ SQL có CTE.

Vì vậy, thay đổi có ROI cao nhất là:

1. thêm `QuestionPlan`/`MetricPlan` có cấu trúc trước bước sinh SQL;
2. thêm semantic SQL validator ở B0.4 trước khi thực thi;
3. biến B0.5 thành risk gate dựa trên bằng chứng, không phải chỉ output gate;
4. khóa integrity của submission;
5. sau đó mới tối ưu model và coverage.

## 2. Kiến trúc mục tiêu

```text
[Câu hỏi + as_of_date]
          │
          ├───────────────────────────────┐
          ▼                               │
[B0.1 Semantic Data Catalog]              │
          │                               │
          │ grain, roles, joins, coverage │
          ▼                               ▼
[B0.2 Metric & Capability Catalog] ◀──────┘
          │
          │ resolved rules + required evidence
          ▼
[B0.3 Question Planner]
          │
          │ QuestionPlan
          ▼
[B0.3 SQL Generator]
          │
          │ SQLCandidate
          ▼
[B0.4 Semantic Validator] ◀── B0.1 catalog
          ▲                  ◀── B0.2 metric definitions
          └──────────────────◀── B0.3 QuestionPlan
          │
          ├── SemanticProof ───────────────────────────┐
          │                                            │
          │ validated SQL                              │
          ▼                                            │
[B0.4 Read-only Executor]                              │
          │                                            │
          │ ExecutionProof                             │
          ▼                                            ▼
[B0.5 Risk & Output Gate] ◀────────────────────────────┘
          │
          │ answer / unanswerable / abstain
          ▼
[Canonical Submission Writer]
```

Nguyên tắc quan trọng nhất là **B0.5 không được tự đoán lại ngữ nghĩa**. Mỗi tầng phải bổ sung bằng chứng vào cùng một kế hoạch, và tầng sau chỉ được kiểm tra hoặc làm giàu kế hoạch đó.

### 2.1. Hợp đồng xuyên tầng đề xuất

| Hợp đồng | Tầng sở hữu | Nội dung tối thiểu |
|---|---|---|
| `SemanticDataCatalog` | B0.1 | table grain, entity key, semantic role của cột, measure grain, additivity, join cardinality, fan-out risk, date coverage, provenance |
| `MetricDefinition` | B0.2 | metric, công thức, grain đầu vào/đầu ra, status policy, time policy, unit policy, required capabilities, tie-break |
| `QuestionPlan` | B0.3 planner | intent, answer type, entity grain, metric, filters, time window, numerator/denominator, join path, pre-aggregation, output shape |
| `SQLCandidate` | B0.3 generator | SQL, `plan_id`, bảng/cột dùng, assumptions đã được phép, generation telemetry |
| `SemanticProof` | B0.4 validator | các invariant đạt/trượt, AST facts, join/fan-out proof, plan conformance |
| `ExecutionProof` | B0.4 executor | status, shape, row count, result diagnostics, elapsed time, truncation |
| `GateDecision` | B0.5 | decision, reason code, calibrated risk, evidence dùng để answer/unanswerable/abstain |

## 3. Phân bổ nguyên nhân lỗi theo tầng

| Vấn đề từ Public Test | Chủ sở hữu chính | Tầng hỗ trợ | Vì sao |
|---|---|---|---|
| `COUNT(*)` dòng hàng thay vì distinct đơn | B0.1 + B0.2 | B0.3/B0.4 | cần biết grain và định nghĩa `order_count`, sau đó validator đối chiếu AST |
| Join 1-n làm nhân bản measure | B0.1 | B0.3/B0.4 | catalog phải mô tả cardinality/fan-out; planner pre-aggregate; validator chặn |
| Hỏi số đơn nhưng SQL tính doanh thu | B0.3 planner | B0.2/B0.4 | intent/metric phải được khóa trước generation và kiểm chứng lại |
| Percent chỉ có tổng, thiếu tử/mẫu | B0.2 + B0.3 | B0.4 | metric contract cần numerator/denominator; AST phải có phép chia |
| Tồn kho suy từ lượng nhập dương | B0.2 | B0.1/B0.4 | phải có inventory flow contract và các capability bắt buộc |
| Sai kỳ thời gian/trạng thái/đơn vị | B0.2 | B0.1/B0.3/B0.4 | policy phải có cấu trúc, không chỉ nằm trong prose prompt |
| CTE bị suy thành `table` | B0.3 parser | B0.5 | dùng outer-select AST; B0.5 không tự cứu kiểu tùy ý |
| `GENERATION_INVALID` | B0.3 | pipeline | constrained output, non-thinking, telemetry và retry theo loại lỗi |
| `unanswerable` giả | B0.2 capability | B0.3/B0.5 | không nhận tên field tự do từ LLM làm bằng chứng âm |
| Submission lệch gate/log | B0.5 writer | pipeline/CI | canonical export, validation toàn tập và checksum |

## 4. B0.1 — Data preparation, schema và join catalog

### 4.1. Điểm tốt hiện tại

- Chuẩn hóa dữ liệu về DuckDB, lưu provenance và profile toàn bảng là nền tảng đúng.
- `JoinEdge` đã có `cardinality`, `status`, `confidence`, `evidence` và `fanout_warning` (`src/datamate/b0/b01/contracts.py:50`).
- Schema builder phân biệt structural identity với business grain và giữ join suy diễn ở trạng thái `uncertain` (`schema_catalog.py:41-54`, `schema_catalog.py:171-200`).
- Full-table profiler đã thu thập null count, cardinality, min/max và sample có tính lặp lại.

### 4.2. Khoảng trống cần sửa

`ColumnMetadata` hiện chỉ có type/null/cardinality/provenance; `TableMetadata.grain` thường chỉ là “row keyed by (...)”. Cấu trúc này chưa trả lời được các câu hỏi quan trọng:

- bảng là order header, order line, payment, debt ledger hay inventory lot;
- `tong_tien` là measure cấp đơn hay cấp dòng;
- một giá trị có bị lặp theo `order_id` hay không;
- measure có cộng được qua thời gian/entity không;
- join nào cần pre-aggregate trước;
- khoảng ngày có thực sự đủ dữ liệu từng tháng hay chỉ có min/max.

Ngoài ra có hai đường làm yếu catalog hiện tại:

1. B0.3 đưa mọi join có `status != invalid` vào prompt, bao gồm join `uncertain` (`prompt.py:229-240`).
2. Khi bundle thiếu join graph, `B0Pipeline.load_context()` coi chỉ cần có overlap là một join `validated`, gán cứng `many_to_one` mà không kiểm tra uniqueness/cardinality (`pipeline.py:94-125`). Điều này đi ngược sự thận trọng của B0.1 và có thể tạo đúng loại fan-out đã thấy ở `q_10831a6f3a2b`.

Prompt còn suy “mọi tháng trong các năm trước năm kết thúc đều đầy đủ” chỉ từ `observed_min/observed_max` (`prompt.py:242-260`). Min/max không chứng minh coverage liên tục.

### 4.3. Cải tiến đề xuất

#### P0 — Không để metadata chưa được chứng minh đi xuống downstream

- Chỉ cho B0.3/B0.4 dùng join `validated`; join `uncertain` chỉ được hiển thị như candidate kèm cảnh báo, không được tự động lập kế hoạch.
- Bỏ fallback “có overlap ⇒ validated” trong `pipeline.load_context()`. Nếu cần fallback, phải gọi đúng profiler B0.1 và giữ status `uncertain` cho tới khi kiểm tra uniqueness, coverage và key pair đầy đủ.
- Thay tuyên bố đủ tháng bằng `DateCoverage` thực tế: danh sách ngày/tháng có dữ liệu, first/last date, số ngày quan sát, gap và freshness.
- Không cho `grain="row keyed by (...)"` được hiểu là business grain. Thêm `grain_status = structural | business_validated | unknown`.

#### P1 — Mở rộng thành semantic data catalog

Thêm các field có cấu trúc:

```text
TableSemantic
  entity_type: order_header | order_line | product | customer | payment | debt | inventory_lot | ...
  business_grain: one row per <entity/key>
  grain_keys: [...]
  grain_status: validated | inferred | unknown

ColumnSemantic
  semantic_role: order_id | product_id | order_date | status | quantity | line_amount | order_total | ...
  value_level: line | order | product | customer | lot | snapshot
  additivity: additive | semi_additive | non_additive
  repeated_within: [order_id]
  unit_dimension: money | item | base_unit | selling_unit | percent | date
  confidence + evidence
```

Các role hiện tại như `money`, `quantity`, `identifier` trong `normalization.py` vẫn hữu ích cho parse vật lý, nhưng không đủ để quyết định metric. Cần tách rõ:

- `physical_role`: phục vụ parse/type normalization;
- `semantic_role`: phục vụ lập kế hoạch nghiệp vụ.

#### P1 — Thêm profiling chuyên phát hiện sai grain

Với từng measure/key candidate, tính offline:

- tỷ lệ `COUNT(*) / COUNT(DISTINCT entity_key)`;
- tỷ lệ một measure giữ nguyên trong cùng entity;
- tổng trực tiếp so với tổng sau deduplicate theo entity;
- fan-out multiplier của từng join path;
- orphan rate hai chiều;
- uniqueness theo full key và composite key.

Nếu `order_total` lặp trên nhiều order lines, catalog phải ghi `repeated_within=[order_id]`, `additivity=non_additive_across_lines`. Đây là bằng chứng để planner không `SUM(order_total)` trực tiếp như lỗi `q_522627a83f38`.

#### P2 — Tạo lớp alias/ontology có provenance

- Map header gốc tiếng Việt sang semantic role bằng rule được review, không chỉ regex tên cột.
- Cho phép override theo business và lưu nguồn (`rulebook`, data dictionary, manual review).
- Không suy category nghiệp vụ từ product name trừ khi rulebook khai báo rõ một derived attribute và pattern hợp lệ.

### 4.4. Tiêu chí nghiệm thu B0.1

- 100% bảng được dùng trong validation set có `grain_status` rõ ràng; bảng `unknown` không được aggregate tự do.
- 100% measure dùng trong metric template có `semantic_role`, `value_level`, `additivity` và evidence.
- Không có join `uncertain` nào xuất hiện như join được phép trong `QuestionPlan`.
- Regression phải phát hiện/chặn được bốn mẫu lỗi: `q_585664a97754`, `q_10831a6f3a2b`, `q_522627a83f38`, `q_0ca19cd317cb`.

## 5. B0.2 — Business context, rule resolution và metric catalog

### 5.1. Điểm tốt hiện tại

- `BusinessRule` có scope, precedence, status, provenance và expression.
- `RuleResolver` xử lý precedence và block conflict thay vì âm thầm fallback (`rule_resolver.py:27-90`).
- `RuleTemplateBinder` yêu cầu evidence rõ ràng trước khi bind công thức (`rule_templates.py:49-108`).
- Ba template hiện có (`revenue`, `gross_profit`, `sold_qty_base`) đã thể hiện đúng hướng: formula được review, role binding rõ và không nhận SQL tùy ý.

### 5.2. Khoảng trống cần sửa

Các thành phần tốt trên chưa trở thành đường chạy chính:

- `B0Pipeline` không gọi `RuleResolver` hay `RuleTemplateBinder`; nó nạp toàn bộ context rồi chuyển thẳng sang B0.3.
- `prompt._select_rules()` tự triển khai một bộ lọc đơn giản khác với resolver, nên conflict/blocked topic không được bảo toàn đầy đủ.
- Template binder mới hỗ trợ ba metric, trong khi Public Test tập trung vào order count, percent/share/growth, average, top-N, inventory, debt và time comparison.
- `answerability_constraints` tồn tại trong contract nhưng chưa có capability taxonomy đủ mạnh.
- Nhiều dòng Markdown được giữ như descriptive rule; model phải tự biến prose thành logic mỗi câu.

### 5.3. Cải tiến đề xuất

#### P0 — Đưa rule resolution vào pipeline thật

Trước khi gọi model:

1. phân loại question thành các topic/intent candidate;
2. gọi `RuleResolver` với `business_id`, `industry`, `question_id`;
3. nếu topic quan trọng bị conflict/blocked, không được truyền rule thấp hơn như thể hợp lệ;
4. chỉ retrieval các rule liên quan, không đưa toàn bộ rulebook vào prompt;
5. log `selected_rule_ids`, `blocked_topics` và provenance.

#### P1 — Xây `MetricDefinition` thay cho prose-only rules

Mỗi metric cần khai báo tối thiểu:

```yaml
metric_id: order_count
input_grain: order
output_kind: number
aggregation: count_distinct
entity_key_role: order_id
time_role: order_date
status_policy: valid_orders
required_capabilities: [order_id, order_date, order_status]
forbidden_shortcuts: [count_order_lines, sum_revenue]
```

Ưu tiên template theo tần suất và thiệt hại điểm:

1. `order_count`, `revenue`, `average_revenue_per_order`;
2. `share_percent`, `growth_percent`, `cancellation_rate`;
3. `top_n_product`, `top_n_customer` với tie-break xác định;
4. `inventory_balance`, `expiring_inventory` theo lot;
5. debt outstanding, due/not-due, installments, collection;
6. unit conversion về base unit;
7. relative time window và period comparison.

Mỗi template phải có grain, status policy, time policy, unit policy, numerator/denominator và invariant kiểm chứng AST.

#### P1 — Tạo capability graph cho answerability

Không dùng một tên field do model tự viết như `orders_in_T4_2026` làm capability. Capability phải thuộc taxonomy đóng, ví dụ:

- `orders.count_by_order_date` cần `order_id + order_date`;
- `revenue.by_product_group` cần `revenue metric + product_id + explicit product_group`;
- `inventory.on_hand_by_lot` cần opening/import/export/sale/return flow hoặc snapshot on-hand;
- `debt.outstanding_due_date` cần debt amount + payment/collection + due date.

Capability resolver phải trả một trong bốn trạng thái:

- `supported`: đủ field/rule/join đã xác minh;
- `unsupported`: thiếu concept thuộc taxonomy và đã kiểm tra mọi nguồn;
- `ambiguous`: có nhiều mapping/rule xung đột;
- `unknown`: evidence chưa đủ.

Chỉ `unsupported` với proof đầy đủ mới được phép ra `unanswerable`. `ambiguous/unknown` phải `abstain` hoặc đi review/retry.

#### P2 — Registry được version hóa

- Version metric/rule bindings theo business bundle.
- Lưu fingerprint của schema và rulebook để invalid cache khi dữ liệu đổi.
- Có test fixture độc lập cho mỗi metric template; không nhúng answer của Public Test vào production rule.

### 5.4. Tiêu chí nghiệm thu B0.2

- Pipeline runtime dùng đúng `RuleResolver`; không còn bộ chọn rule song song trong prompt.
- ≥90% họ intent trong validation suite map được vào một `MetricDefinition` hoặc được đánh dấu rõ `unknown`.
- Mọi percent template có numerator, denominator, zero policy và scale (`fraction`/`percent_points`).
- `unanswerable` precision ≥90%, recall ≥80% trên tập validation đóng băng.
- `q_008fdebb6ec9` phải `unsupported` vì thiếu `product_group`, không được tự suy nhóm trà từ tên nếu rulebook không cho phép.

## 6. B0.3 — Question planning, generation và parser

### 6.1. Điểm tốt hiện tại

- Generator, model backend và parser đã được tách module.
- vLLM backend đã thu thập `input_tokens`, `output_tokens`, `finish_reason` (`types.py:88-100`, `vllm_model.py:103-117`).
- Parser có fallback và trích bảng từ AST, phù hợp cho baseline ban đầu.

### 6.2. Khoảng trống cần sửa

B0.3 hiện gánh quá nhiều quyết định trong một prompt lớn. Một số rule prompt còn đưa ra giả định không được catalog chứng minh:

- bắt buộc suy size từ tên sản phẩm nếu thiếu cột size (`prompt.py:22-23`);
- khẳng định dữ liệu đủ mọi tháng trong năm nằm trong min/max (`prompt.py:27`, `prompt.py:242-260`);
- cho model tự xác định answerability, metric và SQL cùng lúc.

Cấu hình bật thinking, cho 8.192 output token và không có stop sequence (`configs/qwen3_5_9b.toml:11-22`). Trong khi backend có telemetry, `Text2SQLGenerator` chỉ chuyển `gen_result.text` sang parser nên token counts/finish reason không đi vào audit (`generator.py:30-47`).

Parser còn dùng regex để lấy projection trước `FROM` đầu tiên; với CTE nó có thể lấy projection bên trong CTE thay vì outer select. Đây là nguyên nhân trực tiếp của nhóm 38 output `table` sai.

### 6.3. Cải tiến đề xuất

#### P0 — Sửa deterministic contract trước

- Dùng `sqlglot` lấy outer query và outer projections; xóa `_extract_projection()` dựa trên regex.
- Không suy answer type lần hai khi chuyển B0.3 → B0.5. `QuestionPlan.answer_type` là nguồn chuẩn; SQL chỉ được validator kiểm tra có phù hợp hay không.
- Từ chối answerable contract thiếu SQL, SQL có placeholder `...`, bảng ngoài catalog hoặc `tables_used` không khớp AST.
- Parser strict trước, recovery chỉ dùng cho diagnostic/retry; không phát hành một contract được “cứu” mơ hồ.
- Truyền `finish_reason`, input/output tokens, raw response hash và raw response lỗi vào audit.

#### P0 — A/B test structured generation không thinking

Baseline kế tiếp nên thử:

- `enable_thinking=false`;
- output token budget ngắn hơn;
- JSON schema/constrained decoding nếu phiên bản vLLM hỗ trợ;
- stop condition sau JSON hoàn chỉnh;
- temperature 0 như hiện tại.

Không mặc định khẳng định non-thinking luôn tốt hơn; quyết định bằng benchmark gồm contract-valid rate, semantic accuracy, latency và score. Tuy nhiên với 166 `GENERATION_INVALID`, đây là thí nghiệm P0.

#### P1 — Tách planner khỏi SQL generator

Planner sinh `QuestionPlan` nhỏ, không sinh SQL ngay:

```yaml
intent: aggregate
metric_id: order_count
answer_type: number
entity_grain: order
time_window:
  role: order_date
  start: 2026-04-01
  end_exclusive: 2026-05-01
filters:
  status_policy: cancelled_orders
aggregation:
  op: count_distinct
  key_role: order_id
join_plan: []
required_capabilities: [orders.count_by_order_date, orders.cancelled_status]
confidence: 0.92
```

Sau đó SQL generator chỉ bind plan vào schema/metric đã được chọn. Với metric phổ biến, ưu tiên deterministic renderer/template; LLM dùng cho mapping hoặc long-tail, không tự phát minh công thức.

#### P1 — Context retrieval theo plan

Prompt SQL chỉ nên nhận:

- bảng/cột liên quan;
- validated join path;
- selected metric definitions/rules;
- categorical values cần cho filter;
- date coverage liên quan;
- output contract.

Không đưa toàn bộ schema/rulebook nếu không cần. Context ngắn giúp giảm generation invalid và giảm khả năng model chọn nhầm cột cùng nghĩa bề mặt.

#### P1 — Retry theo loại lỗi

- `contract_invalid`: retry bằng prompt JSON-only ngắn, không mang SQL cũ dài.
- `semantic_plan_invalid`: lập lại plan hoặc abstain; không sửa cú pháp SQL.
- `schema/binder error`: sửa SQL với đúng schema subset.
- `semantic_sql_mismatch`: đưa invariant bị vi phạm, ví dụ “metric=order_count yêu cầu COUNT DISTINCT order_id”.
- timeout/resource: deterministic simplification hoặc abstain; không coi mọi lỗi là cùng một repair task.

#### P2 — Nhiều candidate có kiểm soát

Chỉ với plan rủi ro cao, có thể sinh 2–3 SQL candidates rồi dùng B0.4 validator chọn. Không nên majority vote trên kết quả số nếu các candidate cùng dựa vào một mapping sai.

### 6.4. Tiêu chí nghiệm thu B0.3

- `GENERATION_INVALID < 2%` và `RETRY_EXHAUSTED < 2%` trên validation suite.
- 100% output tuân JSON schema trước khi đi B0.4.
- 0 lỗi suy type do CTE trong regression suite; 38 trường hợp cũ phải được map đúng outer shape.
- 100% generation trace có `finish_reason`, input/output tokens, prompt/model version và raw-response reference.
- `q_37a4aca072a6` và `q_c76ae61c6092` phải lập plan `order_count`, không phải `revenue`.
- `q_c0d31d97c743` phải lập plan có numerator/denominator và answer type `percent`.

## 7. B0.4 — Semantic validation và execution

### 7.1. Điểm tốt hiện tại

- Có AST safety check, chặn DDL/DML, multi-statement và external file access.
- DuckDB chạy read-only với memory/thread/timeout/max-row guard.
- Error taxonomy và bounded retry đã có nền tảng sử dụng được.

### 7.2. Khoảng trống cần sửa

`validate_read_only_sql()` chỉ trả SQL sạch nếu query an toàn (`sanitizer.py:127-197`). `execute_query()` sau đó chạy trực tiếp query (`engine.py:85-188`). Không có bước đối chiếu SQL với câu hỏi, metric plan, grain hay join graph.

Vì thế các SQL sau đều hợp lệ với B0.4 hiện tại:

- `SUM(tong_tien)` cho câu hỏi đếm đơn;
- `COUNT(*)` trên order line;
- join 1-n rồi cộng/count mà không pre-aggregate;
- percent không có phép chia;
- tồn kho dựa trên `quantity_imported > 0`.

### 7.3. Cải tiến đề xuất

#### P0 — Thêm `SemanticQueryValidator` trước executor

Validator nhận `QuestionPlan + SQL AST + SemanticDataCatalog + MetricDefinition` và kiểm tra:

1. **Catalog conformance**: mọi table/column tồn tại; không dùng uncertain join.
2. **Join conformance**: đủ toàn bộ composite key pairs; đúng hướng/cardinality; không Cartesian join.
3. **Grain safety**: measure cấp order không bị sum qua order lines; join fan-out phải pre-aggregate hoặc deduplicate có căn cứ.
4. **Metric conformance**:
   - order count → `COUNT(DISTINCT order_key)` hoặc relation đã group đúng grain;
   - share/rate/growth → có numerator, denominator, division, zero policy và đúng thứ tự kỳ;
   - average per order → numerator/denominator đúng grain;
   - inventory → đúng flow/snapshot được metric definition cho phép.
5. **Policy conformance**: time range, status filter, return/cancel policy, unit conversion khớp plan.
6. **Output conformance**: outer projection, số cột, ordering, `LIMIT N`, tie-break và answer type.

Kết quả không chỉ là pass/fail mà phải có danh sách machine-readable invariant:

```text
ORDER_GRAIN_MISMATCH
UNVALIDATED_JOIN
JOIN_FANOUT_UNMITIGATED
METRIC_OPERATOR_MISMATCH
PERCENT_DENOMINATOR_MISSING
TIME_WINDOW_MISMATCH
STATUS_POLICY_MISSING
OUTPUT_SHAPE_MISMATCH
```

#### P1 — Thêm result diagnostics sau execution

Execution thành công vẫn cần các tín hiệu:

- scalar/list/table shape và actual type;
- empty/null/non-finite/truncated;
- duplicate entity rate nếu output là entity list;
- denominator zero;
- result nằm ngoài phạm vi hợp lý có thể chứng minh từ profile, ví dụ count lớn hơn distinct entity toàn bảng;
- query có chạm đúng kỳ dữ liệu hay filter tạo zero rows;
- fan-out multiplier quan sát được đối với join rủi ro.

Các sanity bound phải dựa trên catalog/profile, không dùng ngưỡng cảm tính kiểu “doanh thu quá lớn”.

#### P1 — Repair dùng proof thay vì chỉ error text

Nếu validator chặn query, repair request cần chứa:

- `plan_id` và invariant bị vi phạm;
- AST fact hiện tại;
- role/key đúng cần dùng;
- schema subset liên quan;
- ràng buộc “không đổi metric/answer type/time window”.

Nếu attempt 1 vẫn vi phạm cùng invariant, chuyển `abstain`; không tiếp tục cứu bằng đổi type.

### 7.4. Tiêu chí nghiệm thu B0.4

- 100% SQL trước executor có `SemanticProof`.
- Semantic validator chặn toàn bộ sentinel: count-vs-sum, count-line-vs-order, 1-n fan-out, percent thiếu denominator, inventory shortcut.
- 0 query dùng join `uncertain` hoặc thiếu composite key pair.
- Không làm giảm các safety invariant hiện có của read-only executor.
- Error code đủ cụ thể để đo lỗi theo metric/grain/join/time thay vì gom vào `EXECUTOR_FAILURE`.

## 8. B0.5 — Risk gate, answerability và submission writer

### 8.1. Điểm tốt hiện tại

- Contract 9 answer types rõ ràng.
- Shape/null/non-finite/truncation validation có cấu trúc.
- `unanswerable` yêu cầu evidence `catalog_verified` thay vì tin trực tiếp model.
- Writer de-duplicate ID và dùng `allow_nan=False`.

### 8.2. Khoảng trống cần sửa

`validate_execution()` chỉ kiểm execution status và shape/content (`validators.py:10-129`). Nếu pass, gate format rồi trả `VALID_RESULT` (`gate.py:85-110`). Đây là lý do 398/606 `VALID_RESULT` vẫn sai.

Hai cơ chế “cứu” hiện tại còn che giấu mismatch:

- scalar nhiều dòng có thể tự đổi sang `list` nếu SQL có `LIMIT > 1` (`validators.py:76-82`);
- formatter lỗi có thể tự đổi `number → date/string` (`gate.py:112-151`).

Answerability proof hiện chỉ kiểm token missing field có xuất hiện trong catalog hay không. Một concept dẫn xuất do model bịa tên vẫn dễ trở thành “missing field đã xác minh”.

Writer ghi append từng dòng. Dù code hiện tại không tạo hai typo đã thấy, quy trình không có bước finalization chứng minh submission bằng gate/log, nên hậu xử lý ngoài pipeline có thể làm file lệch mà không bị phát hiện.

### 8.3. Cải tiến đề xuất

#### P0 — Gate theo bằng chứng, fail closed

Chỉ phát hành `answer` khi đồng thời có:

- `QuestionPlan` hợp lệ;
- capability `supported`;
- `SemanticProof.passed=true`;
- execution và output validation pass;
- không có high-risk signal chưa giải quyết;
- answer type đúng với plan, không phải type được tự sửa sau execution.

Nếu type/shape không khớp plan, retry hoặc abstain. Không mutate contract để làm output “hợp lệ về hình thức”.

#### P0 — Sửa answerability proof

- `missing_fields` tự do từ model chỉ là hint, không phải proof.
- B0.5 chỉ nhận `required_capabilities` và proof do B0.2 resolver tạo.
- Derived metric như `orders_in_T4_2026` phải được phân rã thành `order_id + order_date + time window`; không được coi là cột vật lý bắt buộc.
- `unanswerable` chỉ khi capability status là `unsupported`; `ambiguous/unknown` thành `abstain`.
- Reason gửi ra submission được dựng từ taxonomy/provenance, không copy prose tùy ý của model.

#### P0 — Canonical submission finalizer

Thay vì coi file append là artifact cuối cùng:

1. lưu `GateOutcome` canonical cho từng ID;
2. cuối run dựng lại `submission.jsonl` theo thứ tự question manifest;
3. ghi file tạm rồi atomic rename;
4. validate enum/type/schema từng dòng;
5. kiểm đủ, không trùng, không thừa ID;
6. đối chiếu `submission == gate outcome == detailed log` cho mọi ID;
7. tạo SHA-256 manifest ngay sau finalize và trước upload;
8. fail pipeline nếu bất kỳ invariant nào sai.

Điều này phải bắt được `ubstain`, `ananswerable` và reason bị copy từ câu khác trước khi nộp.

#### P1 — Score-aware risk gate

Với luật `+1/-1`, trả lời chỉ có kỳ vọng dương khi xác suất đúng `p > 0,5`:

```text
E(score | answer) = p - (1 - p) = 2p - 1
```

Không dùng confidence do LLM tự khai báo. Xây risk score từ tín hiệu đo được:

- metric template có/không;
- semantic role/grain coverage;
- validated join hay không;
- số invariant pass/fail;
- generation contract/retry history;
- rule conflict;
- result diagnostics;
- nhóm intent/business và hiệu năng lịch sử trên validation.

Ngưỡng ban đầu nên nhắm precision 65–70% để có biên an toàn. Threshold cần calibrate trên validation split đóng băng, không tối ưu trực tiếp trên Public Test.

#### P2 — Calibration theo slice

Calibration riêng cho `number`, `percent`, `list`, `date`, business/domain và metric family. Một threshold chung có thể giữ lại nhóm dễ nhưng phát hành quá nhiều ở nhóm percent/list đang có accuracy thấp.

### 8.4. Tiêu chí nghiệm thu B0.5

- 0 answer được phát hành nếu thiếu plan/semantic proof/execution proof.
- 0 lần tự đổi answer type sau execution; mismatch phải retry/abstain.
- Precision trên các câu được trả lời ≥65% ở validation tổng và không slice lớn nào dưới 50%.
- `unanswerable` precision ≥90%, recall ≥80%.
- 0 mismatch giữa submission, gate outcomes và detailed logs; checksum tái lập tuyệt đối.

## 9. Pipeline/orchestrator — thay đổi bắt buộc để năm tầng thực sự nối với nhau

Pipeline hiện tại nạp context, gọi generator, thực thi SQL rồi gọi gate (`pipeline.py:150-180`, `pipeline.py:540-578`). `RuleResolver`, metric plan và semantic validator không nằm trên đường chạy này.

Luồng đề xuất cho mỗi câu:

1. nạp bundle đã version hóa và kiểm schema/rule fingerprint;
2. B0.2 resolve rule/capability theo câu hỏi;
3. B0.3 planner sinh `QuestionPlan`;
4. kiểm capability trước generation:
   - `unsupported` có proof → candidate `unanswerable`;
   - `ambiguous/unknown` → abstain hoặc bounded clarification strategy;
   - `supported` → tiếp tục;
5. B0.3 sinh SQL từ plan và context subset;
6. B0.4 semantic validate;
7. nếu pass, B0.4 execute và tạo diagnostics;
8. B0.5 risk/output gate;
9. audit toàn bộ plan, rule IDs, proof, SQL, telemetry và decision;
10. cuối run canonicalize submission.

### 9.1. Telemetry tối thiểu

Mỗi attempt cần log:

- model/prompt/schema/rule/metric version;
- selected rules và capabilities;
- `QuestionPlan` và plan validation;
- raw response reference/hash, finish reason, token counts;
- SQL AST summary và semantic invariant results;
- execution status/time/row count/result diagnostics;
- gate risk signals, calibrated probability/score và threshold;
- final artifact checksum.

Không cần lưu chain-of-thought. `thinking` không phải bằng chứng correctness và có thể làm log lớn; chỉ cần plan/decision facts có cấu trúc.

## 10. Thứ tự triển khai theo ROI

### M0 — Khóa benchmark và artifact integrity

**Thay đổi:**

- local evaluator tái lập score;
- canonical finalizer + schema/ID/integrity check + checksum;
- giữ Public Test GT chỉ ở offline evaluation.

**Lý do ưu tiên:** sửa được rủi ro nộp file hỏng mà không phụ thuộc model hay schema.

**Exit gate:** 0 mismatch artifact, score local deterministic.

### M1 — Chặn lỗi deterministic và semantic rõ nhất

**Thay đổi:**

- AST outer projection và answer type nguồn duy nhất từ plan;
- `enable_thinking=false` A/B + strict JSON telemetry;
- `SemanticQueryValidator` cho order count, revenue, percent và join fan-out;
- không chuyển uncertain join xuống generator.

**Lý do ưu tiên:** xử lý trực tiếp 38 lỗi type, 166 generation invalid và nhóm lỗi metric/grain lớn nhất.

**Exit gate:** generation invalid <2%; sentinel semantic errors bị chặn 100%; answered precision vượt 50%.

### M2 — Làm giàu B0.1/B0.2 và tích hợp runtime

**Thay đổi:**

- semantic roles, business grain, measure additivity và date coverage;
- metric registry/capability graph;
- `RuleResolver`/`RuleTemplateBinder` trên đường chạy chính;
- template cho number/percent phổ biến.

**Lý do ưu tiên:** giải quyết gốc của 391 lỗi đúng shape nhưng sai nội dung.

**Exit gate:** mọi query được phát hành có metric definition, validated grain/join và capability proof.

### M3 — Plan-first generation và typed retry

**Thay đổi:**

- `QuestionPlan` riêng;
- deterministic renderer cho metric phổ biến;
- context retrieval;
- retry theo contract/semantic/schema/execution.

**Exit gate:** plan accuracy ≥90% trên bộ intent có nhãn; retry không được đổi metric/time window/answer type.

### M4 — Calibration và mở rộng coverage

**Thay đổi:**

- risk calibration theo answer type/metric/business;
- thêm template long-tail;
- multi-candidate chỉ cho high-risk cases.

**Exit gate:** precision ≥65% tổng, mọi slice lớn >50%, score validation dương ổn định qua nhiều seed/run.

## 11. Ma trận thay đổi theo module

| Module hiện tại | Thay đổi chính | Module mới/gợi ý |
|---|---|---|
| `b01/contracts.py` | thêm semantic roles, business grain, measure level/additivity, date coverage | `b01/semantic_catalog.py` |
| `b01/schema_catalog.py` | phân biệt structural/business grain; không tự nâng join uncertain | giữ builder + thêm validators |
| `b01/ingestion/profiling.py` | duplication/fan-out/date-gap profiles | `b01/semantic_profiling.py` |
| `b02/rule_resolver.py` | dùng trực tiếp trong pipeline | `b02/metric_registry.py` |
| `b02/rule_templates.py` | mở rộng template theo intent | `b02/capability_resolver.py` |
| `b03/prompt.py` | prompt theo plan/context subset; bỏ giả định không có evidence | `b03/planner.py` |
| `b03/parser.py` | AST outer projection, strict contract | `b03/plan_contracts.py` |
| `b03/generator.py` | truyền telemetry, tách plan/SQL generation | `b03/sql_renderer.py` |
| `b04/sanitizer.py` | giữ security-only | `b04/semantic_validator.py` |
| `b04/engine.py` | trả result diagnostics/proof | `b04/result_diagnostics.py` |
| `b05/answerability.py` | dùng capability proof đóng | `b05/risk_gate.py` |
| `b05/validators.py` | không mutate type | giữ strict output validator |
| `b05/writer.py` | canonical atomic finalize + manifest | `b05/finalizer.py` |
| `b0/pipeline.py` | orchestrate plan/proof contracts | cập nhật pipeline + telemetry |

## 12. Bộ regression tối thiểu

Bộ test cần giữ cả unit, contract và end-to-end:

| Nhóm | Ca đại diện | Kỳ vọng |
|---|---|---|
| Metric intent | `q_37a4aca072a6`, `q_c76ae61c6092` | plan `order_count`; SQL không dùng revenue làm output |
| Entity grain | `q_585664a97754` | count distinct order hoặc pre-aggregated order relation |
| Join fan-out | `q_10831a6f3a2b` | query sai bị semantic validator chặn |
| Repeated measure | `q_522627a83f38` | không sum order-level amount qua line grain |
| Inventory flow | `q_0ca19cd317cb` | không dùng imported-positive làm on-hand |
| Percent | `q_c0d31d97c743` | có numerator, denominator, division và percent semantics |
| Answerability | `q_008fdebb6ec9` | unanswerable có capability proof; không suy group từ name |
| CTE output | 38 case đã phát `table` | outer projection quyết định shape đúng |
| Structured output | `q_013b4ff35811` và các generation invalid | JSON hợp lệ hoặc retry/abstain có telemetry đầy đủ |
| Artifact integrity | `q_fa1084dc1d3f`, `q_fb290d8944ec` | finalizer từ chối invalid type/mismatched content |

Các ID Public Test chỉ nên dùng trong offline regression/audit. Production code không được chứa lookup theo question ID, câu trả lời chuẩn hoặc threshold rút ra trực tiếp từ từng answer.

## 13. Mục tiêu đo lường cho lần nộp kế tiếp

| Trục | Hiện tại | Mục tiêu kế tiếp |
|---|---:|---:|
| Answered precision | 35,6% | ≥65% |
| `VALID_RESULT` precision | 34,3% | thay bằng proof-backed answer; ≥65% |
| `GENERATION_INVALID` | 16,6% toàn tập | <2% |
| `RETRY_EXHAUSTED` | 4,3% toàn tập | <2% |
| Output `table` đúng | 0/38 prediction | không còn lỗi type do parser; table chỉ khi plan yêu cầu |
| `unanswerable` precision | 44,7% | ≥90% |
| `unanswerable` recall | 67,7% | ≥80% |
| Artifact mismatch | 2 ID | 0 |
| Join uncertain được dùng | chưa được chặn | 0 |

Mục tiêu score nên theo từng nấc:

- đầu tiên đạt score validation dương bằng cách chặn nhóm rủi ro;
- sau đó đạt ít nhất `350 đúng / ≤188 sai` để vừa đạt precision xấp xỉ 65% vừa có score ≥0,162 nếu tập 1.000 câu;
- chỉ tăng coverage khi slice mới giữ precision >50%, tốt hơn là ≥65%.

## 14. Các quyết định kiến trúc được đề xuất và trade-off

### Quyết định A — Plan-first hybrid thay vì free-form Text-to-SQL một lượt

**Chọn:** metric/template có cấu trúc cho intent phổ biến; LLM lập plan/mapping và xử lý long-tail.
**Không chọn:** tiếp tục tăng rule prose trong một prompt lớn.

**Trade-off:** cần đầu tư metric registry và mapping theo business, nhưng đổi lại có thể test, validate và giải thích lỗi từng bước. Đây là trade-off phù hợp vì phần lớn thiệt hại hiện đến từ semantic correctness, không phải thiếu khả năng sinh SQL cú pháp.

### Quyết định B — Fail closed khi grain/join/capability chưa chắc chắn

**Chọn:** `unknown/ambiguous/uncertain` không được phát hành như answer chắc chắn.
**Trade-off:** coverage ban đầu giảm, nhưng với luật `+1/-1` điều này làm tăng score kỳ vọng khi precision hiện chỉ 35,6%.

### Quyết định C — Answer type thuộc QuestionPlan

**Chọn:** type được xác định từ câu hỏi/intent trước SQL; AST chỉ xác minh conformance.
**Không chọn:** sửa type sau khi nhìn result để làm output hợp lệ.

**Trade-off:** một plan sai sẽ bị retry/abstain thay vì được “cứu”, nhưng tránh che giấu lỗi intent và tạo output đúng type bề ngoài nhưng sai câu hỏi.

### Quyết định D — B0.4 sở hữu semantic SQL validation, B0.5 sở hữu risk/release

**Lý do:** B0.4 đã sở hữu AST và execution boundary nên phù hợp kiểm SQL; B0.5 không nên parse và diễn giải SQL lần nữa. B0.5 tổng hợp proof để quyết định phát hành.

### Quyết định E — Public GT là công cụ đánh giá, không phải nguồn tri thức runtime

**Lý do:** dùng GT để tạo error taxonomy và regression là hợp lệ cho phát triển; nhúng ID/answer/pattern riêng từng câu vào pipeline sẽ overfit và không tổng quát sang private test.

## 15. Những việc không nên làm trước

- Không đổi model lớn hơn trước khi có semantic validator; model mạnh hơn vẫn có thể sinh SQL sai nhưng rất thuyết phục.
- Không giảm abstain bằng mọi giá; coverage tăng ở precision dưới 50% làm điểm xấu đi.
- Không nhồi thêm toàn bộ rulebook vào prompt; hãy resolve và retrieve đúng rule.
- Không coi query chạy thành công là bằng chứng trả lời đúng.
- Không coi value overlap là bằng chứng đủ để validate join.
- Không suy field/category nghiệp vụ từ tên sản phẩm nếu rulebook không cho phép rõ ràng.
- Không auto-correct answer type sau execution.
- Không tối ưu threshold trực tiếp trên 1.000 Public Test câu rồi báo đó là khả năng tổng quát.

## 16. Kết luận

Baseline cần chuyển từ kiến trúc **“LLM sinh SQL → chạy được → format → phát hành”** sang **“catalog có ngữ nghĩa → metric plan → SQL conforming → proof → risk gate”**.

Nếu chỉ chọn một lát cắt để triển khai ngay, nên làm M0 + M1: khóa submission integrity, sửa outer-select parser, A/B structured non-thinking, thêm semantic validator cho `order_count/revenue/percent/join fan-out`, và mặc định abstain khi proof chưa đủ. Lát cắt này tác động trực tiếp vào các nguồn mất điểm lớn nhất mà chưa đòi hỏi viết lại toàn bộ hệ thống.
