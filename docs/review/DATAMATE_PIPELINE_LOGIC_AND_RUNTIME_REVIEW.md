# Báo cáo rà soát Syntax, Logic Pipeline & Rủi ro Runtime

> **Ngày:** 2026-11-11 · **Phạm vi:** `src/datamate/` (pipeline, planner, execution, gate), `scripts/run_b0_pipeline.py`, `Dockerfile`, `entrypoint.sh`
> **Khác với** [DATAMATE_MODULAR_CODE_REVIEW_AND_QUALITY_AUDIT.md](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/DATAMATE_MODULAR_CODE_REVIEW_AND_QUALITY_AUDIT.md): tài liệu đó tập trung vào import thừa/refactor; tài liệu này tập trung vào **lỗi logic và rủi ro ảnh hưởng điểm số / khả năng chạy**. Các phát hiện đều được kiểm chứng bằng chạy thử, trừ khi ghi rõ "suy luận từ code".

---

## 1. Kết quả kiểm tra tự động

| Kiểm tra | Kết quả |
| :--- | :--- |
| `python -m compileall src scripts main.py` | **OK** – không có lỗi syntax |
| `pytest -q` | **361 passed, 3 skipped** |
| `pyflakes` / `ruff` | Không cài trong `.venv` → **chưa quét được** lỗi tĩnh/unused import |

**Kết luận:** Không có lỗi syntax. Test xanh, nhưng **không có test nào bao phủ các lỗi logic bên dưới** (các lỗi đều nằm ở heuristic/edge case mà test hiện tại không chạm tới).

---

## 2. Tổng hợp phát hiện

