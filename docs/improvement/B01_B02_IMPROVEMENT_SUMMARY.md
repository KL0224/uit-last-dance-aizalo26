# Tổng hợp các cải tiến B01 và B02

Cập nhật: 14/11/2026. Nhánh: `feature/dev-improvement`. Tài liệu dùng để bàn giao cho teammate: phân biệt phần đã chạy mặc định, phần LLM tùy chọn và kết quả đã kiểm chứng.

## 1. Hệ thống hiện xử lý gì?

```text
CSV / XLSX / SQLite + README / rulebook / calendar
                  ↓
B01: đọc, chuẩn hóa, lưu DuckDB, profiling toàn bảng
                  ↓
Schema Catalog: bảng, cột, grain, candidate keys, Join Graph
                  ↓
B02: rule nghiệp vụ, semantic metadata và binding
                  ↓
Business Context JSON → bàn giao cho Text-to-SQL / executor

Luồng tùy chọn:
  B01: README + schema → Qwen 3B → validator + SQL profiling → proposal chờ review
  B02: rule có nguồn + schema → Qwen 3B → evidence validator → enrichment riêng
```

Luồng mặc định không bắt buộc gọi LLM. LLM không trực tiếp sửa dữ liệu, tự xác nhận JOIN hay sinh SQL trả lời trong phạm vi các nâng cấp này.

## 2. B01 đã cải tiến như thế nào?

| Phần | Cải tiến | Ý nghĩa thực tế |
|---|---|---|
| Đầu vào | Nhận file CSV, XLSX, SQLite; sinh metadata thay vì yêu cầu nhập JSON thủ công | Teammate truyền thư mục business, nhận database và metadata |
| Chuẩn hóa và truy vết | Giữ raw, dữ liệu typed, mapping tên nguồn, lineage và quality issues | Có thể kiểm tra ngược file/sheet/dòng khi dữ liệu mơ hồ |
| Profiling | Kiểm row count, null/distinct, keys và tuple JOIN bằng SQL trên toàn bảng | Không kết luận uniqueness/coverage chỉ từ vài dòng mẫu |
| Khóa và JOIN | Có cơ chế composite keys, cardinality, coverage, cảnh báo fanout và reviewed evidence | Nhiều cột được kiểm theo tuple; overlap không tự thành quan hệ đáng tin |
| Bảo toàn dữ liệu | Không mặc định xem STT là mã đơn; giữ dòng mơ hồ có tiền/số lượng; sửa nhận diện dòng tổng quá rộng | Hạn chế xóa nhầm giao dịch hoặc thực thể hợp lệ |
| Cache | Fingerprint có mã nguồn B01/B02 và input/config liên quan | Thay logic không dùng lại metadata cũ ngoài ý muốn |
| Schema Advisor mới | Qwen2.5-3B đề xuất role cột/JOIN từ README và schema; kiểm nguồn và SQL độc lập | Hỗ trợ tìm và review quan hệ có evidence; chưa tự áp dụng |

### Sửa lỗi chuẩn hóa đã đo được

Parser release `1.1.2` sửa việc nhầm **Công tắc…** thành dòng **Cộng…**, và khách hàng **Tống Nam…** thành **Tổng năm…**. Đã khôi phục **528 dòng hợp lệ** ở bốn bảng của `biz_113`, `biz_117`, `biz_123`.

Trên cùng bộ 61 SQL review: trước sửa parser đúng **58/61**, sau sửa **61/61**. Đây là regression có chủ đích sau phát hiện lỗi, không phải holdout độc lập và **không phải mức tăng do LLM Schema Advisor**.

### B01 dùng LLM ở đâu?

Schema Advisor chạy sau preparation, nhận 1–4 bảng và tài liệu nguồn đã bind hash; prompt không chứa raw/sample rows, câu hỏi hoặc golden answers. Model đề xuất role và equi-JOIN; code kiểm bảng/cột, quote/line, conflict, composite key, coverage/cardinality/fanout trên DuckDB read-only.

Output là sidecar proposal. Có thể xuất manifest theo contract review hiện có, nhưng chỉ ở trạng thái `pending/unreviewed`. Review và verifier hiện có mới quyết định quan hệ có thể được tin cậy; proposal không tự chuyển `validated`.

