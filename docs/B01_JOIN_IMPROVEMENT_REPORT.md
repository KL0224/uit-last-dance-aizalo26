# B01/B02 JOIN Improvement — Phase 0–5

Ngày kiểm tra: 07/11/2026. Đã thực hiện **Phase 0–5** trong
`khoi_docs/improvement_plan.md`, gồm đợt P0–P3 và yêu cầu tiếp tục P4–P5.

## Kết quả chính

| biz_123 | Baseline | Mới, không truyền review | Mới, có manifest review mẫu |
|---|---:|---:|---:|
| Bảng / dòng chuẩn hóa | 17 / 267.703 | 17 / 267.703 | 17 / 267.703 |
| Candidate keys | 47 | 47 | 47 |
| JOIN edges | 42 | 49 | 49 |
| validated / uncertain / invalid | 0 / 42 / 0 | 0 / 49 / 0 | 6 / 43 / 0 |
| Cảnh báo fanout | 40 | 45 | 45 |
| Đường khách → đơn → dòng → sản phẩm | Không có | Không có validated path | Có, 3 cạnh |
| B02 | 102 descriptive | 102 descriptive | 102 descriptive |

**Tự phát hiện không đồng nghĩa tự validated.** Sáu cạnh validated xuất phát từ
manifest review tường minh và đều qua SQL verification. Nếu không truyền manifest,
những quan hệ đó vẫn là uncertain. Không chỉnh sửa graph của bundle cũ.

## Phase → Code changes → Tests → Results → Remaining limitations

| Phase | Code changes | Tests / Results | Remaining limitations |
|---|---|---|---|
| 0 — Baseline | Đọc source, xác định extension points `SchemaCatalogBuilder.build`, `check_join`, `_relationships`, service và navigator/compiler | 68/68 tests trước sửa; reproduce 17 bảng, 47 keys, 42 uncertain. Viết hai regression tests sample rời nhau; cả hai fail trước sửa | Baseline không chứng minh chất lượng trả lời câu hỏi |
| 1 — Discovery | Tách nhánh SQL candidate generation; lọc theo tên/role/mapping, ưu tiên khóa parent, kiểm tra tuple toàn bảng; giữ inferred uncertain | Single/composite sample không giao nhau đều tìm được; tests NULL, low coverage, tên trùng không liên quan, accidental uniqueness, roles, source mapping và budget | Chưa có semantic matching cho mọi tên khác nhau; composite khác tên cần declaration |
| 2 — Evidence | `--relationships` / API `relationships`; resolve tên nguồn; approved review + hash/quote + scope + fingerprint; tái sử dụng validator; cache dependency; nguồn SQLite FK riêng | Positive/negative fixture và chạy thật biz_123; sai scope/hash/quote/mapping bị chặn, orphan/cardinality sai thành invalid, conflict bị chặn, pending không validated, cache hit/invalidation và source integrity pass | Manifest/metadata producer là trust boundary; hash không xác thực con người |
| 3 — Downstream | Reader contract không suy luận lại; `describe_path` trả status và cảnh báo theo hướng; consumer read-only dùng navigator/compiler hiện có | JSON roundtrip, composite predicate, reject unsafe status, graph shortcut uncertain không được chọn; actual path COUNT = reference EXISTS = **37.524** | Chưa là query planner; validated path vẫn có thể nhân SUM/COUNT nếu sai grain |
| 4 — B01/B02 smoke | Mở rộng consumer đọc RuleCatalog đã lưu, chọn bằng RuleResolver; thêm fixture preparation → binding → SQL, giữ nguyên core B02 | COUNT biz_123 = SQLite nguồn **37.524**; fixture doanh thu **330**, bằng SQL reference; descriptive/missing evidence và unsafe JOIN bị chặn | Luật thực tế chưa có binding/evidence vẫn không compile; COUNT không phải doanh thu |
| 5 — Regression/handoff | Audit thêm SQL keys/JOIN statistics/status, baseline schema/counts/profiles/B02; cập nhật handoff và báo cáo này | **93/93 tests**, **30/30 business**, **128/128 file**, **217 bảng**; 162 source hashes không đổi; Docker offline cold/warm pass; contract 1.0/1.1 pass | Không phải PA benchmark; inference/query planner vẫn ngoài phạm vi |