| ID | Mức | Vị trí | Tóm tắt | Tác động |
| :-- | :-- | :-- | :-- | :-- |
| P1 | **Cao** | [parser.py:206-208](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/parser.py#L206-L208) | Ép `answer_type="list"` bằng regex `LIMIT` trên toàn bộ SQL, kể cả trong CTE/subquery | Câu trả lời scalar bị đánh sai type → retry/abstain hoặc sai |
| P2 | **Cao** | [parser.py:72-77](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/parser.py#L72-L77), [471-495](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/parser.py#L471-L495) | Output bị cắt trong `<think>` vẫn lấy SQL **nháp** trong phần suy nghĩ để thực thi | Trả lời sai (−1) thay vì abstain (0); trái với comment ở dòng 405-406, 514-516 |
| P3 | **Cao** | [parser.py:324-332](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/parser.py#L324-L332) | Quét cặp `{…}` có độ phức tạp bậc 2 (gọi 2 lần) | Treo/chậm hàng giây khi output dài nhiều dấu `{}` (đúng ca thất bại) |
| P4 | **Cao** | [pipeline.py:403](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py#L403), [528-536](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py#L528-L536) | Không có bảo vệ ngoại lệ ở `_evaluate_attempt`; `zip` có thể cắt bớt kết quả batch → `outcome=None` | Một câu lỗi làm **sập cả lượt chạy**, mất các câu sau |
| D1 | **Cao** | `Dockerfile` (lệnh `RUN pip install`) | `pydantic>=2.7.0`, `pandas>=2.2.0`... không được bọc nháy → shell hiểu là **redirect** | Version constraint bị bỏ, tạo file rác `=2.7.0`; build không tái lập |
| D2 | Trung bình | `Dockerfile`, `configs/qwen3_5_9b.toml` | Model `../.models/Qwen3.5-9B` không được COPY vào image, `.dockerignore` không loại trừ nhưng thư mục `.models` không tồn tại trong repo | Container chạy offline sẽ `ModelLoadError` nếu BTC không mount model |
| L1 | Trung bình | [pipeline.py:82](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py#L82) | `DESCRIBE {tname}` không quote | Bảng có khoảng trắng/ký tự đặc biệt → mất toàn bộ `categorical_samples` âm thầm |
| L2 | Trung bình | [pipeline.py:100-128](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py#L100-L128) | Tự "khám phá" join bằng self-join `COUNT(*)` không timeout, gắn cứng `validated`/`many_to_one`/`0.9` | Có thể treo; đưa quan hệ sai vào prompt với nhãn tin cậy cao |
| L3 | Trung bình | [parser.py:227-230](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/parser.py#L227-L230) | Câu hỏi chứa `%`/"tỷ lệ" ép `number → percent` | Câu đếm "…trên 10%?" bị đổi thành percent |
| L4 | Thấp | [pipeline.py:129-130, 93-94](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py#L129-L130) | `except Exception: pass` toàn bộ `load_context` | Mất ngữ cảnh mà không có log |
| L5 | Thấp | [pipeline.py:97-128](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py#L97-L128) | `ctx.get("schema_catalog", {})` – nếu thiếu key, join phát hiện được ghi vào dict tạm rồi mất | Mất kết quả khám phá |
| L6 | Thấp | [pipeline.py:316, 571](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py#L316) / [run_b0_pipeline.py:448](file:///home/kiet97/uit-last-dance-aizalo26/scripts/run_b0_pipeline.py#L448) | `detailed_logs.jsonl` mở `"a"`; chỉ script CLI xóa file cũ, thư mục `logs/` không được xóa | Gọi `run_questions` trực tiếp ⇒ log trùng; `logs/` lẫn kết quả lần chạy cũ |
| L7 | Thấp | [pipeline.py:287, 536](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/pipeline.py#L287) | Truy cập thuộc tính private `writer.audit_logger._history` | Vỡ khi đổi AuditLogger |
| L8 | Thấp | `pyproject.toml` vs `Dockerfile` | `requires-python >=3.12` nhưng base image `pytorch:2.4.0` dùng Python 3.11; `requirements.txt` kéo `vllm>=0.17` ghi đè torch | Image rất nặng, hành vi khó dự đoán (code chạy được nhờ `PYTHONPATH`, không cài package) |

---

## 3. Chi tiết & bằng chứng

### P1 – Ép `answer_type` sai do regex `LIMIT` trên toàn câu SQL (Cao)
`normalize_answer_type` rule A dùng `re.search(r"\bLIMIT\s+([2-9]|\d{2,})\b", sql_upper)` trên **toàn bộ** SQL, còn `_extract_projection` lấy `SELECT` **đầu tiên** (thường là của CTE/subquery), không phải `SELECT` ngoài cùng.

Kết quả chạy thử:

| SQL | LLM khai báo | Kết quả `normalize_answer_type` | Đúng ra |
| :-- | :-- | :-- | :-- |
| `WITH top AS (SELECT ma_kh … LIMIT 5) SELECT SUM(dt) FROM top` | number | **list** | number |
| `SELECT SUM(x) FROM (SELECT x … LIMIT 3) s` | number | **list** | number |
| `WITH a AS (SELECT k, v FROM t) SELECT SUM(v) FROM a` (infer) | – | **table** | number |
| `SELECT MAX(ngay_ban) FROM t` (infer) | – | **string** | date |
| `SELECT EXTRACT(YEAR FROM ngay) AS y, SUM(dt) …` (infer) | – | **number** | table |

Các truy vấn "Top-N rồi tổng hợp" rất phổ biến trong bộ câu hỏi doanh nghiệp. Type sai ⇒ gate báo `SCALAR_SHAPE_MISMATCH`/`OUTPUT_TYPE_ERROR` ⇒ tốn 1 lượt retry hoặc abstain (mất điểm).
Ngoài ra `to_b05_generation_result` ([types.py](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/types.py)) gọi `normalize_answer_type` **lần thứ hai** (không có `question`) → hàm không idempotent.

**Đề xuất:** dùng AST sqlglot: lấy `SELECT` ngoài cùng (`parse_one(...).selects`), đếm số cột projection và `LIMIT` **của root** thay vì regex; chỉ override khi LLM khai báo mâu thuẫn rõ ràng với shape; chuẩn hóa type đúng 1 lần.

### P2 – Dùng SQL nháp trong thinking bị cắt cụt (Cao)
Ví dụ chạy thử (`<think>` mở, chưa đóng, trong đó có khối ```sql nháp):
```
TRUNC_THINK -> answerable  SELECT COUNT(*) FROM orders WHERE x = 1  number
```
Nguyên nhân: `strip_think_blocks` (dòng 72-77) khi gặp `<think>` chưa đóng vẫn cắt lấy từ code fence đầu tiên trong phần suy nghĩ; bước 2d (dòng 471-495) quét `raw_text` tìm "```sql". Hai chỗ này mâu thuẫn trực tiếp với comment ở dòng 405-406 ("TUYỆT ĐỐI không quét raw_text…") và 514-516 ("bảo vệ điểm thi").
Hệ quả: khi `finish_reason == "length"` (thinking budget 4096/8192 token trong `qwen3_5_9b.toml`), hệ thống thực thi bản nháp chưa chốt → rủi ro −1 điểm thay vì abstain/retry.

**Đề xuất:** nếu `<think>` chưa đóng ⇒ coi là không có đáp án (ném `Text2SQLParseError` để đi vào nhánh retry hiện có ở `pipeline.py`); không quét `raw_text` khi còn nằm trong thinking.

### P3 – Quét ngoặc `{}` bậc 2 (Cao)
`extract_json_contract_dict` thử `json.loads` cho mọi cặp (`{` bắt đầu, `}` kết thúc). Đo thực tế với chuỗi không có JSON hợp lệ:

| Số dấu ngoặc | Thời gian (1 lần gọi) |
| :-- | :-- |
| 100 | 43 ms |
| 200 | 168 ms |
| 400 | 700 ms |
| 800 | 2 791 ms |

Hàm bị gọi 2 lần (`visible_text` rồi `raw_text`), và `raw_text` chứa cả phần thinking (CoT thường có `{}` khi viết JSON nháp). Với ~3 000 ngoặc (thử nghiệm), tiến trình không kết thúc sau >60s. Đây chính là đường thất bại (không có JSON) nên chặn luôn luồng batch.

**Đề xuất:** dùng `json.JSONDecoder().raw_decode` từ từng vị trí `{` (tuyến tính theo số điểm bắt đầu), giới hạn độ dài/ số lần thử, và không quét lại `raw_text` nếu `visible_text` rỗng do bị cắt.

### P4 – Một lỗi làm sập cả lượt chạy (Cao)
- `answer_question` chỉ bọc `try/except` quanh `generator.generate/repair`. `_evaluate_attempt` (`to_b05_*`, `execute_query`, `evaluate_gate`, `record_attempt`) **không có bảo vệ**; mọi ngoại lệ không lường trước (ví dụ `AnswerSemantics(**…)` với giá trị không hợp lệ, `OutputWriteError`) lan thẳng lên `run_questions`, không câu nào phía sau được ghi và `run_b0_pipeline.py` không có resume.
- Chế độ batch: `zip(valid_for_gen, gen_results)` (dòng 403) và `zip(repair_needed, repaired_results)` âm thầm cắt nếu backend trả thiếu phần tử ⇒ `entry["outcome"]` còn `None` ⇒ `outcome.decision` ở dòng ~564 ném `AttributeError`.
- `SubmissionWriter.finalize()` (đảm bảo đủ `expected_ids`, validate) **không được gọi** trong `run_pipeline_cli` (chỉ `gate/cli.py` dùng). Không có cơ chế đảm bảo mọi `id` có dòng trong `submission.jsonl`.

**Đề xuất:** bọc mỗi câu hỏi trong `try/except Exception` → `_abstain_outcome(..., GENERATION_INVALID/INTERNAL)` + log; kiểm tra `len(results) == len(inputs)`; sau vòng lặp gọi `writer.finalize(outcomes, expected_ids=…)` hoặc ít nhất điền abstain cho id thiếu.

### D1 – Dockerfile: dấu `>=` bị shell hiểu là redirect (Cao)
```dockerfile
pip install ... duckdb==1.1.3 sqlglot==25.29.0 pydantic>=2.7.0 \
    pandas>=2.2.0 openpyxl>=3.1.2 pyarrow>=16.0.0 -r requirements.txt
```
Kiểm chứng: `echo pydantic>=2.7.0 pandas>=2.2.0` tạo ra file `=2.7.0` và `=2.2.0`. Trong image: pip nhận `pydantic`, `pandas`, … **không ràng buộc phiên bản**, stdout bị ghi vào file rác. Ngoài ra `duckdb==1.1.3` ghim cứng trong khi `requirements.txt` ghi `duckdb>=1.0.0` và `requirements-lock.txt` có thể khác phiên bản đã chạy test cục bộ ⇒ lệch môi trường (`SET lock_configuration`, `read_only` ... hành vi có thể khác).
**Đề xuất:** bọc nháy `"pydantic>=2.7.0"` hoặc bỏ dòng này vì đã có trong `requirements.txt`; build từ `requirements-lock.txt` để tái lập.

### D2 – Model không có trong image (Trung bình)
`entrypoint.sh` mặc định `CONFIG_FILE=/workspace/configs/qwen3_5_9b.toml` ⇒ `model_path=/workspace/.models/Qwen3.5-9B`, nhưng `Dockerfile` không `COPY` model, `.models` không có trong repo, `HF_HUB_OFFLINE=1`. `VLLMModel.load()` sẽ ném `ModelLoadError`. Nếu thể lệ BTC yêu cầu model đóng gói sẵn, cần COPY/mount; nếu mount ở nơi khác cần truyền `--model_path` (entrypoint đã hỗ trợ). *(Suy luận từ code; chưa chạy Docker.)*

### L1/L2 – `load_context` (Trung bình)
- Dòng 82 `DESCRIBE {tname}` không quote, trong khi các câu truy vấn khác đã quote. Chạy thử với bảng `"don hang"` ⇒ `categorical_samples` **không xuất hiện** trong context (lỗi bị `except Exception: pass` nuốt). Review cũ (M1) ghi "đã khắc phục" nhưng dòng này vẫn còn.
- Khám phá join (dòng 101-126): với mọi cặp cột có tên chứa `id/ma_/so_/sku/code/hd`, chạy `SELECT COUNT(*) … JOIN …` không giới hạn thời gian. Khi hai cột trùng lặp nhiều (many-to-many) kết quả bùng nổ theo tích Descartes. Mọi cạnh tìm được đều bị gán `status="validated"`, `cardinality="many_to_one"`, `confidence=0.9` – `prompt.py` chỉ lọc `status != "invalid"` nên các cạnh đoán này vào prompt như quan hệ đã xác thực (và `JoinGraphNavigator` chỉ chấp nhận `validated`).
- Chi phí chạy một lần mỗi bundle (có cache theo `bundle_key`), nhưng trên dữ liệu lớn có thể rất lâu.

**Đề xuất:** quote mọi định danh (dùng hàm `quote_ident`), thêm giới hạn (`LIMIT`/sample, timeout, `con.interrupt`), đánh dấu `status="candidate"` + confidence thấp, hoặc bỏ tính năng này nếu B0.1 đã có `join_graph`.

### L3 – Override `percent` theo từ khóa câu hỏi (Trung bình)
Chạy thử: `SELECT COUNT(*) … WHERE giam_gia>10` với câu hỏi *"Có bao nhiêu đơn giảm giá trên 10%?"* ⇒ `percent` (đáp án là số đếm). Từ khóa `%` quá rộng. Nên chỉ override khi projection thật sự là phép chia/tỷ lệ (`/`, `*100`) hoặc LLM đã khai báo.

### Các điểm thấp (L4–L8)
Xem bảng tổng hợp. Điểm đáng lưu ý: `except Exception: pass` ở `load_context` nên ít nhất `logger.warning`; `engine.py` cũng nuốt lỗi ở `on_timeout`/`con.close()` (chấp nhận được).

---

## 4. Những điểm đã kiểm tra và **không** thấy lỗi
- `ExecutionRequest(... db_path=bundle_path)` – `engine.execute_query` xử lý đúng thư mục có `data.duckdb`.
- Bounded retry: `max_retries=1`, `attempt` truyền đúng; nhánh all-NULL chỉ recoverable ở lần thử đầu.
- Sandbox DuckDB (read-only, `enable_external_access=false`, interrupt timer) và `validate_read_only_sql` (AST + fallback regex).
- `SubmissionWriter` chống ghi trùng theo `id`; `to_submission_dict` dùng `allow_nan=False`.
- `entrypoint.sh` truyền đúng tham số sang `run_b0_pipeline.py`.

---

## 5. Thứ tự ưu tiên đề xuất
1. **P4** (bọc lỗi từng câu + kiểm tra độ dài batch + finalize) – bảo vệ toàn bộ lượt chạy.
2. **D1** (sửa Dockerfile) và **D2** (xác nhận chiến lược model).
3. **P2 + P3** (parser: không dùng SQL nháp; quét JSON tuyến tính).
4. **P1 + L3** (chuẩn hóa answer_type bằng AST).
5. **L1/L2** (quote định danh, giới hạn khám phá join).
6. Bổ sung test hồi quy cho từng mục (các ví dụ ở mục 3 có thể dùng nguyên làm test case) và cài `ruff` để quét tĩnh.

> **Giới hạn:** chưa chạy Docker/vLLM/GPU nên D2 và tác động thực tế lên điểm là suy luận; chưa review sâu `grounding/`, `ingestion/`, `gate/validators.py|formatter.py`.

