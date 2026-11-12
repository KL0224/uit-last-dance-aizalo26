# Cơ Chế Chuyển Từ Rule-Based Sang LLM Trong Question Grounding

## 1. Mục đích

Tài liệu này mô tả khi nào tầng Question Grounding sử dụng fast-path rule-based, khi nào chuyển sang Qwen 3B qua LLM fallback, cách kiểm tra kết quả LLM và cách hệ thống suy giảm an toàn nếu LLM thất bại.

Tài liệu kiến trúc tổng thể: [GROUNDING_ARCHITECTURE.md](../grounding/GROUNDING_ARCHITECTURE.md).

Các thành phần liên quan:

- `VietnameseQuestionNormalizer`: chuẩn hóa Unicode, khoảng trắng và một số từ viết tắt trước khi phân tích.
- `VietnameseRuleMatcher`: trích xuất intent bằng luật và gán confidence.
- `QuestionIntentParser`: quyết định giữ kết quả rule-based hay gọi LLM.
- `StructuredLLMParser`: gọi Qwen 3B và chuyển JSON trả về thành `QuestionIntent`.
- `QuestionGroundingEngine`: đưa intent qua các bước temporal, schema, value và answerability.

## 2. “Rule-based thất bại” có nghĩa là gì?

Trong kiến trúc hiện tại, `VietnameseRuleMatcher` gần như luôn trả về một `QuestionIntent`; nó không cần ném exception mới được xem là thất bại. “Thất bại” ở đây có nghĩa là kết quả rule-based **không có đủ bằng chứng ngữ nghĩa để được tin cậy**, ví dụ:

- Không nhận ra cấu trúc câu hỏi nên chỉ trả về `LOOKUP` với confidence thấp.
- Nhận ra phép tính nhưng không nhận ra metric bắt buộc.
- Nhận ra nhiều metric và chưa xác định được metric chính.
- Metric được nhận ra không tồn tại trong registry của doanh nghiệp.
- Câu hỏi còn ký hiệu, emoji hoặc từ viết tắt chưa giải quyết được.

LLM vì vậy là nhánh phục hồi có điều kiện, không phải đường xử lý mặc định.

## 3. Luồng điều khiển tổng quát

```text
┌───────────────────────────────────┐
│            Câu hỏi gốc            │
└─────────────────┬─────────────────┘
                  │
                  ▼
┌───────────────────────────────────┐
│   VietnameseQuestionNormalizer    │
└─────────────────┬─────────────────┘
                  │
                  ▼
┌───────────────────────────────────┐
│       VietnameseRuleMatcher       │
│  → tạo QuestionIntent từ rule     │
└─────────────────┬─────────────────┘
                  │
                  ▼
          ┌─────────────────────┐
          │ Có fallback reason? │
          └──────────┬──────────┘
                    │
          ┌─────────┴─────────┐
          │                   │
       Không                  Có
          │                   │
          ▼                   ▼
┌───────────────────┐  ┌───────────────────┐
│  Dùng rule intent │  │ Đã cấu hình LLM?  │
└─────────┬─────────┘  └─────────┬─────────┘
          │              ┌────────┴────────┐
          │              │                 │
          │           Không                Có
          │              │                 │
          │              ▼                 ▼
          │  ┌──────────────────────┐  ┌──────────────────────────┐
          │  │ Giữ rule intent và   │  │ StructuredLLMParser     │
          │  │ ghi fallback_reasons │  │ gọi Qwen 3B             │
          │  └──────────┬───────────┘  └────────────┬─────────────┘
          │             │                           │
          │             │                           ▼
          │             │                  ┌─────────────────────┐
          │             │                  │ JSON và intent      │
          │             │                  │ hợp lệ?             │
          │             │                  └──────────┬──────────┘
          │             │                     ┌───────┴───────┐
          │             │                     │               │
          │             │                   Không             Có
          │             │                     │               │
          │             │                     ▼               ▼
          │             │       ┌─────────────────────┐  ┌───────────────┐
          │             │       │ Giữ rule intent +   │  │ Dùng LLM      │
          │             │       │ LLM_FALLBACK_FAILED │  │ intent        │
          │             │       └──────────┬──────────┘  └───────┬───────┘
          │             │                  │                     │
          └─────────────┴──────────────────┴─────────────────────┘
                                      │
                                      ▼
                        ┌──────────────────────────┐
                        │ C2. Temporal Resolution  │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │ C3. Schema Grounding     │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │ C4. Value Grounding      │
                        └────────────┬─────────────┘
                                     │
                                     ▼
                        ┌──────────────────────────┐
                        │ C5. Answerability Check  │
                        └──────────────────────────┘
```

