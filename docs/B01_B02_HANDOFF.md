# Bàn giao B01/B02 — input, output và tích hợp

Cập nhật 05/11/2026 · Dataset path: contract 1.1 · Metadata legacy: 1.0.

## Mình đã làm gì?

**B01 nhận trực tiếp file dataset**, đọc và chuẩn hóa vào DuckDB, tính profiling toàn bộ dữ liệu rồi xây catalog bảng/cột, khóa và join graph. **B02 nhận README/rulebook**, lưu luật cùng nguồn/phạm vi và cung cấp API chọn luật, binding công thức, compile SQL fragment có tham số.

```text
CSV/XLSX/SQLite + README/rulebook/calendar
  → B01 ingestion → data.duckdb + foundation_metadata.json
  → B01 schema/keys/joins + B02 rules → business_context.json
  → teammate Planner/Text-to-SQL/executor tích hợp tiếp
```

“Data Foundation” là tên tầng đọc/chuẩn hóa/profiling trong kiến trúc dự án, hiện được triển khai trong B01. Không phải ban tổ chức hay một teammate bắt buộc phải tạo JSON trước.

## B01 input/output

| Input | Ý nghĩa |
|---|---|
| `business_dir` | Thư mục một business chứa CSV, XLSX, SQLite và README |
| `rulebook` | File Markdown luật chung, tùy chọn trong API nhưng nên truyền cho dataset train |
| `calendar` | Đường dẫn lịch, tham gia cache; không import như bảng business |
| `config` | Giới hạn bộ nhớ, batch, encoding/delimiter/header/role override khi cần |
| `output_dir` | Nơi ghi artifacts, nằm ngoài thư mục business |

```python
from datamate.ingestion import prepare_business

result = prepare_business(
    'data/train/data/biz_123', 'data/cache',
    rulebook='data/train/rulebook.md', calendar='data/train/calendar.csv',
)
# PreparedBusinessArtifacts:
# business_id, cache_key, bundle_dir, status, cache_hit, quality_summary
```

CLI:

```bash
uv sync --frozen
PYTHONPATH=src uv run --frozen python -m datamate prepare \
  --business-dir data/train/data/biz_123 \
  --rulebook data/train/rulebook.md --calendar data/train/calendar.csv \
  --output-dir data/cache
```

Bundle `<output>/<business_id>/<cache_key>/`:

| Output | Teammate dùng để làm gì |
|---|---|
| `data.duckdb` | Toàn bộ dữ liệu chuẩn hóa trong `main`; raw trong `raw`; lineage/issues trong `meta` |
| `business_context.json` | Input metadata chính cho Planner/Text-to-SQL |
| `foundation_metadata.json` | Artifact metadata trung gian do B01 sinh, không phải đầu vào dataset bắt buộc |
| `source_manifest.json` | Trạng thái, hash và mapping mọi nguồn/sheet/table |
| `normalization_report.json` | Số dòng, dedup, quality issues và runtime build |

## Schema JSON teammate cần biết

```text
BusinessContext {
  contract_version: "1.1",
  business_id: string,
  normalized_data_handle: {
    engine: "duckdb", sql_dialect: "duckdb",
    database: "data.duckdb", schema: "main"
  },
  schema_catalog: {
    tables: [{name, columns: [{name, data_type, nullable, null_ratio,
                             cardinality, provenance}], row_count,
              grain, grain_evidence, ...}],
    key_candidates: [{table, columns[], key_type, status, confidence, evidence[]}],
    join_graph: [{left_table, left_column, right_table, right_column,
                  additional_key_pairs[], cardinality, status,
                  confidence, evidence[], fanout_warning}],
    warnings: []
  },
  rule_catalog: {business_id, rules: [], warnings: []},
  data_profiling: {<table>: {row_count, columns, samples, profile_mode,
                            coverage_semantics}},
  business_metadata: {schema_mapping: {<table>: {family, source_ids,
                       columns: {<column>: {original_name, role, sql_type}}}}},
  answerability_constraints: null
}
```

Đây là mô tả schema, không phải JSON literal để copy làm dữ liệu. Mẫu JSON thật nằm trong bundle vừa chạy.

