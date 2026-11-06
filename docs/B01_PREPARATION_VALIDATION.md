# B01 — Kết quả kiểm chứng preparation

Cập nhật 05/11/2026. Đây là kiểm chứng chuẩn bị dữ liệu, chưa phải benchmark PA hay inference.

## Kết quả

| Hạng mục | Kết quả |
|---|---|
| Unit/integration tests | **68/68 pass**, gồm toàn bộ 45 tests cũ và 23 tests mới |
| Business | **30/30 ready**, không có build lỗi |
| File dữ liệu | **128/128**: 20 CSV, 107 XLSX, 1 SQLite; mọi file có trạng thái trong manifest |
| Bảng chuẩn hóa | **217** |
| Dòng raw đọc được | **3,997,042**; không tính header lặp/dòng hoàn toàn trống |
| Dòng business trước dedup | **3,997,002** |
| Dòng chuẩn hóa | **3,983,919** |
| Dòng xuất trùng được gộp | **13,083**, giữ raw và lineage |
| Footer | **40** dòng tổng/ghi chú giữ trong raw, loại khỏi giao dịch bằng rule có evidence |
| Parse failure trên train | **0** |
| Forward-fill | **462,763 ô**, giới hạn field cấp đơn theo rulebook |
| Trạng thái chưa ánh xạ | **8,646 ô**, giữ giá trị nguồn và issue |
| Cache warm | **30/30 cache hit**, cùng cache key với lượt cold |
| Nguồn giữ nguyên | SHA-256 trước/sau của **162 file** trong train trùng nhau |
| Audit database | 30/30 pass: raw/manifest counts, tên/type cột, NULL/DISTINCT toàn bảng, lineage/dedup, sample JSON ≤5 |
| Docker | Build thành công; SQLite chạy offline với input read-only, filesystem container read-only, output writable; warm cache hit cũng đã kiểm tra |
| Tương thích legacy | Ví dụ `--metadata` vẫn xuất contract 1.0, không thêm handle; luồng dataset xuất 1.1 |

## Runtime và bộ nhớ

Môi trường: Python 3.12.3, DuckDB 2.0.0, openpyxl 3.1.5, Linux. Chạy **8 business song song**; thời gian mỗi business chịu ảnh hưởng contention. Timer đo lời gọi preparation sau khi import module; RSS là peak toàn tiến trình worker. Giới hạn 512MB là của DuckDB, không phải giới hạn RSS Python.

| Chỉ số mỗi business | Min | Median | Max |
|---|---:|---:|---:|
| Cold | 6.27 s | 105.36 s | 281.77 s |
| Warm | 0.011 s | 0.026 s | 0.057 s |
| Peak RSS cold | 118.6 MiB | 206.4 MiB | 307.9 MiB |

| Business | File | Bảng | Dòng chuẩn hóa | Cold (s) | Warm (s) | Peak RSS (MiB) |
|---|---:|---:|---:|---:|---:|---:|
| biz_101 | 1 | 1 | 56,501 | 18.99 | 0.023 | 183.6 |
| biz_102 | 2 | 2 | 86,106 | 229.35 | 0.027 | 223.4 |
| biz_103 | 2 | 17 | 45,611 | 90.49 | 0.020 | 150.7 |
| biz_104 | 2 | 2 | 62,896 | 68.31 | 0.014 | 203.3 |
| biz_105 | 6 | 5 | 139,526 | 281.77 | 0.040 | 293.8 |
| biz_106 | 10 | 9 | 286,123 | 261.01 | 0.057 | 259.8 |
| biz_107 | 1 | 1 | 43,605 | 39.27 | 0.014 | 138.8 |
| biz_108 | 7 | 7 | 113,696 | 114.20 | 0.025 | 209.4 |
| biz_109 | 2 | 9 | 156,626 | 203.22 | 0.031 | 214.1 |
| biz_110 | 1 | 1 | 29,317 | 6.27 | 0.015 | 118.6 |
| biz_111 | 5 | 5 | 239,499 | 36.30 | 0.034 | 201.4 |
| biz_112 | 3 | 2 | 113,375 | 209.04 | 0.028 | 250.6 |
| biz_113 | 1 | 1 | 32,994 | 22.09 | 0.011 | 125.4 |
| biz_114 | 1 | 1 | 26,119 | 7.13 | 0.012 | 140.2 |
| biz_115 | 4 | 19 | 55,962 | 97.53 | 0.029 | 146.4 |
| biz_116 | 1 | 4 | 79,117 | 99.59 | 0.020 | 184.1 |
| biz_117 | 7 | 7 | 65,773 | 126.21 | 0.030 | 167.7 |
| biz_118 | 4 | 4 | 92,169 | 156.95 | 0.021 | 171.8 |
| biz_119 | 10 | 10 | 170,661 | 163.42 | 0.031 | 182.9 |
| biz_120 | 10 | 27 | 240,702 | 204.41 | 0.033 | 215.4 |
| biz_121 | 2 | 7 | 172,139 | 111.12 | 0.021 | 217.7 |
| biz_122 | 9 | 7 | 214,306 | 182.20 | 0.032 | 264.8 |
| biz_123 | 1 | 17 | 267,703 | 35.21 | 0.046 | 216.4 |
| biz_124 | 13 | 13 | 305,973 | 167.84 | 0.038 | 192.6 |
| biz_125 | 1 | 1 | 79,052 | 21.12 | 0.018 | 223.3 |
| biz_126 | 1 | 1 | 66,429 | 44.02 | 0.011 | 147.5 |
| biz_127 | 5 | 5 | 195,901 | 21.64 | 0.037 | 217.0 |
| biz_128 | 8 | 25 | 151,116 | 122.51 | 0.024 | 210.8 |
| biz_129 | 5 | 5 | 222,331 | 20.90 | 0.032 | 229.9 |
| biz_130 | 3 | 2 | 172,591 | 111.22 | 0.015 | 307.9 |

