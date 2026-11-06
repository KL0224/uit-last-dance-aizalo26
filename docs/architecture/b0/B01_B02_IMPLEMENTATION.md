# B01/B02 — từ file dataset đến Business Context

Cập nhật 05/11/2026. Luồng dataset dùng contract **1.1**; luồng metadata JSON **1.0** vẫn được giữ để tương thích.

B01 hiện nhận trực tiếp file **CSV, XLSX, SQLite** trong thư mục business. Phần Data Foundation là tên tầng khám phá/đọc/chuẩn hóa/profiling trong kiến trúc của dự án, không phải một đầu vào JSON bắt buộc do ban tổ chức hoặc teammate cung cấp.

```text
business/*.csv, *.xlsx, *.sqlite + README + rulebook + calendar
    → discovery/manifest → raw → normalization → DuckDB main
    → SQL profiling → B01 schema/keys/joins → B02 document rules
    → database + Business Context JSON
```

## Chạy chương trình

```bash
uv sync --frozen
PYTHONPATH=src uv run --frozen python -m datamate prepare \
  --business-dir data/train/data/biz_123 \
  --rulebook data/train/rulebook.md \
  --calendar data/train/calendar.csv \
  --output-dir data/cache
```

CLI in một object JSON mô tả đường dẫn bundle, `status`, `cache_hit`, `quality_summary`. API Python tương ứng:

```python
from datamate.ingestion import PreparationConfig, prepare_business

artifacts = prepare_business(
    'data/train/data/biz_123', 'data/cache',
    rulebook='data/train/rulebook.md', calendar='data/train/calendar.csv',
    config=PreparationConfig(memory_limit='512MB', batch_size=10_000),
)
# artifacts.bundle_dir / 'data.duckdb'
# artifacts.bundle_dir / 'business_context.json'
```

## Bundle và schema

```text
<output>/<business_id>/<cache_key>/
  data.duckdb
  source_manifest.json
  foundation_metadata.json
  business_context.json
  normalization_report.json
```

| Artifact/schema | Nội dung |
|---|---|
| DuckDB `raw.s_<hash>` | Giá trị nguồn đã decode, số dòng vật lý và cache công thức; tham chiếu lại file gốc trong manifest |
| DuckDB `main.<logical_name>_<hash>` | Dữ liệu chuẩn hóa đầy đủ, typed; có `__dm_row_id` phục vụ lineage, không phải khóa nghiệp vụ |
| `meta.source_mapping`, `meta.column_mapping` | Tên nguồn, sheet, header row, tên cột gốc → tên SQL |
| `meta.lineage` | `table_name`, `row_id`, `source_id`, `source_row`, `deduplicated`; kể cả dòng xuất trùng được gộp |
| `meta.quality_issues` | `source_id`, `source_row`, `column_name`, `code`, `rule`; tra raw để xem giá trị gây lỗi |
| `source_manifest.json` | Hash, trạng thái mọi file, sheet/table, vùng header, bảng đích; tài liệu/câu hỏi/đáp án có lý do excluded |
| `foundation_metadata.json` | Metadata **do chương trình sinh**: bảng/cột, thống kê đầy đủ, tối đa 5 mẫu deterministic mỗi bảng, source mapping |
| `business_context.json` | Contract downstream: catalog B01, luật B02, profiling, metadata nguồn và database handle |
| `normalization_report.json` | Số dòng raw/business/đầu ra/dedup/footer, số issues theo loại, thời gian build, trạng thái |

Tên SQL được chuẩn hóa và thêm hash ổn định theo family/schema. File đánh số và sheet tháng chỉ hợp nhất khi cùng family và cùng header. Sheet nghiệp vụ khác giữ riêng. Teammate luôn lấy **tên chính xác từ catalog**, không suy tên từ tên file.

## Hành vi chuẩn hóa

- CSV streaming: UTF-8/BOM, fallback CP1258, delimiter thông dụng hoặc override.
- XLSX: openpyxl read-only, header nhóm + header chi tiết, header lặp, vùng bảng tách bằng dòng trống. Header không xác định phải khai báo cấu hình. Công thức chỉ lấy cached value; thiếu cache thành NULL có issue, công thức vẫn nằm ở raw.
- SQLite: `mode=ro&immutable=1`, `query_only`, fetch theo batch; không tải extension hoặc tạo journal/SHM. Nguồn có WAL chưa checkpoint phải xuất snapshot trước; chương trình báo lỗi thay vì bỏ qua WAL. FK ghép khai báo được kiểm chứng bằng cả tuple.
- ID/tên/điện thoại giữ text và dấu; số 0 đầu của text được giữ. Không thể khôi phục số 0 đã mất trong nguồn numeric chỉ từ giá trị số.
- Tiền/số lượng dùng Decimal và DuckDB DECIMAL theo scale quan sát; giá trị quá precision giữ VARCHAR. Hỗ trợ thêm dạng `2tr760`, `398,8604tr`; số lượng có suffix như `2 xe 4m3` chỉ lấy số lượng 2, giữ dấu vết đơn vị ở raw và không tự nhân hệ số. Không làm tròn; đơn vị suffix số lượng không tạo bảo đảm đã quy về đơn vị cơ bản.
- Ngày: ISO, dd/mm/yyyy, ngày tiếng Việt, Excel epoch, năm sheet khi thiếu năm; không lấy năm từ đồng hồ máy.
- Parse failure thành NULL **có quality issue + raw reference**, không thành 0. Trạng thái chưa nhận diện giữ nguyên và có issue; trạng thái nhận diện dùng `completed/cancelled/returned/delivering`.
- Forward-fill/dedup chỉ bật khi tài liệu có đủ các quy ước xuất nhóm/đơn đã nhận diện, bảng có một mã đơn và có dòng hàng/số lượng. Không áp dụng dedup cho sổ sự kiện; không fill số lượng/giá/tên hàng. Các phép biến đổi được ghi trong quality issues và lineage.
- Footer có nhãn tổng/ghi chú rõ ở cột ngày, không có identity đơn/hàng, được giữ trong raw và ghi `non_data_footer`; không đưa vào bảng giao dịch để tránh cộng trùng tổng. Trường hợp mơ hồ giữ dữ liệu kèm issue.
- Không lọc đơn hủy/trả, ngày tương lai; không tự quy đổi đơn vị, tính doanh thu/lợi nhuận hoặc khẳng định dữ liệu đủ trả lời câu hỏi.