Điểm quyết định nằm trong `QuestionIntentParser.decide_fallback()`. Chỉ cần xuất hiện **ít nhất một** lý do bên dưới thì `should_use_llm = True`.

## 4. Các điều kiện chuyển sang LLM

### 4.1. `LOW_RULE_CONFIDENCE`

**Ý nghĩa:** Rule matcher đã tạo được một `QuestionIntent`, nhưng số điểm tin cậy của intent thấp hơn ngưỡng chấp nhận. Điểm thấp cho biết các pattern hiện có không cung cấp đủ bằng chứng để kết luận chắc chắn operation, metric hoặc kiểu câu trả lời. Đây là điểm heuristic của bộ luật, không phải xác suất intent đúng.

**Tại sao chuyển sang LLM:** Rule-based chỉ nhận ra các từ khóa và cấu trúc đã được định nghĩa trước. Khi người dùng diễn đạt gián tiếp, dùng cách nói mới hoặc đặt câu hỏi hội thoại, rule có thể mặc định sai thành `LOOKUP`. LLM có khả năng xét toàn bộ câu và ngữ cảnh để diễn giải các cách diễn đạt ngoài tập pattern. Chuyển sang LLM trong trường hợp này giúp tránh đưa một intent yếu sang các tầng C2–C5 như thể nó đã đáng tin cậy.

Điều kiện:

```text
rule_intent.confidence < fallback_threshold
```

Ngưỡng mặc định là `0.7`.

Rule matcher hiện gán:

- `0.9` khi nhận ra một mẫu operation rõ ràng.
- `0.45` khi không nhận ra cấu trúc và phải mặc định thành `LOOKUP`.
- Tối đa `0.55` khi nhận ra `SUM`, `AVG`, `PERCENT_CHANGE` hoặc `RATIO` nhưng không tìm được metric.

Ví dụ:

```text
Câu hỏi: "Tình hình bán hàng dạo này thế nào?"
```

Không có mẫu rõ ràng cho tổng, trung bình, Top-K hay so sánh. Rule matcher có thể trả về:

```json
{
  "operation": "lookup",
  "target_metrics": [],
  "confidence": 0.45
}
```

Kết quả: gọi LLM với reason `LOW_RULE_CONFIDENCE`.

Lưu ý: confidence hiện là điểm heuristic theo nhánh luật, không phải xác suất đã được calibration trên dữ liệu thực tế.

### 4.2. `MISSING_REQUIRED_METRIC`

**Ý nghĩa:** Rule matcher đã nhận ra operation cần thực hiện, nhưng chưa xác định được đại lượng mà operation phải tác động lên. Chẳng hạn, biết câu hỏi yêu cầu tính tổng nhưng chưa biết phải tính tổng `revenue`, `sold_qty`, `cost` hay một metric khác. Vì vậy intent chưa đủ dữ liệu để lập kế hoạch truy vấn.

**Tại sao chuyển sang LLM:** Nếu tiếp tục với metric rỗng, planner có thể chọn nhầm cột, tự suy đoán metric hoặc không tạo được truy vấn hợp lệ. LLM nhận cả câu hỏi và danh sách metric khả dụng nên có thêm cơ hội suy ra metric từ ngữ cảnh, từ đồng nghĩa hoặc cách diễn đạt gián tiếp. Kết quả LLM vẫn bị kiểm tra để bảo đảm metric được chọn thuộc registry; LLM không được phép bịa metric mới.

Điều kiện: operation cần metric nhưng `target_metrics` rỗng.

Các operation bắt buộc phải có metric:

- `SUM`
- `AVG`
- `ARGMAX`
- `ARGMIN`
- `TOP_K`
- `PERCENT_CHANGE`
- `RATIO`
- `COMPARISON`

