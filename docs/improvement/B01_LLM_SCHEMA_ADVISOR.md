# B01 — LLM Schema Advisor

Ngày: 14/11/2026. Đây là lớp hỗ trợ tùy chọn **sau preparation deterministic**, không phải model đọc/thay dữ liệu nguồn. Không chạy Grounding, B02 extraction, planner 9B hoặc full pipeline.

## Dùng LLM ở đâu và để làm gì?

```text
Bundle B01 đã ready + README/rulebook có hash
  → metadata request: tên SQL, tên gốc, kiểu cột, grain, số dòng, tài liệu đánh số dòng
  → Qwen2.5-3B + structured JSON
  → kiểm tra source/quote/line + binding bảng/cột
  → SQL full-table kiểm JOIN tuples, coverage, cardinality và cảnh báo fanout
  → b01 advice sidecar + relationships manifest PENDING
  → người review → luồng reviewed relationships hiện có → verifier B01
```

Có hai loại đề xuất:

- Vai trò ngữ nghĩa của cột: order/customer/product ID, ngày đặt/thu tiền, giá đơn vị, tiền dòng/đơn, số lượng, trạng thái, tên thực thể. Đây là annotation `review_required`, không phải parser override.
- Equijoin một hoặc nhiều cột: validator tái sử dụng `DuckDBProfileProvider.check_join()` trên toàn bảng. Đầu ra giữ `uncertain` và không mang trusted relationship attestation, kể cả overlap 100%.

Lợi ích là hỗ trợ đọc tên cột không đồng nhất và tài liệu để tạo **đề xuất có nguồn, có số liệu và có đường đi tới review**, thay vì chỉ gợi ý từ tên/overlap. Chưa chứng minh tăng recall JOIN hoặc PA toàn dataset.

## Interfaces

Module: `src/datamate/ingestion/schema_advisor.py`.

- `build_request(bundle, documents, tables)`: chọn 1–4 bảng business, chỉ nhận tài liệu khớp hash của input bundle. Request bind với hash DuckDB/Business Context; không gửi raw/sample rows, questions hoặc answers.
- `advise(bundle, documents, chat_fn, tables)`: API dependency injection dùng model đã được caller cấu hình. Lỗi backend/JSON trả `llm_failed`.
- `validate_response(bundle, request, response)`: kiểm schema/source binding, phát hiện đề xuất sai, trùng, role xung đột; SQL kiểm tuple JOIN. Không viết database hoặc catalog.
- `export_pending_review(...)`: ánh xạ tên SQL về file/sheet và tên cột nguồn bằng metadata có sẵn; xuất schema `ReviewedRelationships` 1.0. Chỉ xuất `pending/unreviewed`. Nguồn vật lý mơ hồ hoặc many-to-many được báo `blocked`, không chọn đại.

Trích dẫn có thật chỉ chứng minh nguồn tồn tại, chưa chứng minh model diễn giải đúng. Annotation role và JOIN đều cần review nghiệp vụ. Proposal không tự trở thành sự thật của B02/Text-to-SQL.

## Chạy

Chọn bundle release từ `artifacts/b01_b02_full/preparation_release.json`, rồi:

```bash
PYTHONPATH=src .venv/bin/python scripts/b01_schema_advisor.py \
  --bundle /path/to/prepared/biz_123/cache_key \
  --document data/train/data/biz_123/README.md \
  --table pos_don_hang_4deaa0c6 --table pos_chi_tiet_don_51f4fb5e \
  --output artifacts/b01_advisor/request.json

.venv/bin/modal run scripts/modal_b01_advisor.py \
  --request artifacts/b01_advisor/request.json \
  --output artifacts/b01_advisor/modal_constrained.json

PYTHONPATH=src .venv/bin/python scripts/b01_schema_advisor.py \
  --bundle /path/to/prepared/biz_123/cache_key \
  --document data/train/data/biz_123/README.md \
  --table pos_don_hang_4deaa0c6 --table pos_chi_tiet_don_51f4fb5e \
  --response artifacts/b01_advisor/modal_constrained.json \
  --output artifacts/b01_advisor/advice.json \
  --pending-relationships artifacts/b01_advisor/relationships.pending.json
```