Pilot thật trên hai bảng của `biz_123`: giữ 1 role `ma_hoa_don → order_id` và 1 JOIN đơn–chi tiết để review; loại 3 role vì trích dẫn không khớp. JOIN có coverage 100% hai phía, cardinality một–nhiều, nhưng **đã có trong catalog**. Số JOIN mới đã chứng minh: **0**. Quote đúng chỉ xác nhận nguồn tồn tại, chưa đảm bảo diễn giải ngữ nghĩa đúng.

## 3. B02 đã cải tiến như thế nào?

| Phần | Cải tiến | Trạng thái sử dụng |
|---|---|---|
| Rule và provenance | Giữ rule có ID/nguồn để đối chiếu README/rulebook | Hỗ trợ giải thích và audit |
| LLM semantic extraction | Có luồng đề xuất metric, JOIN, quy đổi kèm evidence | Metric/JOIN tổng quát vẫn cần review; runner Modal hiện tập trung quy đổi |
| Kiểm evidence | Kiểm quote/rule ID, bảng/cột, biểu thức và phương trình quy đổi | Không nhận proposal chỉ vì output JSON hợp lệ |
| Quy đổi đơn vị | Chỉ `source_verified` khi có mặt hàng, phương trình rõ, hệ số dương hữu hạn và biểu diễn DECIMAL phù hợp; kiểm mâu thuẫn | Có thể materialize các quy đổi đã qua kiểm nguồn |
| Enrichment | Publish bundle riêng, cập nhật DuckDB và cả hai metadata cùng hash | Baseline và dữ liệu gốc giữ nguyên |
| Fallback | Backend/JSON lỗi không nhận output dở dang; giữ baseline và trace lỗi | Không để output lỗi trở thành metadata thực thi |

Pilot Qwen2.5-3B trên README `biz_128`: **8/8 quy đổi đúng, không thừa**, đối chiếu tám phương trình nguồn. Bundle enriched có bảng `unit_conversions` gồm 8 dòng. Hai thử nghiệm trước không đạt đã bị từ chối; kết quả 8/8 không được suy rộng thành chất lượng B02 trên 30 business.

Metric có cột và SQL expression hợp lệ vẫn có thể là `review_required`; quote đúng không đủ xác nhận công thức nghiệp vụ. JOIN từ B02 không nâng trạng thái Join Graph của B01. LLM nhận định thiếu dữ liệu cũng không tự trở thành bằng chứng `unanswerable`.

## 4. Input/output để tích hợp

| Module / chế độ | Input | Output |
|---|---|---|
| B01 preparation | Thư mục business, README, rulebook, calendar, config nếu cần | Bundle `data.duckdb`, `source_manifest.json`, `foundation_metadata.json`, `normalization_report.json`, `business_context.json` |
| B01 Schema Advisor | Bundle ready + tài liệu khớp hash + nhóm bảng | Role/JOIN proposals, lý do reject, SQL statistics; manifest quan hệ pending khi export |
| B02 mặc định | Schema/profile và tài liệu/rules | Rule catalog, semantic metadata và Business Context |
| B02 LLM enrichment | Schema + rules có định danh nguồn + response model | Proposal có trạng thái; bundle enriched riêng cho quy đổi đủ evidence |

Database có schema `raw` để kiểm tra nguồn, `main` cho dữ liệu chuẩn hóa và `meta` cho truy vết/quality. JSON chỉ mang metadata và mẫu giới hạn; dữ liệu đầy đủ ở DuckDB. Contract bundle là `1.1`, có `normalized_data_handle`; mode metadata/contract cũ vẫn được giữ theo luồng tương thích hiện có.

Teammate Text-to-SQL dùng đúng tên bảng/cột catalog và DuckDB dialect. Executor mở database read-only và tự quản lý giới hạn truy vấn. Không xem candidate key, JOIN uncertain, rule descriptive hoặc proposal như guarantee đã được xác minh. Downstream hiện chưa tự consume sidecar Schema Advisor.

## 5. Kết quả kiểm chứng mới nhất