Ví dụ:

```text
Câu hỏi: "Tổng tháng này là bao nhiêu?"
```

Rule có thể nhận ra `SUM` từ từ “tổng”, nhưng không biết cần tổng doanh thu, số lượng bán, chi phí hay lợi nhuận.

```json
{
  "operation": "sum",
  "target_metrics": [],
  "confidence": 0.55
}
```

Kết quả: gọi LLM với ít nhất hai reason:

```text
LOW_RULE_CONFIDENCE
MISSING_REQUIRED_METRIC
```

### 4.3. `AMBIGUOUS_METRICS`

**Ý nghĩa:** Rule matcher nhận ra nhiều hơn một metric trong cùng câu hỏi, nhưng chưa xác định được vai trò của từng metric. Việc xuất hiện đồng thời nhiều metric có thể biểu thị yêu cầu trả nhiều kết quả, so sánh, tính tỷ lệ hoặc chỉ là một metric được nhắc đến để bổ nghĩa cho metric khác.

**Tại sao chuyển sang LLM:** Việc chọn metric đầu tiên hoặc áp dụng cùng một operation lên tất cả metric là quyết định thiếu căn cứ và có thể làm sai ý người dùng. LLM có thể phân tích quan hệ ngữ nghĩa giữa các metric để chọn operation và cấu trúc intent phù hợp hơn. Việc fallback vẫn được kích hoạt ngay cả khi rule confidence cao, vì confidence cao chỉ cho biết các từ khóa đã khớp tốt, không giải quyết được quan hệ giữa nhiều metric.

Điều kiện:

```text
len(rule_intent.target_metrics) > 1
```

Ví dụ:

```text
Câu hỏi: "Doanh thu và lợi nhuận tháng này là bao nhiêu?"
```

Rule matcher có thể nhận ra đồng thời:

```json
{
  "operation": "sum",
  "target_metrics": ["revenue", "gross_profit"],
  "confidence": 0.9
}
```

Dù confidence cao, hệ thống vẫn gọi LLM vì chưa chắc người dùng muốn một kết quả tổng hợp, hai kết quả riêng hay một phép so sánh.

### 4.4. `METRIC_OUTSIDE_REGISTRY`

**Ý nghĩa:** Rule matcher nhận ra một metric từ pattern hoặc từ đồng nghĩa dựng sẵn, nhưng metric đó không tồn tại trong metric registry của doanh nghiệp hiện tại. Intent vì vậy không tương thích với dữ liệu và hợp đồng nghiệp vụ đang khả dụng.

**Tại sao chuyển sang LLM:** Đưa metric không tồn tại xuống schema grounding dễ dẫn đến chọn sai cột, không tìm được bảng hoặc tạo truy vấn dựa trên dữ liệu không có thật. LLM được cung cấp danh sách metric hợp lệ nên có thể thử diễn giải lại câu hỏi theo vocabulary của doanh nghiệp. Tuy nhiên, fallback không thể biến một metric thực sự thiếu thành dữ liệu có sẵn; nếu LLM vẫn trả metric ngoài registry, validation sẽ từ chối kết quả và hệ thống quay về safe degradation.

Điều kiện:

- Business context có metric registry không rỗng.
- Rule matcher tạo ra ít nhất một metric không tồn tại trong registry đó.

Ví dụ:

```text
Câu hỏi: "Lợi nhuận tháng này là bao nhiêu?"
Registry của doanh nghiệp: ["revenue", "order_count"]
Rule nhận ra metric: "gross_profit"
```

Kết quả: gọi LLM với reason `METRIC_OUTSIDE_REGISTRY` để LLM thử diễn giải lại theo các metric thực sự khả dụng.

LLM không được phép tự tạo metric mới. Nếu LLM vẫn trả về `gross_profit`, output validation sẽ từ chối kết quả đó.

### 4.5. `UNRESOLVED_SYMBOL`

**Ý nghĩa:** Câu hỏi chứa emoji, ký hiệu tiền tệ hoặc ký hiệu Unicode khác mà hệ thống phát hiện được nhưng chưa biết ý nghĩa nghiệp vụ. Ký hiệu đó cũng chưa được khai báo trong value aliases của business context, nên rule matcher không thể chuyển nó thành entity hay filter cụ thể.