Output không được nằm trong baseline bundle hoặc ghi đè tài liệu đầu vào. Không tự feed pending manifest vào preparation. Sau review có thể dùng `--relationships` của preparation hiện có; chỉ evidence approved/source-declared cùng SQL checks mới có thể cho JOIN validated. Không cần viết lại verifier.

## Giới hạn và bảo toàn dữ liệu

- Không tự sửa header, role parser, forward-fill, dedup, chuẩn hóa tiền/ngày hoặc grain từ lời model. Những thay đổi đó cần cấu hình và test riêng.
- Tối đa 12 đề xuất mỗi nhóm ở API; pilot GPU thu hẹp 4 roles/2 joins. Composite JOIN tối đa 4 cặp cột, không đánh giá FK theo từng cột riêng.
- Giới hạn input theo ký tự và token; không cắt tài liệu âm thầm. Pilot chỉ chọn hai bảng; không tuyên bố tìm đủ JOIN cho mọi bảng/business.
- Model chỉ dùng JSON Schema với tên bảng/cột và câu trích dẫn có thật trong input; validator vẫn kiểm độc lập quan hệ quote/line và binding.
- Dùng chung ledger reservation 15 USD của đợt B01/B02, timeout 900s, không retry tự động, cache gắn request/code/runner/model identity. Reservation không phải billing thực tế.
- Contract Business Context 1.0/1.1 và preparation mặc định giữ nguyên. Advisor sidecar là API mới, downstream chưa tự consume nó. Chuẩn bị lại bundle sẽ invalid cache theo code hash hiện có, không xóa bundle cũ.

Kiểm thử hiện tại: **482 passed, 3 skipped, 15 subtests passed**. Trong đó 16 tests mới cho advisor, gồm composite/cardinality/fanout, quote giả, source đổi, conflict, duplicate/reverse JOIN, fail backend, bảo toàn bundle và roundtrip pending không auto-validate.

Đối chiếu lại 61 golden SQL: **61/61**; kiểm hash artifact của **30/30 bundle** giữ nguyên. Đây là kiểm chứng không regression khi dùng sidecar read-only, không phải đo tăng điểm nhờ LLM.

## Pilot thực tế trên Modal

Đối chiếu baseline sau nâng cấp và inventory đủ 3.000 golden: [B01_ADVISOR_GOLDEN_VERIFICATION.md](B01_ADVISOR_GOLDEN_VERIFICATION.md). Chỉ 61 câu có reference SQL, không gọi kết quả này là chấm đủ 3.000 câu.

Chạy Qwen2.5-3B-Instruct với README và hai bảng đơn hàng/chi tiết đơn của `biz_123`; không chạy full pipeline hoặc model 9B.

- Lần đầu: 12 role và 1 JOIN đều bị validator loại do trích dẫn không khớp hoặc khóa lặp.
- Lần hai, sau khi ràng buộc JSON Schema theo tên bảng/cột và câu nguồn: chấp nhận 1 annotation `ma_hoa_don → order_id` để review; loại 3 role do trích dẫn không khớp. Việc quote có thật vẫn chưa đủ chứng minh role đúng về nghiệp vụ.
- JOIN đơn–chi tiết qua `ma_hoa_don`: 33.630 dòng đơn, 62.941 dòng chi tiết; coverage hai phía 100%, cardinality quan sát được `one_to_many`, có cảnh báo fanout. Cạnh đã có trong catalog, tiếp tục `uncertain`; không phải quan hệ mới được phát hiện hay tự động xác minh.
- Xuất được 1 quan hệ theo contract review hiện có, trạng thái `pending/unreviewed`. Baseline database và Business Context không thay đổi.
- Lần hai mất khoảng 113,7 giây trong hàm GPU, gồm khởi tạo model; 2.272 prompt tokens và 794 completion tokens. Đây không phải benchmark inference toàn hệ thống.

Artifacts local (không commit dữ liệu sinh): `artifacts/b01_advisor/modal_constrained.json`, `advice.json`, `relationships.pending.json`, `regression.json`. Hai lần chạy mới reservation tổng 2 USD; ledger chung hiện 5/15 USD, **không phải số tiền billing đã xác nhận**. Không chạy LLM toàn bộ 30 business. Chưa có bằng chứng tăng recall JOIN, chất lượng semantic role hay PA; cải tiến đã kiểm chứng là có luồng đề xuất B01, kiểm nguồn độc lập, SQL profiling và bàn giao review an toàn.