## Các file source thay đổi

| File | Vai trò thay đổi |
|---|---|
| `src/datamate/schema_catalog.py` | Candidate SQL không còn bị chặn bởi 5 samples; giới hạn tìm kiếm, lọc hằng số/role, ngăn cardinality declarations xung đột; legacy profile checker yêu cầu attestation |
| `src/datamate/ingestion/profiling.py` | Giữ SQL validator; bổ sung structured statistics, NULL counts, trust/scope gate và lý do kiểm chứng; cung cấp column roles từ mapping |
| `src/datamate/relationship_evidence.py` (mới) | Chính sách trust và fingerprint ràng buộc business, mapping composite, cardinality |
| `src/datamate/ingestion/relationships.py` (mới) | Đọc manifest, xác minh resource hash/quote, review status, resolve nguồn → SQL; không đoán mapping mơ hồ |
| `src/datamate/ingestion/preparation.py` | Nối manifest và resources vào cache, chống thay đổi nguồn trong build, cấp attestation từ SQLite FK, đưa declarations/roles vào pipeline |
| `src/datamate/contracts.py` | DTO `JoinStatistics`, `RelationshipEvidence`; hai field JOIN tùy chọn, bỏ khỏi output khi không có |
| `src/datamate/metadata_adapter.py` | Parse structured producer attestation; `BusinessContextSchemaReader` đọc graph đã có và kiểm tra claim validated |
| `src/datamate/context_service.py` | Truyền business scope vào schema builder |
| `src/datamate/join_graph.py` | Giữ `find_path`/predicate compiler; thêm `JoinPathResult`, `describe_path` và cảnh báo hướng JOIN/NULL/fanout |
| `src/datamate/__main__.py` | CLI `prepare --relationships` |
| `scripts/demo_join_graph.py` (mới) | Consumer mẫu đọc bundle, tìm path, compile predicate; COUNT read-only; đọc persisted B02 và báo thiếu binding/evidence thay vì tự tạo SQL nghiệp vụ |
| `scripts/audit_prepared_bundles.py` | Audit lại keys/JOIN bằng SQL; tùy chọn `--baseline-report` kiểm tra schema, row count, profiling và RuleCatalog; lưu counters trước/sau |

Tests mới: `test_join_improvements.py`, `test_downstream_join_graph.py`,
`test_business_context_integration.py`, helper `relationship_fixtures.py`.
Các fixture positive cũ trong `test_metadata_resolution`,
`test_composite_and_formulas`, `test_metadata_entrypoint` được bổ sung attestation
tường minh; vẫn giữ các assertions uniqueness/coverage/cardinality. Có negative
test riêng chứng minh evidence string legacy không còn cấp quyền validated.

## Thuật toán và điều chỉnh so với kế hoạch

Trước đây, cột cùng tên giống mã phải có overlap ≥80% trong tối đa 5 dòng mẫu mới
được SQL kiểm tra. Khách hàng và sản phẩm đều có overlap mẫu bằng 0 nên bị bỏ sót.

Luồng SQL mới: sinh ứng viên bằng cấu trúc → kiểm tra full-table tuples → chỉ giữ
cạnh có overlap khác 0 và coverage ≥80% ít nhất một chiều → xét trust riêng cho
declaration. Có tối đa **32 ứng viên/cặp bảng, 1.024 SQL checks inferred/business**;
ưu tiên parent key, có warning nếu cắt search; declarations không chịu giới hạn này.
Money/quantity/date/boolean/status roles không làm single-key proposals. Không có
business ID, tên bảng hash hay mapping biz_123 trong source production.

Trong kiểm tra role mapping đã phát hiện `IDCuaHang` hằng số làm sinh 136 cặp bảng
vô ích. Đã thêm regression test trước khi lọc identifier hằng số cả hai phía. Cũng
loại các cạnh mã chi nhánh hằng số. Quan hệ một giá trị thực sự cần declaration;
catalog ghi warning, không âm thầm giả định chúng không thể liên kết.

