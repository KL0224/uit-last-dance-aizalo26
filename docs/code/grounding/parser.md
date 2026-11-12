# Giải Thích Mã Nguồn: `parser.py`

**Đường dẫn file:** [`src/datamate/grounding/parser.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/parser.py)  
**Thuộc module:** Component C — Question Grounding (C1 Intent Parser Coordinator)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `parser.py` triển khai lớp `QuestionIntentParser` — **Bộ điều phối trung tâm của Module C1 (Intent Extraction Coordinator)**.

Module C1 là điểm chạm đầu tiên của câu hỏi người dùng khi bước vào Pha Question Grounding. Nhiệm vụ của nó là:
1. Tiếp nhận câu hỏi tiếng Việt và ngày tham chiếu `as_of_date`.
2. Áp dụng chiến lược **Hybrid Execution**: ưu tiên luật xác định (`VietnameseRuleMatcher` < 2ms), sau đó dùng `FallbackDecision` kiểm tra bằng chứng semantic trước khi quyết định gọi mô hình 3B (`StructuredLLMParser`).
3. Thực thi cơ chế **Suy giảm an toàn (Graceful Degradation)**: Bảo đảm pipeline luôn xuất ra một đối tượng `QuestionIntent` hợp lệ, không bao giờ để exception từ LLM làm sập quy trình chấm thi.

---

## 2. Chi Tiết Các Class & Phương Thức

### 2.1. Khởi Tạo `QuestionIntentParser`

```python
def __init__(
    self,
    rule_matcher: VietnameseRuleMatcher | None = None,
    llm_fallback: LLMParserProtocol | None = None,
    fallback_threshold: float = 0.7,
) -> None:
    self._rule_matcher = rule_matcher or VietnameseRuleMatcher()
    self._llm_fallback = llm_fallback
    self._fallback_threshold = fallback_threshold
```
* **Tham số**:
  * `rule_matcher`: Động cơ Regex bóc tách nhanh. Nếu không truyền, tự động khởi tạo mặc định.
  * `llm_fallback`: Đối tượng cài đặt `LLMParserProtocol` (mô hình 3B). Có thể để `None` nếu muốn chạy chế độ 100% deterministic (ví dụ trong các bài test hiệu năng hoặc môi trường không có GPU).
  * `fallback_threshold`: Ngưỡng tự tin (mặc định `0.70`). Đây chỉ là một tín hiệu; confidence cao không còn tự động bỏ qua LLM nếu metric/symbol/shorthand vẫn chưa được giải quyết.

---

### 2.2. Phương Thức `parse(...)`

```python
def parse(
    self,
    question: str,
    as_of_date: str,
    context: BusinessContextProtocol | None = None,
) -> QuestionIntent:
```

#### Quy Trình Điều Phối 3 Bước:
1. **Bước 1: Chạy Fast-Path bằng Rule Matcher**:
   * Gọi `rule_intent = self._rule_matcher.match(question, context)`.
   * Fast-path tạo `QuestionIntent` ban đầu. Điểm confidence gán theo rule vẫn được giữ để tương thích và quan sát, nhưng không còn là tiêu chí duy nhất.
2. **Bước 2: Đánh giá điều kiện kích hoạt Fallback**:
   * `decide_fallback()` trả về `FallbackDecision(should_use_llm, reasons)`.
   * Các lý do hiện có: `LOW_RULE_CONFIDENCE`, `MISSING_REQUIRED_METRIC`, `AMBIGUOUS_METRICS`, `METRIC_OUTSIDE_REGISTRY`, `UNRESOLVED_SYMBOL`, `UNRESOLVED_SHORTHAND`.
   * Viết tắt đã khai báo trong `value_aliases` như `CK` không bị coi là unresolved.
3. **Bước 3: Gọi LLM 3B Fallback & Xử lý suy giảm an toàn (Safe Fallback)**:
   * Thực hiện lời gọi:
     ```python
     try:
         return self._llm_fallback.extract_intent(
             question=question,
             as_of_date=as_of_date,
             available_metrics=available_metrics,
             available_tables=available_tables,
         )
     except Exception:
         # Suy giảm an toàn: trả về rule_intent nếu LLM gặp sự cố
         return rule_intent
     ```
   * Kết quả LLM được kiểm tra lại: metric phải khả dụng, operation cần metric không được để trống, `TOP_K` phải có `top_k`, `sort_order` chỉ nhận `asc|desc`.
   * Nếu model lỗi, JSON sai hoặc intent không đủ bằng chứng, pipeline ghi warning `grounding_llm_fallback_failed` (chỉ gồm reason và loại lỗi, không log câu hỏi), trả lại `rule_intent` và thêm `LLM_FALLBACK_FAILED` vào `fallback_reasons`.

---

## 3. Tại Sao Lại Thiết Kế & Code Như Vậy?

1. **Tối ưu hóa Chi Phí & Độ Trễ (Latency & Cost Optimization)**:
   * Trong 1.000 câu hỏi thi, nếu 800 câu chạy qua Rule Matcher mất 2ms/câu, và 200 câu chạy qua model 3B mất 150ms/câu, thì tổng thời gian phân tích ý định cho toàn bộ bài thi chỉ tốn **khoảng 31 giây**, thay vì tốn hàng chục phút nếu gọi LLM 9B cho toàn bộ 1.000 câu.
2. **Khả năng cấu hình linh hoạt (Pluggable Architecture)**:
   * Bạn có thể chạy hệ thống ở chế độ "Không cần GPU" (`llm_fallback=None`) mà các câu hỏi thông thường vẫn được phân tích hoàn hảo. Khi đưa lên máy chủ thi có GPU, chỉ cần truyền thêm adapter của model 3B vào.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Được gọi trực tiếp bởi `engine.py`**: Là bước C1 mở đầu cho toàn bộ quy trình Grounding.
* **Quyết định hướng đi cho C2 và C3**:
  * Nếu C1 xác định `operation == TOP_K`, C3 sẽ biết cần phải chuẩn bị danh sách cột và bảng hỗ trợ sắp xếp và giới hạn dòng (`LIMIT K`).
  * Nếu C1 xác định `target_metrics == ("cash_collected",)`, C2 sẽ ưu tiên giải quyết mốc thời gian theo vai trò `DateRole.PAYMENT_DATE`.

---

## 5. Nếu Không Có File Này Thì Sao?

* Nếu không có lớp điều phối này, code của bạn sẽ bị phân mảnh: hoặc phải hardcode gọi Regex ở một nơi và gọi LLM ở một nơi khác, hoặc phụ thuộc hoàn toàn vào một phương án duy nhất. Khi LLM gặp sự cố parse JSON, toàn bộ hệ thống sẽ bị crash do không có cơ chế quay lui (fallback) an toàn.