## Cấu hình ngoại lệ có nguồn

`--config path/to/config.json` nhận JSON tương ứng `PreparationConfig`. `source_overrides` dùng đường dẫn tương đối file, hoặc `file.xlsx#Tên sheet`. Override và hash cấu hình được lưu trong manifest.

```json
{
  "memory_limit": "512MB",
  "threads": 2,
  "batch_size": 10000,
  "source_overrides": {
    "data.csv": {"encoding": "cp1258", "delimiter": ";"},
    "book.xlsx#Sheet1": {
      "header_row": 2,
      "logical_table": "sales",
      "roles": {"Mã đơn": "identifier", "Giá bán": "money"}
    }
  }
}
```

Roles: `identifier`, `text`, `status`, `date`, `money`, `quantity`, `boolean`, `unknown`. Header_row là chỉ số 1-based. Cần cấu hình khi cấu trúc ngoài các quy ước đã nhận diện; không hardcode theo business_id.

## Profiling, keys và joins

DuckDB tính COUNT, NULL, DISTINCT, khoảng ngày trên **toàn bảng**, thay vì coi 5 mẫu là toàn bộ dữ liệu. `DuckDBProfileProvider` kiểm tra uniqueness và tuple FK bằng SQL. Key là candidate cấu trúc; không khẳng định business grain. Cạnh từ overlap luôn uncertain; FK có evidence chỉ validated khi coverage/cardinality đạt. Phạm vi ngày chỉ là observed coverage.

Các guarantee như `valid_revenue_orders`, `quantity_in_base_unit`, `sales_line_grain` tiếp tục do B02/downstream thu thập evidence; ingestion không tự đánh dấu đã thỏa.

## Cache và lỗi

Cache gồm hash nguồn, README/rulebook/calendar, parser/code, dependency và config. Cache hit kiểm tra artifact hash, không parse lại bảng; vẫn hash file để nhận diện thay đổi. Build trong `.build-*`, hoàn tất mới rename atomically thành cache key. API ném `PreparationError` khi thất bại. Lỗi giữ thư mục `failed-*` có manifest/report, CLI trả exit 1; không phát hành ready. Không chỉnh dữ liệu nguồn. DuckDB memory limit mặc định 512MB, không phải giới hạn RSS toàn tiến trình Python; file spool và spill nằm trong bundle tạm.

## Docker offline

```bash
docker build -t datamate-prepare:local .
mkdir -p data/docker-cache
docker run --rm --network none \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$PWD/data/train,dst=/input,readonly" \
  --mount "type=bind,src=$PWD/data/docker-cache,dst=/output" \
  datamate-prepare:local prepare \
  --business-dir /input/data/biz_123 --rulebook /input/rulebook.md \
  --calendar /input/calendar.csv --output-dir /output
```

Image dùng uv.lock; build cần tải dependency, runtime không cần mạng. DuckDB là database file, không có database server.

## Kiểm thử và benchmark

```bash
DATAMATE_TRAIN_DIR=data/train PYTHONPATH=src uv run --frozen python -m unittest discover -s tests -v
uvx ruff check src tests scripts
PYTHONPATH=src uv run --frozen python scripts/benchmark_preparation.py \
  --train-dir data/train --output-dir data/regression-cache \
  --report data/preparation-benchmark.json --jobs 4
```

Script benchmark chạy mỗi business trong subprocess, ghi cold/warm wall time, peak RSS Linux và hash nguồn trước/sau. Dùng output directory mới để đo cold thực sự; kiểm tra `cache_hit=false` cho lượt cold. Nếu chạy nhiều jobs, wall time chịu ảnh hưởng contention. Đây là preparation benchmark, chưa phải PA/inference benchmark. Kết quả lần chạy thực tế nằm trong [báo cáo regression](B01_PREPARATION_VALIDATION.md).

Kiểm tra chéo bundle đã publish với SQL trên toàn bộ database:

```bash
PYTHONPATH=src uv run --frozen python scripts/audit_prepared_bundles.py \
  data/preparation-benchmark.json
```

Audit đối chiếu tên/type cột, row count, NULL/DISTINCT, lineage, dedup, số issues và giới hạn mẫu JSON; yêu cầu cold không cache hit và warm có cache hit. File có lỗi discovery/read không được phát hành bundle ready. Source thay đổi trong lúc build cũng làm build thất bại.