- Tên bảng/cột trong catalog **khớp database**; dùng trực tiếp tên này khi sinh SQL và quote identifier bằng dấu `"`.
- Tên nguồn có dấu được lưu ở source mapping. Mẫu chỉ tối đa 5 dòng/bảng; thống kê SQL tính trên toàn bảng.
- Decimal trong JSON mẫu là string để giữ chính xác; trong database là DECIMAL khi precision cho phép. Ngày mẫu là ISO.
- `__dm_row_id` chỉ phục vụ lineage, không coi là mã đơn hoặc khóa nghiệp vụ.
- Keys là candidate cấu trúc. Join `validated` đã kiểm tra evidence + SQL coverage/cardinality; vẫn cần tôn trọng grain. `uncertain/candidate` phải xem xét trước khi dùng, `invalid` không dùng.
- Đơn hủy/trả và ngày tương lai vẫn có trong database. Trạng thái nhận diện là `completed/cancelled/returned/delivering`; giá trị lạ giữ nguyên và có issue.
- Footer có nhãn tổng/ghi chú rõ được giữ ở raw kèm issue, không cộng thành giao dịch. Báo cáo có `raw_rows`, `source_rows` (dòng business), `excluded_non_data_rows`.
- Parse lỗi thành NULL có raw reference; không thành 0. Đọc quality report trước khi aggregate. Không coi khoảng ngày quan sát là bằng chứng dữ liệu đầy đủ.

## B02 input/output

Input B02: danh sách đường dẫn README/rulebook, business_id, catalog B01; khi binding có thêm mapping role → `table.column` và evidence cho từng điều kiện.

```python
from datamate.rule_compiler import BusinessRuleCompiler
from datamate.rule_resolver import RuleResolver

compiler = BusinessRuleCompiler()
catalog = compiler.ingest_documents(
    ['data/train/rulebook.md', 'data/train/data/biz_123/README.md'],
    business_id='biz_123',
)
selected = RuleResolver().resolve(catalog, 'biz_123', industry='Nhà thuốc')
# selected.rules, selected.blocked_topics, selected.warnings
```

B02 output:

```text
RuleCatalog {business_id, rules: BusinessRule[], warnings[]}
BusinessRule {
  rule_id, text, source, scope, precedence, status,
  topic, industry, question_id, required_fields[], expression,
  validation_messages[], requirements[], binding_evidence[]
}
```

Luật đọc từ prose mặc định `descriptive`, không tự trở thành SQL. Resolver ưu tiên question override > business > industry > split default. Topic mâu thuẫn bị chặn. `RuleTemplateBinder.bind(...)` hỗ trợ revenue/gross_profit/sold_qty_base khi có binding và đủ evidence. `BusinessRuleCompiler.compile_rule(rule, schema)` trả `(sql_fragment, parameters)` cho rule structured đã validated. Teammate phải truyền cả fragment lẫn parameters cho executor.

Ingestion không tự khẳng định đã lọc đơn hợp lệ, đã quy đổi đơn vị hoặc đã thỏa điều kiện công thức. Không được dùng dedup hay profiling để tự đánh dấu các guarantee đó.

## Teammate tích hợp thế nào?

```python
import json
from pathlib import Path
import duckdb

bundle = Path(result.bundle_dir)
context = json.loads((bundle/'business_context.json').read_text())
handle = context['normalized_data_handle']
connection = duckdb.connect(str(bundle/handle['database']), read_only=True)
# Text-to-SQL lấy catalog + rules + câu hỏi + as_of_date, sinh DuckDB SQL.
# Executor tự phụ trách giới hạn truy vấn và kiểm soát tài nguyên.
```

B01/B02 chưa triển khai LLM sinh SQL, query API, executor hoặc formatter đáp án. Mode cũ `python -m datamate --metadata ... --business-id ... --document ...` vẫn nhận metadata 1.0. Chi tiết chuẩn hóa, override, cache, Docker và tests ở `docs/B01_B02_IMPLEMENTATION.md`; kết quả regression ở `docs/B01_PREPARATION_VALIDATION.md`.
