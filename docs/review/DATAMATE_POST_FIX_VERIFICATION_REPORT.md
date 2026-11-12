# Báo cáo kết quả sau khi sửa lỗi

> **Ngày:** 2026-11-11 · **Tham chiếu:** [DATAMATE_PIPELINE_LOGIC_AND_RUNTIME_REVIEW.md](file:///home/kiet97/uit-last-dance-aizalo26/docs/review/DATAMATE_PIPELINE_LOGIC_AND_RUNTIME_REVIEW.md)

## 1. Kết quả kiểm thử

| Hạng mục | Trước sửa | Sau sửa |
| :-- | :-- | :-- |
| `compileall src scripts` | OK | OK |
| `pytest -q` | 361 passed, 3 skipped | **381 passed, 3 skipped, 15 subtests passed** (~11 s) |
| Test hồi quy mới | – | 20 test trong [test_review_fixes.py](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_review_fixes.py) |
| `bash -n entrypoint.sh` | – | OK |

Thay đổi test cũ (có chủ đích): `test_parse_sql_block_inside_truncated_think` trước đây **yêu cầu** salvage SQL nháp trong `<think>` bị cắt; nay yêu cầu `Text2SQLParseError` (xem P2).

## 2. Trạng thái từng lỗi

| ID | Trạng thái | Cách sửa | Bằng chứng |
| :-- | :-- | :-- | :-- |
| P1 | **Đã sửa** | [parser.py](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/planner/parser.py): dùng AST sqlglot lấy `SELECT` ngoài cùng, `LIMIT` ngoài cùng, bỏ alias; không ép `list` khi là aggregate không `GROUP BY`; `MAX/MIN(cột ngày)` → `date` | CTE/subquery + LIMIT → `number` (trước: `list`); `EXTRACT(... FROM ...)` → `table` |
| P2 | **Đã sửa** | `<think>` chưa đóng ⇒ ném `Text2SQLParseError` (đi vào nhánh retry sẵn có); không quét JSON/SQL trong `raw_text` khi có thẻ think | Ca "SQL nháp trong thinking cắt cụt" nay raise |
| P3 | **Đã sửa** | Quét `{` bằng `JSONDecoder.raw_decode`, giới hạn 200 vị trí cuối; vẫn xử lý trailing comma | 3 000 dấu ngoặc: từ >60 s (không kết thúc) xuống ~1 ms |
| P4 | **Đã sửa** | `_evaluate_attempt` được bọc: lỗi bất ngờ ⇒ abstain `UNKNOWN_ERROR` + ghi attempt; `_pad_batch_results` chống `zip` cắt bớt; guard `outcome is None` | Test: executor ném lỗi → abstain; batch trả thiếu → đủ 3 dòng submission |
| D1 | **Đã sửa** | [Dockerfile](file:///home/kiet97/uit-last-dance-aizalo26/Dockerfile): bọc nháy các version spec | Test đọc Dockerfile |
| D2 | **Giảm thiểu** | [entrypoint.sh](file:///home/kiet97/uit-last-dance-aizalo26/entrypoint.sh): kiểm tra `config.json` của model trước khi chạy, thoát mã 2 với thông báo rõ | Đã xác nhận phần resolve đường dẫn; **chưa chạy Docker**. Weights vẫn phải được mount/COPY – không thể tự giải quyết trong repo |
| L1 | **Đã sửa** | Quote mọi định danh bằng `_q()` | Bảng `"don hang"` vẫn có `categorical_samples` |
| L2 | **Đã sửa** | Semi-join `DISTINCT … IN`, tối đa 300 cặp / 20 s; cạnh gắn `status="candidate"`, `cardinality="unknown"`, `confidence=0.5` | Test 2 bảng × 3 000 hàng trùng chạy <5 s |
| L3 | **Đã sửa** | Chỉ đổi sang `percent` khi projection là tỷ lệ (`/`, `100`, `percent/ratio…`) hoặc không có SQL | Câu đếm "…trên 10%?" → `number`; "Tỷ lệ…" → `percent` |
| L4 | **Đã sửa** | `load_context` log `warning/debug` thay vì `pass` | – |
| L5 | **Đã sửa** | `ctx.setdefault("schema_catalog", {})` | Test join discovery đọc `ctx["schema_catalog"]["join_graph"]` |
| L6 | **Đã sửa** | `run_questions` xóa `detailed_logs.jsonl` cũ khi không có submission để resume; script CLI xóa thêm thư mục `logs/` | Test stale log |
| L7 | **Đã sửa** | Thêm `AuditLogger.get_history()`, pipeline dùng API công khai | Test |
| L8 | **Chưa sửa** | Lệch Python 3.11 (base image) / 3.12 (`pyproject`) và `vllm` kéo torch khác – cần quyết định về base image | – |

## 3. Chưa thực hiện / lưu ý
- **Không gọi `SubmissionWriter.finalize()`** trong `run_pipeline_cli`: không rõ manifest/thay thế journal có ảnh hưởng `gate_trace`/logs; thay vào đó mỗi câu luôn có outcome (abstain khi lỗi), nên submission không còn bị thiếu câu do sập giữa chừng.
- **L8** và việc đóng gói model cần quyết định của bạn.
- Chưa chạy được Docker/vLLM/GPU, nên tác động lên điểm số thực tế chưa đo; chưa cài `ruff` nên chưa quét lint tĩnh.
- Việc từ chối SQL trong thinking bị cắt có thể tăng số câu `abstain/retry` (0 điểm) thay vì đoán (±1) – nên so sánh trên tập `train` có `answers.jsonl` để xác nhận.
- Đã tạm dùng `git stash` để thử test trên code cũ; đã khôi phục đầy đủ (không còn stash).

## 4. Tệp thay đổi
`src/datamate/planner/parser.py`, `src/datamate/pipeline.py`, `src/datamate/gate/audit.py`, `scripts/run_b0_pipeline.py`, `Dockerfile`, `entrypoint.sh`, `tests/test_b03_text2sql.py` (cập nhật 1 test), `tests/test_review_fixes.py` (mới).