Contract vẫn dùng 1.0/1.1 và nhận cấu trúc input cũ. Thay đổi policy có chủ đích:
evidence string đơn lẻ không còn đủ để validated. Producer cũ cần attestation để
xác minh; strict downstream reader từ chối persisted validated claim thiếu proof.
Không đổi thuật toán B02 hoặc tự compile 102 luật mô tả.

## Các quan hệ cốt lõi và evidence

| Quan hệ theo tên nguồn | Bằng chứng SQL toàn bảng | Không review | Có review mẫu |
|---|---|---|---|
| don_hang → khach_hang, MaKhachHang | 300/300 mã con; parent 300 mã unique; 13.544 dòng con NULL | uncertain | validated |
| chi_tiet_don → san_pham, MaHangHoa | 80/80 mã con; parent 80 mã unique | uncertain | validated |
| chi_tiet_don_lo → lo_hang, MaLo | 2.950/2.950 mã con; parent 2.953 mã unique; 3 lô chưa tham gia phân bổ | uncertain | validated |
| chi_tiet_don → don_hang, MaHoaDon | 33.630/33.630 mã đơn con, parent unique | uncertain | validated |
| thanh_toan → don_hang, MaHoaDon | 33.266/33.266 mã đơn con, parent unique; không yêu cầu đơn nào cũng đã thu tiền | uncertain | validated |
| chi_tiet_don_lo → chi_tiet_don, (MaHoaDon, SoThuTu) | 62.288/62.288 tuple con, parent 62.941 tuple unique | uncertain | validated |

Manifest: `examples/relationships/biz_123.json`; tài liệu chứng cứ:
`examples/relationships/biz_123_review.md`. Đây là **review kỹ thuật của Codex** dựa
trên README và source schema, không giả danh teammate review. Tài liệu ghi rõ
mapping nào được README mô tả và mapping nào là kết luận review schema POS.
Manifest được truyền rõ qua CLI, không tự áp cho business mới.

Nguồn trust phân biệt `sqlite_foreign_key` và `reviewed_relationship`; inferred
không có semantic attestation. Pipeline kiểm tra approved status, reviewer, scope,
resource SHA-256 và quote trong resource; fingerprint ràng buộc đúng mapping và
cardinality. SQL tiếp tục kiểm chứng tuple uniqueness, directional coverage và
shape. Structured statistics tách riêng evidence ngữ nghĩa.

## Kiểm chứng và runtime

- **93/93 tests pass** với `DATAMATE_TRAIN_DIR=data/train`, gồm 68 tests baseline.
- Ruff check/format cho `src/datamate`, tests, consumer/audit/benchmark scripts pass; `git diff --check` pass.
- Cả hai preparation mode ready; samples ≤5/bảng; 102 luật vẫn descriptive.
- **17/17 bảng main trùng baseline**, đối chiếu `EXCEPT ALL` hai chiều, bao gồm số
  lần xuất hiện của mỗi dòng. SHA-256 SQLite và README nguồn trước/sau trùng nhau.
- Fixture SUM đơn gốc 300: JOIN dòng bán =400, JOIN thanh toán =400, JOIN cả hai
  nhánh =600. Composite phân bổ trả 4 dòng; chỉ JOIN mã đơn trả 7 dòng. Warnings
  theo hướng JOIN được kiểm tra; planner vẫn chịu trách nhiệm preaggregation.
- COUNT đường JOIN thực tế **37.524**, bằng reference SQL dùng các EXISTS độc lập;
  đây là kiểm tra cấu trúc INNER JOIN, không phải doanh thu hoặc PA benchmark.
- Cold preparation: không review **14,704 s**, có review **14,712 s**; wall process
  khoảng 14,9 s; peak RSS tương ứng **191,5 / 218,1 MiB** (`/usr/bin/time -v`).
  Hai process chạy đồng thời, DuckDB mỗi process 2 threads/512MB. Warm API lần đo:
  **0,030 / 0,024 s**, đều cache hit. Không suy ra tăng tốc so với benchmark cũ
  vì điều kiện đo khác. Kết quả toàn train mới ở bên dưới.

Bundles cuối trong `data/join-improvement/biz_123/`:

- Không review: `a5eebd6a1271b397585963dd330d981fbc7a908ad2f18c7cb5232b930b558cfb`.
- Có review: `c3cc4e640164390ffd6e73e131c69b1d17792a4210ef10ddb9c1853a346318fc`.

## Tái lập và bàn giao

```bash
DATAMATE_TRAIN_DIR=data/train PYTHONPATH=src .venv/bin/python -B -m unittest discover -s tests -q
PYTHONPATH=src .venv/bin/python -B -m datamate prepare \
  --business-dir data/train/data/biz_123 \
  --rulebook data/train/rulebook.md --calendar data/train/calendar.csv \
  --relationships examples/relationships/biz_123.json --output-dir data/join-improvement
PYTHONPATH=src .venv/bin/python -B scripts/demo_join_graph.py \
  --bundle <bundle_dir-vừa-trả-về> --source khach_hang --target san_pham --count-rows \
  --rule-topic 'Doanh thu một đơn' --industry 'Nhà thuốc'
```

Không có manifest: bỏ `--relationships`; consumer trả `no_validated_path`, SQL null.
Teammate đọc [handoff](B01_B02_HANDOFF.md#khai-báo-reviewed-relationships-và-dùng-join-graph)
để biết schema manifest, attestation, thống kê và API reader/navigator/compiler.

## Phase 4 — B01/B02 tích hợp và SQL reference

Consumer `run_demo()` đọc schema và `rule_catalog` từ cùng Business Context JSON,
dùng `RuleResolver` theo business/industry/topic. Trên biz_123, luật doanh thu vẫn
descriptive: output `missing_binding_or_evidence`, `sql_fragment: null`; không thay
đổi 102 luật trong bundle. Nếu producer đã cấp structured validated rule, consumer
chỉ compile fragment, không tự áp filter hay thực thi phép tính nghiệp vụ.

Đường JOIN reviewed trả 37.524 dòng, bằng SQLite nguồn read-only dùng reference:

```sql
SELECT COUNT(*) FROM (SELECT DISTINCT * FROM chi_tiet_don)
WHERE MaHangHoa IN (SELECT MaHangHoa FROM san_pham)
  AND MaHoaDon IN (
    SELECT MaHoaDon FROM don_hang
    WHERE MaKhachHang IN (SELECT MaKhachHang FROM khach_hang)
  );
```

`DISTINCT *` đối chiếu quy tắc xuất trùng, không dedup theo một cột hoặc loại sự
kiện khác nhau. Đây là COUNT liên kết các dòng có khách, không phải tổng shop.
Không review thì consumer trả `no_validated_path`, không tự sinh JOIN.

Fixture SQLite thật khai báo FK → preparation → persisted JSON → RuleResolver →
RuleTemplateBinder → compiler → DuckDB read-only. Evidence do test caller cung cấp
cho relation/filter cụ thể: tháng 06/2026, loại cancelled/returned và mọi đơn có
phiếu trả (kể cả phiếu tháng 07), giữ delivering, không nhân grain dòng bán.
SUM theo fragment = reference chỉ chọn đơn hợp lệ `o1/o5` = **330**. Tests chặn
descriptive rule, thiếu semantic evidence, unsafe JOIN, topic không có và catalog
khác business. Test auditor còn sửa statistics trong bundle fixture và xác nhận
audit thất bại; bundle/source thật không bị sửa.

## Phase 5 — Regression toàn train

Chạy mới toàn bộ 30 business, **không truyền manifest review**, 4 process workers:

| Kiểm chứng | Kết quả |
|---|---|
| Preparation / SQL audit | **30/30 ready, 30/30 audit pass** |
| Nguồn dữ liệu | **128/128 file**: 20 CSV, 107 XLSX, 1 SQLite; mọi file có trạng thái |
| Schema và row count | **217 bảng, 3.983.919 dòng chuẩn hóa**, khớp baseline từng bảng |
| Profiling và B02 | **30/30 khớp nguyên baseline**; kiểm chứng lại NULL/distinct/lineage bằng SQL |
| Raw / source rows | 3.997.042 / 3.997.002; 40 footer và 13.083 export duplicates như baseline |
| Source integrity | **162/162 file SHA-256 trước/sau trùng nhau** |
| Cache | 30/30 cold miss; 30/30 warm hit, cùng key cold/warm |
| Keys | **480 candidate**, bằng baseline; SQL uniqueness/null checks pass |
| JOIN mặc định | **538 uncertain**, so với 116 cạnh baseline; **0 validated**, không tự cấp trust |
| Fanout / search cap | 500 cạnh có warning; không business nào chạm cap 32/1.024 |
| Contract | CLI metadata legacy 1.0, dataset 1.1 và JSONMetadataProvider đọc artifact 1.1 pass |

Số cạnh tăng thể hiện recall ứng viên cấu trúc, **không chứng minh 538 quan hệ đều
đúng nghiệp vụ**. Kết quả 6 validated của biz_123 chỉ có trong lượt review tường minh
riêng; không tính vào 538 cạnh của regression mặc định. Audit kiểm tra statistics
và status, không tự ghi trạng thái mới vào bundle.

| Mỗi business, 4 workers | Min | Median | Max |
|---|---:|---:|---:|
| Cold preparation | 2,881 s | 46,499 s | 116,112 s |
| Warm preparation | 0,005 s | 0,014 s | 0,030 s |
| Peak RSS cold | 109,3 MiB | 188,1 MiB | 295,4 MiB |

biz_123 cold mới: **19,057 s / 207,3 MiB**, 17 bảng/267.703 dòng/47 keys/49 uncertain.
Timer worker bắt đầu sau import; RSS là toàn process. Baseline cũ chạy 8 workers,
lượt này 4 workers: không suy diễn tăng tốc từ hai điều kiện đo khác nhau.

### Docker/offline

Image `datamate:join-p5` build thành công bằng Dockerfile hiện có, `uv sync --frozen`.
Build không mạng ban đầu không tải được wheel; build có mạng thành công. Không
khẳng định Docker build lần đầu offline; **runtime cold/warm đều offline**:

- `--network none --read-only --user <uid>:<gid> --memory 1g --cpus 2`.
- `/input` và `/reviews` mount read-only, `/output` writable, `/tmp` là tmpfs.
- Cold ready, warm cache hit; 17 bảng/267.703 dòng, 6 validated/43 uncertain.
- Host consumer đọc được bundle container, COUNT 37.524 và chặn descriptive B02.
- Wall container cold/warm **21,427 / 0,911 s**, gồm startup; không so với timer API.
- SQLite nguồn giữ nguyên hash. Không đổi Dockerfile hoặc dependencies.

### Artifacts và tái lập regression

Artifacts máy có tại `data/` (gitignore): `join-integration-smoke.json`,
`join-contract-check.json`, `join-docker-smoke.json`, `join-improvement-regression.json`,
`join-improvement-regression-audit.json`. Native bundles: `data/join-full-regression/`;
Docker bundles: `data/docker-join-p5/`. Báo cáo này lưu bản tổng hợp để teammate đọc
khi không có dataset/cache cục bộ.

```bash
# Dùng output-dir mới để đo cold, không dùng lại cache đã có.
PYTHONPATH=src .venv/bin/python -B scripts/benchmark_preparation.py \
  --train-dir data/train --output-dir <output-moi> \
  --report data/join-improvement-regression.json --jobs 4
PYTHONPATH=src .venv/bin/python -B scripts/audit_prepared_bundles.py \
  data/join-improvement-regression.json \
  --baseline-report data/b01-preparation-validation.json
```

Baseline-report cần các baseline bundles còn tồn tại; bỏ tùy chọn này chỉ bỏ phần
so sánh snapshot cũ, audit metadata/SQL hiện tại vẫn chạy. Không bỏ qua lỗi test
hoặc điều chỉnh assertions để ép pass.

## Giới hạn còn lại

Semantic matching từ README, temporal/polymorphic joins, chứng thực reviewer,
fanout-safe query planning và tự xác định business grain vẫn ngoài phạm vi. Nhiều
grain còn unknown; full coverage không chứng minh semantic completeness. Cần team
review manifest trước khi coi đây là chính sách quan hệ đã được cả team chấp thuận.
Chưa có LLM/Text-to-SQL/executor/formatter hoàn chỉnh hoặc kết quả PA benchmark.