**Tại sao chuyển sang LLM:** Một ký hiệu có thể mang nghĩa phụ thuộc ngữ cảnh, chẳng hạn `🌙` có thể chỉ “ca tối”, còn ký hiệu tiền tệ có thể bổ nghĩa cho doanh thu hoặc chi phí. Bộ luật chỉ có thể phát hiện sự tồn tại của ký hiệu, không thể suy luận an toàn ý nghĩa của mọi ký hiệu mới. LLM có thể dùng phần văn bản xung quanh để chuẩn hóa ký hiệu thành cách diễn đạt rõ ràng trước khi các tầng deterministic tiếp tục xử lý.

Điều kiện: câu hỏi chứa ký hiệu thuộc nhóm Unicode Symbol hoặc Currency Symbol mà không được giải quyết bởi value alias trong business context.

Ví dụ:

```text
Câu hỏi: "Doanh thu ca 🌙 hôm qua là bao nhiêu?"
```

Nếu `🌙` chưa được khai báo là alias của “ca tối”, rule matcher không biết ý nghĩa ký hiệu này.

Kết quả: gọi LLM với reason `UNRESOLVED_SYMBOL`.

Nếu business context đã khai báo alias `🌙 -> Ca tối`, ký hiệu được xem là đã giải quyết và bản thân nó không kích hoạt fallback.

### 4.6. `UNRESOLVED_SHORTHAND`

**Ý nghĩa:** Câu hỏi còn chứa token có hình thức của một từ viết tắt nhưng deterministic normalizer và business context chưa ánh xạ được nó sang thuật ngữ đầy đủ. Cùng một chữ viết tắt có thể mang nhiều nghĩa theo doanh nghiệp, ví dụ `CP` có thể là “chi phí”, “cổ phần” hoặc một mã nội bộ.

**Tại sao chuyển sang LLM:** Tự động mở rộng một từ viết tắt chưa biết bằng rule cố định có nguy cơ làm thay đổi hoàn toàn metric hoặc entity được hỏi. LLM có thể kết hợp phần còn lại của câu với danh sách metric và bảng khả dụng để chọn cách diễn giải phù hợp hơn. Nếu registry đã khai báo từ viết tắt là alias hợp lệ thì không cần LLM, vì khi đó nghĩa của token đã được xác định bằng dữ liệu doanh nghiệp.

Điều kiện: câu hỏi còn từ viết tắt chưa được normalizer hoặc business context giải quyết. Bộ phát hiện hiện xem xét:

- Token viết hoa dài từ 2 đến 8 ký tự, ví dụ `GMV`, `AOV`.
- Dạng có dấu chấm, ví dụ `d.thu`, `h.nay`.
- Một tập viết tắt tiếng Việt phổ biến, ví dụ `ck`, `cp`, `cty`, `dh`, `dt`, `kh`, `ln`, `nv`, `sl`, `sp`, `tt`.

Ví dụ:

```text
Câu hỏi: "GMV hnay là bn?"
```

Normalizer có thể xử lý `hnay`, nhưng nếu `GMV` không phải alias của metric trong context thì parser vẫn phát hiện từ viết tắt chưa giải quyết.

Kết quả: gọi LLM với reason `UNRESOLVED_SHORTHAND`.

Ngược lại, nếu registry khai báo `GMV` là alias của `revenue`, token này không kích hoạt fallback.

## 5. Khi nào giữ fast-path rule-based?

Kết quả rule-based được dùng trực tiếp khi đồng thời thỏa mãn:

1. `confidence >= 0.7`.
2. Operation cần metric đã có ít nhất một metric.
3. Không có nhiều hơn một metric.
4. Metric thuộc registry của doanh nghiệp, nếu registry tồn tại.
5. Không còn symbol chưa giải quyết.
6. Không còn shorthand chưa giải quyết.

Ví dụ:

```text
Câu hỏi: "Doanh thu tháng này là bao nhiêu?"
```

Kết quả rule dự kiến:

```json
{
  "operation": "sum",
  "target_metrics": ["revenue"],
  "confidence": 0.9,
  "used_llm_fallback": false,
  "fallback_reasons": []
}
```

Đây là fast-path: không gọi model 3B, giảm latency và giữ tính tất định.

## 6. Dữ liệu gửi sang LLM

Khi cần fallback và đã cấu hình LLM, `StructuredLLMParser` nhận:

```text
Câu hỏi: <question đã qua deterministic normalizer>
Ngày tham chiếu (as_of_date): <YYYY-MM-DD>
Metric IDs khả dụng: <danh sách metric đã giới hạn>
Bảng ứng viên: <danh sách bảng đã giới hạn>
```

LLM phải trả về một JSON có cấu trúc, gồm các trường chính:

- `normalized_question`
- `operation`
- `target_metrics`
- `entities`
- `filters`
- `group_by`
- `top_k`
- `sort_order`
- `answer_type_hint`

LLM chỉ làm nhiệm vụ **trích xuất ngữ nghĩa**, không sinh SQL.

Để bảo vệ context window, prompt giới hạn tối đa 64 metric và 32 bảng, ưu tiên candidate liên quan tới câu hỏi. Nếu prompt vẫn vượt token budget, hệ thống giảm dần danh sách bảng, sau đó giảm danh sách metric. Nếu vẫn không vừa, lần fallback bị từ chối trước khi inference.

## 7. Kiểm tra kết quả LLM

Kết quả LLM không được tin cậy trực tiếp. Hệ thống kiểm tra cả cấu trúc lẫn ngữ nghĩa:

- Response phải là JSON object hợp lệ và không vượt giới hạn kích thước.
- `operation` và `answer_type_hint` phải thuộc enum cho phép.
- `target_metrics` phải thuộc metric registry được truyền vào.
- `group_by` chỉ được thuộc `customer`, `product`, `date`, `shift`.
- Filter operator chỉ được thuộc allowlist.
- Operation cần metric không được trả về danh sách metric rỗng.
- `TOP_K` phải có `top_k` dương.
- `sort_order` chỉ được là `asc` hoặc `desc`.

Khi hợp lệ, intent từ LLM được dùng với:

```json
{
  "confidence": 0.85,
  "used_llm_fallback": true,
  "fallback_reasons": ["các reason đã kích hoạt LLM"]
}
```

## 8. Khi LLM không khả dụng hoặc thất bại

### 8.1. Có reason nhưng chưa cấu hình LLM

Parser không gọi model và vẫn trả về rule intent. Các reason vẫn được giữ trong `fallback_reasons` để downstream và observability biết kết quả có rủi ro.

```json
{
  "used_llm_fallback": false,
  "fallback_reasons": ["MISSING_REQUIRED_METRIC"]
}
```

Hiện tại chưa có reason riêng như `LLM_FALLBACK_UNAVAILABLE`.

### 8.2. LLM lỗi hoặc trả output không hợp lệ

Các tình huống gồm:

- Lỗi load hoặc inference model.
- Prompt vượt token budget.
- Response không phải JSON hợp lệ.
- Metric, enum, group hoặc operator nằm ngoài allowlist.
- Intent thiếu metric bắt buộc hoặc `TOP_K` thiếu `top_k`.

Hệ thống ghi warning `grounding_llm_fallback_failed`, sau đó quay về rule intent và thêm:

```text
LLM_FALLBACK_FAILED
```

Ví dụ:

```json
{
  "operation": "sum",
  "target_metrics": [],
  "used_llm_fallback": false,
  "fallback_reasons": [
    "MISSING_REQUIRED_METRIC",
    "LLM_FALLBACK_FAILED"
  ]
}
```

Đây là cơ chế safe degradation: lỗi LLM không làm sập toàn bộ grounding pipeline. Tuy nhiên downstream cần xem intent này là có rủi ro vì nguyên nhân ban đầu chưa được giải quyết.

## 9. Phạm vi LLM trong toàn bộ grounding

LLM fallback chỉ can thiệp tại **C1 — Question Intent Parsing** và có thể cung cấp `normalized_question` tốt hơn. Sau đó câu hỏi hiệu lực được đưa vào các tầng tất định:

| Tầng | Trách nhiệm | Dùng LLM fallback? |
|---|---|---:|
| N0 | Chuẩn hóa Unicode và viết tắt có allowlist | Không |
| C1 | Operation, metric, entity, filter, group, Top-K | Có, khi xuất hiện fallback reason |
| C2 | Phân giải thời gian theo `as_of_date`, lịch và date role | Không |
| C3 | Chọn schema, fact table và join path | Không |
| C4 | Khớp value alias và giá trị thực tế | Không |
| C5 | Kiểm tra dữ liệu có đủ để trả lời | Không |

Ví dụ toàn tuyến:

```text
Input: "DT ca 🌙 h.nay bn?"

N0:
  "doanh thu ca 🌙 hôm nay bn?"

C1 rule:
  Nhận ra revenue nhưng còn symbol chưa giải quyết
  -> UNRESOLVED_SYMBOL

C1 LLM:
  normalized_question = "Doanh thu ca tối hôm nay là bao nhiêu?"
  operation = "sum"
  target_metrics = ["revenue"]

C2:
  Tính khoảng ngày "hôm nay" từ as_of_date

C3:
  Chọn bảng có metric revenue và đường join an toàn

C4:
  Ground "ca tối" vào giá trị thực trong database

C5:
  Kiểm tra schema và dữ liệu có đủ để trả lời
```

LLM không tự quyết định date range cuối cùng, không tự chọn join tùy ý và không tự khẳng định câu hỏi answerable. Các quyết định này vẫn thuộc các tầng deterministic phía sau.

## 10. Bảng quyết định nhanh

| Tình huống | Reason | Gọi LLM nếu đã cấu hình? |
|---|---|---:|
| Không nhận ra cấu trúc câu hỏi | `LOW_RULE_CONFIDENCE` | Có |
| Operation cần metric nhưng metric rỗng | `MISSING_REQUIRED_METRIC` | Có |
| Rule nhận ra nhiều metric | `AMBIGUOUS_METRICS` | Có |
| Metric không thuộc business registry | `METRIC_OUTSIDE_REGISTRY` | Có |
| Emoji/ký hiệu tiền tệ chưa có alias | `UNRESOLVED_SYMBOL` | Có |
| Từ viết tắt chưa có alias | `UNRESOLVED_SHORTHAND` | Có |
| Không có bất kỳ reason nào | Không có | Không |
| LLM lỗi hoặc output không hợp lệ | Thêm `LLM_FALLBACK_FAILED` | Quay về rule intent |

## 11. Điểm cần lưu ý khi đánh giá chất lượng

- Không nên đánh giá router chỉ bằng confidence, vì các kiểm tra bằng chứng như missing metric hoặc symbol chưa giải quyết có thể kích hoạt fallback dù confidence là `0.9`.
- Một câu hỏi có thể sinh nhiều reason; đây là hành vi mong đợi và giúp chẩn đoán chính xác hơn.
- Confidence `0.9`, `0.55`, `0.45` và `0.85` hiện là hằng số heuristic. Muốn xem chúng như xác suất cần calibration trên tập validation có nhãn.
- Việc LLM trả về confidence `0.85` không bảo đảm intent đúng; allowlist và các tầng C2–C5 vẫn là hàng rào kiểm soát bắt buộc.
- Khi không có LLM hoặc LLM thất bại, pipeline vẫn chạy tiếp với rule intent. Hệ thống gọi phía sau cần theo dõi `fallback_reasons` thay vì chỉ nhìn `used_llm_fallback`.

## 12. Tham chiếu mã nguồn

- [`parser.py`](../../../src/datamate/grounding/parser.py): quyết định fallback, validation intent và safe degradation.
- [`rules_matcher.py`](../../../src/datamate/grounding/rules_matcher.py): luật fast-path và cách gán confidence.
- [`llm_fallback.py`](../../../src/datamate/grounding/llm_fallback.py): prompt, token budget, parse và validation output LLM.
- [`normalizer.py`](../../../src/datamate/grounding/normalizer.py): chuẩn hóa câu hỏi trước C1.
- [`engine.py`](../../../src/datamate/grounding/engine.py): luồng C1 đến C5 và cách dùng `normalized_question`.