## Quality issues và giới hạn

- Trạng thái chưa ánh xạ được giữ nguyên, không ép thành completed/cancelled. Có cả trạng thái khách/hàng và trạng thái nguồn cần review như “Đang hoạt động”, “Đã nhập hàng”, “Không giao được”. Downstream phải xem field/table, README và B02 trước khi áp luật doanh thu.
- `biz_117`: 40 dòng “Tổng tháng”/“Ghi chú” nằm dưới bảng, không có mã đơn/hàng. Raw giữ đầy đủ; `meta.quality_issues.code=non_data_footer` ghi lý do không đưa vào main. Chặn việc cộng lại tổng vào doanh thu.
- Không lọc đơn hủy/trả hoặc ngày tương lai; không tự quy đổi đơn vị hay xác nhận semantic guarantees của B02. Không suy business completeness từ khoảng ngày quan sát.
- Cấu trúc header ngoài các quy ước nhận diện cần override có provenance. Sheet có dữ liệu sau vùng scan trống không bị coi là sheet rỗng; chương trình yêu cầu header_row. SQLite có WAL chưa checkpoint phải cung cấp snapshot; không ghi checkpoint vào nguồn.
- 0 parse failure trên train không khẳng định hỗ trợ mọi định dạng ngoài train. Giá trị không parse được ở input mới vẫn giữ raw và có quality issue, không đổi thành 0.

## Tái lập và artifacts

```bash
uv sync --frozen
DATAMATE_TRAIN_DIR=data/train PYTHONPATH=src uv run --frozen python -m unittest discover -s tests -q
PYTHONPATH=src uv run --frozen python scripts/benchmark_preparation.py \
  --train-dir data/train --output-dir data/prepared-bundles \
  --report data/b01-preparation-validation.json --jobs 8
PYTHONPATH=src uv run --frozen python scripts/audit_prepared_bundles.py \
  data/b01-preparation-validation.json
```

Dùng output mới khi muốn đo cold lại. Kết quả chi tiết tại `data/b01-preparation-validation.json`, `data/b01-preparation-validation-audit.json`; bundles tại `data/prepared-bundles/<business_id>/<cache_key>/`. Dataset/cache/JSON benchmark được gitignore; bảng tổng hợp trong tài liệu này được theo dõi bằng Git.

Fingerprint code của lượt toàn train: `6492ee35d42bf8e427d95ee4ecf1dda35bef7f57e201be39d91b17eb12660b0b`. Sau lượt này chỉ bổ sung guard từ chối output trỏ vào nguồn (kể cả qua parent/symlink); các tầng đọc, chuẩn hóa, materialization và profiling giữ nguyên. Guard được kiểm tra bằng unit test, rồi chạy lại CLI CSV cold/warm và Docker SQLite offline trên mã cuối. Fingerprint mã cuối: `4a5f0231085a7370fc1e69a43cab1974f34734a1f4fe22936ed44851cffcd810`. Sửa code làm cache invalid theo thiết kế.

Tài liệu tích hợp: [B01/B02 handoff](B01_B02_HANDOFF.md), [chi tiết preparation](B01_B02_IMPLEMENTATION.md), [Data Contract](DATA_CONTRACT.md).
