# Nâng cấp B01/B02 bằng bằng chứng nguồn

Ngày: 14/11/2026. Phạm vi: preparation và semantic metadata; không chạy full pipeline, Grounding, model 9B hoặc tạo submission.

## Luồng xử lý

```text
CSV / XLSX / SQLite + README + rulebook
  → B01 deterministic → bundle baseline (DuckDB + catalog + profiling)
  → B02 deterministic
  → Qwen2.5-3B (tùy chọn, chỉ nhận schema + các rule có định danh nguồn)
  → kiểm tra trích dẫn, bảng/cột, biểu thức, phương trình quy đổi
  → proposals cần review / quy đổi đủ bằng chứng
  → bundle enriched riêng, giữ nguyên baseline và nguồn
```

### B01 thay đổi gì?

- Không coi `STT` mặc định là mã đơn. Description ghi rõ mã đơn vẫn được nhận diện.
- Không loại dòng chỉ vì thiếu mã/tên nhưng có tiền/số lượng. Giữ dòng và ghi `ambiguous_subtotal`; dòng tổng có nhãn rõ vẫn theo quy tắc cũ.
- Parser version `1.1.0`; cache fingerprint bao gồm code B01 và B02 để tránh dùng lại metadata khi logic semantic thay đổi.

### B02 dùng LLM như thế nào?

- Model đề xuất metric, JOIN và quy đổi; mỗi đề xuất cần `evidence.rule_id` và `evidence.quote` khớp rule nguồn. Rule giữ `source` để truy vết README/rulebook.
- Metric có cột và SQL expression hợp lệ vẫn là `review_required`: trích dẫn đúng chưa chứng minh công thức đúng. Không ghi đè metric deterministic.
- JOIN tồn tại trong schema vẫn chỉ `candidate`; không nâng trạng thái của B01 Join Graph.
- Nhận định thiếu capability từ LLM không thành bằng chứng `unanswerable`.
- Quy đổi chỉ thành `source_verified` khi trích dẫn chứa tên mặt hàng và phương trình `1 đơn vị = hệ số đơn vị`; hệ số dương hữu hạn, không mâu thuẫn, biểu diễn được bằng `DECIMAL(38,12)`.
- Các proposal và lý do bị từ chối nằm ở `semantic_catalog.proposals`. JSON lỗi dùng baseline và ghi warning/raw output trong artifact thử nghiệm.
- Publisher kiểm tra lại evidence trên rule của baseline, copy baseline sang bundle mới, thêm bảng quy đổi và cập nhật cả Business Context/Foundation Metadata; không sửa database baseline.

Các trường mới là tùy chọn; contract 1.0/1.1 và các metric có sẵn vẫn đọc được. Consumer cần phân biệt proposal với metadata có thể dùng; `source_verified` chỉ chứng minh quy đổi có trong tài liệu, không chứng minh toàn bộ truy vấn nghiệp vụ đúng.

## Chạy kiểm chứng local

```bash
PYTHONPATH=src .venv/bin/python scripts/verify_b01_b02.py \
  --cases examples/b01_b02/golden_checks.json
```

Output mặc định: `artifacts/b01_b02/report.json`, `bundles/`, `requests_all.json`.

Các SQL trong fixture được viết/rà soát theo câu hỏi, README và rulebook trước khi so đáp án. Chúng kiểm tra tổng tiền phiếu nhập theo kỳ trên `biz_123`, `biz_128`, `biz_105`; không phải LLM-generated SQL. Đáp án chỉ được đọc bởi evaluator. Đây là regression có chủ đích, không phải benchmark holdout hoặc điểm PA toàn hệ thống.

## Pilot Modal chỉ B02

```bash
.venv/bin/modal run scripts/modal_b02_semantics.py \
  --request artifacts/b01_b02/request.json \
  --output artifacts/b01_b02/modal_structured.json
```

`request.json` là tập packet đã lựa chọn (schema + rule, không questions/answers). Không đưa toàn bộ `requests_all.json` vào pilot: runner chỉ nhận tối đa 8 packet/lần. Chunking giữ nguyên record và báo lỗi với record quá lớn; tích Descartes schema/rule có thể tạo nhiều packet và phải được chọn theo mục tiêu thử nghiệm.

Runner chỉ load Qwen2.5-3B trên A100; dùng weights đã có ở Modal Volume. Timeout 900 giây, không tự retry. Có ledger reservation bảo thủ; tối đa 15 USD cho đợt, đây không phải số tiền billing thực tế. Build image và xác minh metadata có thể có thêm chi phí CPU. Không có bảo đảm PA tăng từ pilot này.

Enrichment sau khi có output thật:

```bash
PYTHONPATH=src .venv/bin/python scripts/verify_b01_b02.py \
  --cases examples/b01_b02/golden_checks.json \
  --modal-result artifacts/b01_b02/modal_structured.json
```

Baseline deterministic là mặc định. Chưa tự bật LLM trên toàn dataset; chưa fine-tune hay thay đổi B03–B05.

## Kết quả thực chạy của đợt này

### B01 và golden answers

