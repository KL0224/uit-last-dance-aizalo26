# Giải Thích Mã Nguồn: `llm_fallback.py`

**Đường dẫn file:** [`src/datamate/grounding/llm_fallback.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/llm_fallback.py)  
**Thuộc module:** Component C — Question Grounding (C1 3B LLM Fallback)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `llm_fallback.py` triển khai lớp `StructuredLLMParser` — **Tầng dự phòng trích xuất ngữ nghĩa có cấu trúc (Structured Semantic Extractor Fallback)** của module C1.

Khi fast-path thiếu bằng chứng semantic (confidence thấp, thiếu/không hợp lệ metric, nhiều metric cạnh tranh, symbol/emoji hoặc viết tắt chưa giải nghĩa), hệ thống kích hoạt `StructuredLLMParser`.

Thay vì để mô hình 9B chính phải tự đọc câu hỏi và suy luận phân loại thô, file này sử dụng mô hình ngôn ngữ nhỏ **3B (`Qwen/Qwen2.5-3B-Instruct`)** làm nhiệm vụ chuyên biệt: đọc hiểu ngữ nghĩa câu hỏi tiếng Việt và xuất ra **DUY NHẤT một khối JSON** mô tả cấu trúc ý định.

---

## 2. Chi Tiết Các Thành Phần & Phương Thức

### 2.1. `EXTRACTOR_SYSTEM_PROMPT`
Prompt hệ thống được tinh chỉnh nghiêm ngặt dành riêng cho mô hình 3B:
```text
Bạn là bộ trích xuất ngữ nghĩa câu hỏi tiếng Việt (Semantic Extractor) cho hệ thống DataMate 2026.
Nhiệm vụ duy nhất của bạn là phân tích câu hỏi và trả về MỘT khối JSON hợp lệ theo cấu trúc:
{
  "operation": "sum | count | count_distinct | avg | argmax | argmin | top_k | percent_change | ratio | comparison | lookup | existence | table_report",
  "target_metrics": ["revenue", ...],
  "entities": ["tên thực thể hoặc điều kiện lọc"],
  "filters": [{"field_hint": "...", "operator": "=", "raw_value": "...", "is_having": false}],
  "group_by": ["customer | product | date | shift"],
  "top_k": null,
  "sort_order": "desc",
  "answer_type_hint": "number | percent | string | date | boolean | list | table"
}
Tuyệt đối không sinh câu lệnh SQL và không giải thích dài dòng.
```
* **Tại sao cấm sinh SQL?** Mục tiêu của tầng Grounding là làm rõ ý định và phạm vi dữ liệu, không làm thay việc của Planner. Cấm sinh SQL giúp mô hình 3B không bị phân tâm, phản hồi nhanh trong vòng < 200 token.

---

### 2.2. `_extract_json_dict(raw_text: str) -> dict[str, Any]`
Bộ lọc và xử lý chuỗi phản hồi thô từ LLM để đảm bảo tính an toàn tuyệt đối:
* **Loại bỏ khối suy nghĩ (`<think>...</think>`)**: Một số dòng mô hình reasoning hoặc thinking model có thể sinh ra thẻ `<think>`. Hàm dùng biểu thức chính quy `re.sub(r"<think>.*?</think>", "", raw_text, flags=re.DOTALL)` để cắt bỏ toàn bộ suy luận nội tâm.
* **Xử lý trường hợp thẻ `<think>` bị cắt cụt**: Nếu token sinh ra bị chạm trần và chưa kịp đóng thẻ `</think>`, hàm tự động cắt bỏ phần sau `<think>` để lấy nội dung hợp lệ phía trước.
* **Bóc tách JSON từ Code Block**: Dùng regex tìm kiếm khối ```json { ... } ``` hoặc cặp ngoặc nhọn ngoài cùng `{ ... }`.
* **Kiểm tra tính hợp lệ**: Gọi `json.loads()` và xác nhận kết quả bắt buộc phải là một `dict` của Python. Nếu mô hình trả về text rác, hàm ném `ValueError`.

---

### 2.3. `StructuredLLMParser`

#### Khởi tạo:
```python
def __init__(
    self,
    chat_fn: Callable[[str, str], str],
    *,
    token_count_fn: Callable[[str, str], int] | None = None,
    max_input_tokens: int = 3_584,
) -> None:
```
* **Mô hình lập trình hàm (Functional Dependency Injection)**: Thay vì phụ thuộc cứng vào thư viện `vllm.LLM` hay `transformers.pipeline`, lớp này chỉ cần một callable nhận `(system_prompt, user_prompt)` và trả về chuỗi text. Điều này cho phép:
  * Trong môi trường Production: Truyền vào hàm gọi vLLM Engine của model 3B với `temperature=0.0`.
  * Trong môi trường Unit Test: Truyền vào Fake Client trả về chuỗi JSON mẫu chạy tức thì trong 0.001 giây.

#### Phương thức `extract_intent(...)`:
```python
def extract_intent(
    self,
    question: str,
    as_of_date: str,
    available_metrics: Sequence[str],
    available_tables: Sequence[str],
) -> QuestionIntent:
```
* **Quy trình thực thi**:
  1. Ưu tiên metric/table liên quan, giới hạn tối đa 64 metric và 32 bảng, rồi serialize dạng JSON compact.
  2. Đếm token sau chat template. Với cấu hình 4096/512, factory dành 64 token an toàn và chỉ cho input tối đa 3520 token; nếu quá dài, bảng bị cắt trước rồi đến metric. Nếu riêng câu hỏi vẫn không vừa, request bị từ chối trước khi gọi model.
  3. Gọi `self._chat_fn` để lấy phản hồi từ mô hình 3B.
  4. Bóc tách JSON qua `_extract_json_dict()`.
  5. Ép kiểu an toàn sang các Enum:
     * `operation`: Ánh xạ sang `OperationKind`; giá trị ngoài allowlist bị từ chối.
     * `answer_type_hint`: Ánh xạ sang `AnswerTypeHint`; giá trị ngoài allowlist bị từ chối.
  6. Đóng gói danh sách `FilterCondition`, `normalized_question` và ép kiểu số nguyên an toàn cho `top_k`.
  7. Từ chối metric không có trong danh sách `available_metrics`; khi registry rỗng, dùng taxonomy metric built-in đóng thay vì cho model tự đặt tên metric.
  8. Trả về `QuestionIntent` với cờ `used_llm_fallback=True` và `confidence=0.85`; `QuestionIntentParser` tiếp tục kiểm tra tính đầy đủ semantic trước khi chấp nhận.

### 2.4. Khởi tạo Qwen 3B bằng vLLM

Factory `create_qwen3b_vllm_parser(config_path)` dùng `VLLMModel` chung của B0.3, nạp snapshot cục bộ và chuyển hai prompt thành hai `ChatMessage`. Import vLLM vẫn lazy nên import package trên máy CPU không cấp phát GPU.

Factory cũng lấy token count trực tiếp từ tokenizer/chat template của checkpoint. `max_input_tokens = max_model_len - max_new_tokens - 64`, nên model 3B vẫn giữ context 4096 thay vì tăng lên 32K chỉ để chứa registry không giới hạn.

```bash
uv sync --extra inference
```

```bash
uv run python scripts/download_model.py \
  --model-id Qwen/Qwen2.5-3B-Instruct \
  --output-dir .models/Qwen2.5-3B-Instruct
```

```python
from datamate.grounding import QuestionGroundingEngine

engine = QuestionGroundingEngine.from_qwen3b_vllm(
    "configs/qwen2_5_3b_grounding.toml"
)
```

`temperature=0.0` trong cấu hình giúp extraction ổn định. Engine/model phải được tạo một lần và tái sử dụng cho nhiều câu hỏi; không nạp lại weights theo từng request.

Output model được coi là dữ liệu không tin cậy: response có giới hạn kích thước; `operation`, `answer_type_hint`, `group_by`, filter operator, số lượng phần tử và độ dài chuỗi đều được validate theo allowlist trước khi tạo `QuestionIntent`.

Nếu model 3B và 9B cùng nằm trên một GPU, cần phân bổ lại `gpu_memory_utilization` của cả hai cấu hình hoặc dùng hai GPU. Cấu hình 9B hiện tại dùng `0.9`, nên không thể nạp thêm engine 3B `0.35` đồng thời trên cùng thiết bị mà không điều chỉnh.

Cấu hình BF16 này không dành cho GPU 4 GB: riêng weights 3B đã vượt ngân sách thực tế sau khi cộng KV cache và runtime vLLM. Giá trị `gpu_memory_utilization=0.35` nhắm tới GPU dung lượng lớn khi chia sẻ VRAM; nếu model 3B chạy độc lập trên GPU phù hợp, có thể tăng giá trị này sau khi đo VRAM thực tế.

---

## 3. Tại Sao Lại Thiết Kế & Code Như Vậy?

1. **Chiến lược Dual-Model ($\le 15\text{B}$)**:
   * Giới hạn của cuộc thi là tổng số tham số $\le 15\text{B}$.
   * Model 9B (`Qwen3.5-9B`) được dành trọn vẹn cho bài toán lập kế hoạch (Plan) và sinh DuckDB SQL chuyên sâu (Pha D) kèm vòng lặp sửa lỗi (Pha F).
   * Model 3B (`Qwen2.5-3B-Instruct`) được giao nhiệm vụ trích xuất thông tin (Information Extraction) ở cả Pha chuẩn bị dữ liệu B2 (đọc Rulebook) và Pha Grounding C1 (phân tích câu hỏi khó).
   * Tổng tham số: $3.09\text{B} + 9\text{B} = \mathbf{12.09\text{B} \le 15\text{B}}$, vừa an toàn tuyệt đối với quy chế, vừa tối ưu hóa năng lực chuyên môn của từng mô hình.
2. **Không để LLM quyết định các giá trị enum quan trọng mà không có phòng thủ**:
   * Giá trị enum ngoài allowlist làm lần fallback thất bại; bộ điều phối bắt lỗi và quay về kết quả rule-based kèm `LLM_FALLBACK_FAILED`.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Hỗ trợ `parser.py`**: Là phương án dự phòng đắc lực cho `rules_matcher.py`, giúp nâng cao độ phủ (Coverage) của hệ thống đối với các câu hỏi phức tạp hoặc câu hỏi hiếm gặp trong bộ dữ liệu Private Test.
* **Cung cấp dữ liệu chuẩn hóa cho C3 và C4**: Đầu ra vẫn là đối tượng `QuestionIntent` chuẩn mực, giúp các bước tiếp theo trong pipeline không cần quan tâm câu hỏi được parse bằng Regex hay bằng LLM 3B.

---

## 5. Nếu Không Có File Này Thì Sao?

* Nếu chỉ dựa vào Regex của `rules_matcher.py`, hệ thống sẽ bất lực trước những câu hỏi diễn đạt lắt léo (ví dụ: *"Mức độ đóng góp tương đối của tệp khách VIP vào giỏ hàng chung?"* hoặc *"Tỷ số giữa doanh số buổi trưa và buổi tối trong tuần vừa qua"*). Những câu này sẽ bị đoán sai phép toán dẫn đến toàn bộ câu truy vấn SQL phía sau tính đúng trên một kế hoạch sai.