| Kiểm tra | Kết quả | Phạm vi kết luận |
|---|---:|---|
| Audit integrity | 30/30 business; 128 file dữ liệu | Đọc được, metadata/profile/lineage và SQL checks khớp |
| Dữ liệu release | 247 bảng gồm calendar; 3.981.887 dòng business | Không phải số câu trả lời đúng |
| Kiểm source dependencies gần nhất | 160 file khớp hash, trước/sau giữ nguyên | Không tính questions/answers vào nguồn business |
| B01 catalog release | 512 key candidates; 538 JOIN uncertain | Có candidate, chưa tự xác nhận quan hệ |
| B02 release mặc định | 4.128 descriptive rules; 116 heuristic metrics | Không đồng nghĩa tất cả compile được SQL |
| Golden trước/sau Advisor | 61/61 → 61/61, 0 câu thay đổi | Chứng minh không regression trên bộ SQL đã review |
| Golden inventory | 3.000 câu, có SQL review cho 61 câu/14 business | 2.939 câu chưa được chấm |
| Artifact sau replay Advisor | 30/30 bundle giữ nguyên hash | Advisor không sửa baseline |
| Tests | 484 passed, 3 skipped, 15 subtests passed | Bao gồm evidence, composite/fanout, preservation và evaluator coverage |

**Chưa có bằng chứng Schema Advisor làm tăng golden accuracy hoặc PA.** Hai nhánh kiểm chứng dùng cùng bundle bởi proposal chưa được áp dụng. Kiểm đủ 30 business không đồng nghĩa đã trả lời và chấm đủ 3.000 câu.

Các thử nghiệm LLM dùng Qwen2.5-3B-Instruct trên Modal, không gọi planner 9B hay chạy full pipeline. Ledger reservation hiện 5/15 USD cho các pilot B01/B02 đã ghi nhận; đây không phải billing đã đối chiếu. Lượt kiểm chứng golden gần nhất không gọi GPU mới.

## 6. File chính để teammate tra cứu

| File / nhóm | Vai trò |
|---|---|
| `src/datamate/ingestion/ingestion/readers.py` | Đọc nguồn |
| `src/datamate/ingestion/ingestion/normalization.py`, `preparation.py` | Chuẩn hóa, materialize và quản lý bundle |
| `src/datamate/ingestion/ingestion/profiling.py` | SQL profiling và tuple JOIN checks |
| `src/datamate/ingestion/schema_catalog.py`, `join_graph.py` | Schema Catalog, keys và quan hệ |
| `src/datamate/ingestion/relationship_evidence.py`, `ingestion/relationships.py` | Evidence và reviewed relationships |
| `src/datamate/ingestion/schema_advisor.py` | Đề xuất B01, validate và export pending review |
| `src/datamate/context/semantic_extractor.py`, `verified_semantics.py`, `semantic_experiment.py` | B02 extraction, kiểm chứng và enrichment |
| `src/datamate/context/rule_compiler.py`, `rule_resolver.py` | Compile/resolve rule có cấu trúc phù hợp |
| `scripts/modal_b01_advisor.py`, `modal_b02_semantics.py` | Runner pilot Qwen 3B |
| `scripts/audit_b01_b02_full.py`, `compare_b01_advisor_golden.py` | Audit toàn bộ và đối chiếu golden có reference |

## 7. Phần còn cần làm

1. Review quan hệ/role quan trọng bằng tài liệu hoặc constraint; tạo nhãn độc lập để đo precision/recall, giữ holdout.
2. Áp dụng proposal đã review vào bundle thử nghiệm riêng và tích hợp consumer; so sánh với baseline trước khi bật mặc định.
3. Mở rộng reference SQL cho business chưa phủ, công nợ, lô/hạn dùng, temporal/as-of, lợi nhuận và quy đổi. Không suy công thức từ đáp án golden.
4. Đo chất lượng semantic B02 ngoài pilot 8 quy đổi; bổ sung binding có bằng chứng thay vì coi rule descriptive là executable.
5. Đo điểm trả lời đủ 3.000 câu cần reference procedure đầy đủ hoặc luồng downstream riêng; chưa nằm trong kết quả B01/B02 hiện tại.

## Tài liệu và artifact liên quan

- [Evidence upgrade và pilot B02](B01_B02_EVIDENCE_UPGRADE.md).
- [Audit full dataset và lỗi parser đã sửa](B01_B02_FULL_AUDIT_REPORT.md).
- [B01 Schema Advisor: API và lệnh chạy](B01_LLM_SCHEMA_ADVISOR.md).
- [So sánh baseline/Advisor và coverage 3.000 golden](B01_ADVISOR_GOLDEN_VERIFICATION.md).

Artifact local không đưa lên Git: `artifacts/b01_b02_full/preparation_release.json`, `artifacts/b01_advisor/full_verification/integrity/audit.json`, `artifacts/b01_advisor/full_verification/golden_comparison.json`, cùng response Modal và enriched bundle được dẫn trong từng báo cáo. Teammate cần dataset/bundle local tương ứng để chạy lại.