- Dựng lại độc lập ba business train: `biz_123` (SQLite), `biz_128` và `biz_105` (XLSX). Không chạy full pipeline.
- Catalog baseline có lần lượt 18 / 26 / 6 bảng (có calendar); tên bảng khớp database.
- Preparation cold của ba business trong lượt đối chiếu: 240,24 giây. Chưa đo peak memory bằng profiler chuyên dụng.
- **9/9 câu tiền nhập hàng theo tháng khớp `data/train/answers.jsonl`**, trước và sau enrichment. Đây là kiểm tra một nhóm phép tính, không chứng minh mọi metric đều đúng.
- Hash của 18 file nguồn (gồm README) giữ nguyên khi kiểm tra lại.

Chi tiết SQL và kết quả: `artifacts/b01_b02/report.json`, `artifacts/b01_b02/comparison.json`; fixture review được commit cùng code ở `examples/b01_b02/golden_checks.json`.

### Qwen 3B trên Modal

Cùng một packet tám phương trình từ README `biz_128`, không dùng golden answers:

| Lần thử | Kết quả | Quyết định |
|---|---|---|
| Prompt cũ có ví dụ nghiệp vụ | Sao chép ví dụ Ống PVC, thiếu evidence | Không nhận đề xuất nào vào metadata thực thi |
| Prompt tổng quát không có ví dụ nghiệp vụ | JSON có trailing comma và bị cắt, còn lẫn metric/quy đổi | Fallback baseline, không cứu JSON hoặc nhận output dở dang |
| Task chỉ quy đổi + JSON Schema | **8/8 đúng, không thừa**, đối chiếu tám phương trình nguồn | Publish bundle enriched riêng |

JSON Schema dùng public API `StructuredOutputsParams` của [vLLM](https://docs.vllm.ai/en/v0.31.0/features/structured_outputs/). Đây là ràng buộc cấu trúc; evidence validator vẫn kiểm tra nội dung độc lập. Runner Modal hiện cố ý chỉ hỗ trợ pilot quy đổi đơn vị; trích metric/JOIN tổng quát vẫn là đề xuất cần review, chưa được chứng minh hoạt động hiệu quả trên model thật.

- Model: `Qwen/Qwen2.5-3B-Instruct`, cached revision `aa8e72537993ba99e69dfaafa59ed015b17504d1`.
- Lần chạy structured: [Modal app](https://modal.com/apps/geminiveo4ai57/main/ap-zECqzpdWMziioApPTWLADO), function call `fc-01M7AYMPYZ0BSTSM9MYWGHBKMY`, thời gian trong function khoảng 81,37 giây (gồm load/compile).
- Output thật: `artifacts/b01_b02/modal_structured.json`; raw output của hai lần thử trước cũng được giữ để audit.
- Bundle enriched: `artifacts/b01_b02/enriched/biz_128/63763349361c81199414b752f3e52552bcd5311b2ff6d39cb2d204eb105a2d80/`.
- Enriched có 27 bảng main, trong đó `unit_conversions` có 8 dòng. Business Context/Foundation Metadata cùng mô tả bảng mới; artifact hashes hợp lệ; B01 Join Graph giữ nguyên.

### Chi phí và cache

- Ba lần gọi GPU đã đặt reservation tổng cộng **3 USD / trần 15 USD**, không phải billing đã xác nhận. Có một lần dựng image rồi dừng trước khi gọi GPU do lỗi tìm CLI; đã sửa dùng đúng Python environment. Chi phí CPU build chưa được đối chiếu billing.
- Đã xác nhận các app thử nghiệm đều stopped và không còn GPU task.
- Ledger dùng một đường dẫn chung của project và khóa khi ghi để tránh vượt trần do chạy đồng thời. Cache-result key gồm request, code, lock/config và model identity đọc bằng CPU; cache hit không dispatch GPU. Cache và budget được kiểm thử bằng fake remote, không đốt credit để test lại.

### Giới hạn còn lại

- Chưa regression lại toàn bộ 30 business; chưa đánh giá 120 câu, chưa có holdout business độc lập. Không báo tăng PA.
- Chưa kiểm chứng đủ metric doanh thu, giá vốn, công nợ, temporal/as-of hoặc mọi phép JOIN bằng golden answers.
- Bộ SQL review hiện tập trung tiền nhập hàng; nó không sử dụng bảng quy đổi, nên 9/9 chỉ chứng minh không regression nhóm câu đó sau enrichment. Chất lượng quy đổi được đo riêng bằng README, không đánh tráo thành điểm trả lời câu hỏi.
- Không tự bật semantic LLM trên mọi business. Baseline deterministic tiếp tục là mặc định.

Kiểm thử cuối đợt: **459 passed, 3 skipped, 15 subtests passed**; thêm 26 tests cho evidence, retention, cache, atomic metadata/hash và giới hạn ngân sách.

Cập nhật sau đợt audit toàn dataset: xem [B01/B02 Full Audit Report](B01_B02_FULL_AUDIT_REPORT.md). Parser release hiện là **1.1.2**; đã kiểm 30 business / 128 file và 61 golden cases. Những giới hạn “chưa regression 30 business” ở trên mô tả thời điểm pilot trước, không phải trạng thái mới nhất.
