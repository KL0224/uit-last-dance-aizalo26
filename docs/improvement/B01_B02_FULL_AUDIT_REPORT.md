# Audit toàn bộ B01/B02 và đối chiếu golden data

Ngày: 14/11/2026. Chỉ chạy CPU local, không gọi Modal/GPU, không chạy Grounding, planner 9B, executor pipeline hay submission. SQL kiểm chứng được viết và review theo README/rulebook, không do LLM sinh.

## Kết quả bản release parser 1.1.2

| Hạng mục | Kết quả |
|---|---:|
| Business chuẩn bị / audit integrity đạt | 30 / 30 |
| File dữ liệu có trạng thái đọc | 128 ({'.csv': 20, '.xlsx': 107, '.sqlite': 1}) |
| File đầu vào hash trước/sau | 162; giữ nguyên: True |
| Bảng chuẩn hóa, gồm calendar tham chiếu | 247 |
| Dòng business sau chuẩn hóa, không cộng calendar | 3,981,887 |
| Golden đúng / kiểm chứng | 61 / 61 |
| Business có SQL golden kiểm chứng | 14 / 30 |
| Peak RSS cao nhất mỗi worker cold | 387.5 MiB |
| Tổng thời gian các lượt cold | 2688.37 s |
| Tổng thời gian các lượt warm | 0.64 s |

Benchmark chạy 8 worker. Thời gian cold/warm trên là cộng thời gian từng business, **không phải wall time chạy song song**. Tất cả cold cache miss, warm cache hit. Kiểm tra final không có integrity finding: `[]`.

## Lỗi thật đã tìm được và sửa

Lượt đầu integrity đã đạt 30/30 và 58 câu golden đều đúng, nhưng control totals so baseline phát hiện dữ liệu thật bị loại:

1. Tiền tố bỏ dấu `cong ` nhầm tên hàng **Công tắc…** thành dòng **Cộng…**. Ảnh hưởng sổ bán `biz_113`, bảng giá và tồn kho `biz_117`.
2. Tiền tố bỏ dấu `tong nam ` nhầm tên khách hàng họ **Tống Nam…** thành **Tổng năm…** trong `biz_123`.

Sửa theo mẫu ngôn ngữ, không theo business ID: bỏ tiền tố `cong ` quá rộng; giữ khác biệt dấu giữa Công/Cộng và Tống/Tổng khi xóa dòng; nhãn tổng năm có phần bổ nghĩa phải chứa năm hợp lệ. Vẫn loại nhãn tổng có bằng chứng như “Cộng ngày 01/01/2025”. Parser tăng lên 1.1.2 để invalid cache. Không sửa nguồn hoặc artifact cũ; dựng bundle release riêng.

Ba golden regression bổ sung đã chứng minh lỗi và kết quả sửa:

| Question ID | Trước sửa | Sau sửa | Golden |
|---|---:|---:|---:|
| `q_756cb06c26cc` | None | 703000 | 703000 |
| `q_80410ed452fc` | 986417400 | 988489400 | 988489400 |
| `q_f5fd1585c5c6` | 908788600 | 910179600 | 910179600 |

Cùng bộ 61 câu, trước sửa 58/61, sau sửa 61/61. Đây là regression sau phát hiện lỗi, không phải holdout độc lập hay PA của hệ thống.

Auditor cũ cũng có giả định không còn đúng: yêu cầu `calendar` nằm trong business lineage. Calendar được ingestion nạp từ file tham chiếu riêng, nên auditor hiện đối chiếu toàn bộ giá trị ở hai chiều với CSV nguồn; vẫn kiểm row count, schema, profile và key. Có test sửa holiday trong DB để chắc chắn audit phát hiện dữ liệu bị đổi.

## Phạm vi kiểm chứng

Integrity audit kiểm tên bảng/cột khớp database; row counts; raw/main/lineage; null/distinct statistics đầy đủ; giới hạn samples; kiểm lại candidate keys và tuple JOIN statistics bằng SQL, gồm composite; trạng thái manifest; artifact hashes; hash nguồn và cache.

Golden SQL có các nhóm:

- base_unit_quantity: 1 câu.
- cancel_count: 3 câu.
- cancel_percent: 3 câu.
- order_count: 7 câu.
- purchase_total: 24 câu.
- revenue: 12 câu.
- revenue_event_no_order_id: 3 câu.
- revenue_join: 4 câu.
- weighted_purchase_price_join: 4 câu.

Các JOIN dùng trong SQL review có precheck uniqueness và đơn vị khi cần; chạy được SQL review **không nâng trạng thái cạnh JOIN trong catalog**.

## Đối chiếu baseline và cảnh báo

Baseline local: `data/join-improvement-regression.json`, dẫn tới bundle cũ `data/join-full-regression`. Không coi đây là bản V4: V4 không có đầy đủ bundle tương ứng để đối chiếu chắc chắn.

Có 30 bảng mới so baseline, chủ yếu calendar tham chiếu. Các bảng còn đổi số dòng hoặc tổng kiểm soát:

| Business | Bảng | Số dòng baseline → release |
|---|---|---:|
| biz_104 | `don_hang_chi_tiet_c45c645a` | 62894 → 62451 |
| biz_105 | `so_ban_hang_17d6a4c9` | 138023 → 137983 |
| biz_107 | `so_ban_hang_29632c77` | 43605 → 43079 |
| biz_110 | `danh_sach_hoa_don_9579ce11` | 29317 → 28888 |
| biz_130 | `so_chi_tiet_ban_hang_25020381` | 172530 → 171936 |

Diff đầy đủ có cả type và tổng numeric trong JSON. Không tự coi mọi diff là bug: loại dòng tổng là thay đổi có chủ đích; làm mất thực thể là lỗi cần sửa. Bảng giá/tồn kho và khách hàng vừa bị mất dòng đã được kiểm tra phục hồi riêng.

Quality events (đếm lượt biến đổi/cảnh báo, không phải số lỗi độc lập): `{'unmapped_status': 6301, 'forward_fill': 459452, 'non_data_footer': 2072, 'duplicate_export': 13083}`. Forward-fill và duplicate-export chỉ được kiểm theo luật hiện có; không coi số lượng lớn tự động là lỗi.

Một số nhóm unmapped status lớn:

| Business | Bảng / cột | Số lượt |
|---|---|---:|
| biz_109 | `du_lieu_ban_hang_danh_sach_nhap_hang_a51f856f` / `trang_thai` | 561 |
| biz_119 | `danh_sach_nhap_hang_120a7c6c` / `trang_thai` | 554 |
| biz_123 | `pos_phieu_nhap_9ec4e5c1` / `tinh_trang` | 540 |
| biz_120 | `danh_sach_nhap_hang_120a7c6c` / `trang_thai` | 526 |
| biz_106 | `danh_sach_nhap_hang_120a7c6c` / `trang_thai` | 513 |
| biz_108 | `danh_sach_nhap_hang_120a7c6c` / `trang_thai` | 499 |
| biz_128 | `danh_sach_nhap_hang_120a7c6c` / `trang_thai` | 479 |
| biz_124 | `ban_hang_khach_hang_9f784b87` / `trang_thai` | 380 |

Cần phân biệt trạng thái phiếu nhập/khách hàng với trạng thái đơn bán; không map mù mọi giá trị sang completed/cancelled. Raw values vẫn được giữ, và cảnh báo không đồng nghĩa một golden đang sai.

## B02 và downstream: điều gì còn thiếu?

- Có 512 key candidates, phân loại `{'candidate': 512}`; kết quả SQL recheck khớp metadata.
- Có 538 JOIN candidates, phân loại `{'uncertain': 538}`. Luồng mặc định không có reviewed relationship manifest, nên không tự coi overlap là chứng cứ JOIN validated. Cơ chế kiểm chứng đã có; cần bổ sung/review evidence cho các quan hệ quan trọng, không viết lại validator.
- Có 4128 rule, phân loại `{'descriptive': 4128}`, và 116 heuristic metric entries. Không phát hiện metric trỏ bảng/cột không tồn tại. Rule descriptive vẫn là văn bản; không đồng nghĩa đã compile được thành SQL. Compiler cho structured validated rules đã có, nhưng đợt này chưa tạo binding mới.
- Không chạy 3B trên cả 30 business; kết quả 8/8 quy đổi ở pilot trước vẫn chỉ là kết quả riêng `biz_128`. Không suy rộng thành chất lượng LLM toàn dataset.
- Golden hiện chưa phủ đủ công nợ, lô/hạn sử dụng, as-of, lợi nhuận và mọi biến thể quy đổi. 16 business chưa có SQL golden trong bộ này. Không kết luận Text-to-SQL end-to-end đã tốt hoặc PA tăng.

Ưu tiên tiếp: (1) golden/reference checks cho công nợ, lô, temporal và các business chưa phủ; (2) review evidence JOIN quan trọng và binding một số metric/rule cần dùng; (3) phân loại status theo nghiệp vụ để giảm cảnh báo nhiễu; (4) chỉ sau đó mở rộng pilot 3B theo batch. Đợt audit này dùng 0 GPU call, không dùng thêm credit Modal.

## Chạy lại

```bash
PYTHONPATH=src .venv/bin/python scripts/benchmark_preparation.py \
  --train-dir data/train --output-dir artifacts/b01_b02_full/bundles_release \
  --report artifacts/b01_b02_full/preparation_release.json --jobs 8

PYTHONPATH=src .venv/bin/python scripts/audit_b01_b02_full.py \
  --report artifacts/b01_b02_full/preparation_release.json \
  --baseline data/join-improvement-regression.json \
  --output artifacts/b01_b02_full/release_audit \
  --cases examples/b01_b02/expanded_golden_checks.json
```

Lưu ý benchmark cold/warm: chạy lại vào output đã tồn tại sẽ có cold cache hit; audit cold/warm chặt yêu cầu output mới cho một lượt cold mới. Nếu muốn đo lại cold, đổi output/report sang thư mục mới; không cần xóa cache cũ.

Artifacts: `artifacts/b01_b02_full/preparation_release.json`, `release_audit/audit.json`, `golden_before_footer_fix.json`. Lượt đầu và lượt sửa trung gian được giữ riêng để truy vết; bản kết luận là **release parser 1.1.2**, không lấy nhầm report trung gian.

## Kiểm thử và dữ liệu được khôi phục

Tests cuối đợt: **466 passed, 3 skipped, 15 subtests passed**. `git diff --check` đạt. Có regression riêng cho Công/Cộng, Tống/Tổng, nhãn tổng năm và Cộng ngày, cùng test auditor phát hiện calendar bị sửa.

| Bảng bị ảnh hưởng | Trước sửa | Release |
|---|---:|---:|
| biz_113 — sổ bán hàng | 32.469 | 32.994 |
| biz_117 — bảng giá | 99 | 100 |
| biz_117 — tồn kho | 59 | 60 |
| biz_123 — khách hàng | 299 | 300 |

Tổng cộng khôi phục **528 dòng hợp lệ**, không đồng nghĩa 528 thực thể khác nhau. Chi tiết: `artifacts/b01_b02_full/restored_entities.json`.
