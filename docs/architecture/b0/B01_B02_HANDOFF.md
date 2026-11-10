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
| `relationships` | Manifest JSON khai báo quan hệ đã review, tùy chọn; dùng tên file/bảng/cột nguồn |
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
                  confidence, evidence[], fanout_warning,
                  statistics?, relationship_evidence?}],
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
- Keys là candidate cấu trúc. Join `validated` cần attestation có scope/provenance và SQL coverage/cardinality; một chuỗi `evidence` tự do không đủ. `uncertain/candidate/invalid` đều không được navigator/compiler sử dụng. JOIN đã validated vẫn cần tôn trọng grain.
- Đơn hủy/trả và ngày tương lai vẫn có trong database. Trạng thái nhận diện là `completed/cancelled/returned/delivering`; giá trị lạ giữ nguyên và có issue.
- Footer có nhãn tổng/ghi chú rõ được giữ ở raw kèm issue, không cộng thành giao dịch. Báo cáo có `raw_rows`, `source_rows` (dòng business), `excluded_non_data_rows`.
- Parse lỗi thành NULL có raw reference; không thành 0. Đọc quality report trước khi aggregate. Không coi khoảng ngày quan sát là bằng chứng dữ liệu đầy đủ.

## Khai báo reviewed relationships và dùng JOIN graph

Mặc định không có review: candidate discovery dùng tên/role/mapping cột và khóa cấu
trúc, kiểm tra SQL toàn bảng; không dùng 5 samples để loại JOIN. Cạnh inferred có
coverage cao vẫn là `uncertain`. README không tự trở thành declaration JOIN.
Các identifier hằng số ở cả hai phía không tự tạo cạnh; cần declaration tường minh
nếu thực sự có quan hệ một giá trị. Điều này tránh nối mọi bảng chỉ bằng mã cửa hàng.

Khai báo qua `prepare_business(..., relationships='path/review.json')` hoặc:

```bash
PYTHONPATH=src uv run --frozen python -m datamate prepare \
  --business-dir data/train/data/biz_123 \
  --rulebook data/train/rulebook.md --calendar data/train/calendar.csv \
  --relationships examples/relationships/biz_123.json \
  --output-dir data/join-improvement
```

[Manifest mẫu](../../../examples/relationships/biz_123.json) và [review nguồn](../../../examples/relationships/biz_123_review.md)
ghi rõ đây là review kỹ thuật của agent, chưa phải teammate sign-off. Production
không chứa mapping hardcode cho business này. Không truyền manifest thì các quan
hệ đó vẫn chỉ là inferred. Với business khác cần manifest và review riêng.

Manifest gồm `version: "1.0"`, `business_id`, `relationships[]`. Mỗi quan hệ có:

- `id`, `left/right: {file, table, columns[]}`; `table` là tên SQLite table/XLSX sheet,
  hoặc `null` cho CSV; `columns` dùng **tên cột nguồn** và phải ghép đủ composite key.
- `cardinality`: `many_to_one`, `one_to_many` hoặc `one_to_one`.
- `review: {status, reviewed_by, evidence: {path, sha256, quote}}`; đường dẫn evidence
  tương đối với manifest. Hash phải khớp file và quote phải có trong nội dung UTF-8.
  Chỉ `approved` có thể đủ điều kiện trust; `pending/rejected` không thể validated.

SQL checker vẫn phải xác nhận uniqueness/coverage/cardinality. Orphan hoặc sai
cardinality thành `invalid`; xung đột khai báo bị chặn. NULL key được báo riêng,
không coi là orphan. Manifest và mọi evidence file tham gia cache invalidation.

`relationship_evidence` tách nguồn `sqlite_foreign_key` với `reviewed_relationship`,
lưu scope, reviewer, hash và fingerprint ràng buộc đúng mapping/cardinality.
`statistics` lưu row/null/distinct/matched counts, directional coverage và observed
cardinality. Hash/quote bảo vệ traceability, không xác thực danh tính reviewer hoặc
chứng minh tự động ý nghĩa nghiệp vụ. Manifest/metadata producer là trust boundary.

Đọc contract đã có, không suy luận lại hoặc đổi trạng thái:

```python
from datamate.b0.b01.metadata_adapter import BusinessContextSchemaReader
from datamate.b0.b01.join_graph import JoinGraphNavigator, JoinPredicateCompiler

schema = BusinessContextSchemaReader().read(context)
result = JoinGraphNavigator().describe_path(schema, source_sql_name, target_sql_name)
if result.status == 'validated_path':
    predicates = [JoinPredicateCompiler().compile(edge, schema) for edge in result.path]
# result.warnings: hướng cardinality, fanout, NULL keys; planner tự chọn INNER/LEFT.
# no_validated_path: không có đường đã xác minh; không đồng nghĩa unanswerable.
```

Ví dụ consumer read-only: `scripts/demo_join_graph.py --bundle <bundle> --source
khach_hang --target san_pham --count-rows` (chạy với `PYTHONPATH=src`). Consumer chỉ
dựng equijoin và COUNT để kiểm chứng, không tính doanh thu hay tự áp luật B02.

Thêm `--rule-topic 'Doanh thu một đơn' --industry 'Nhà thuốc'` để đọc `rule_catalog`
đã lưu và chọn luật bằng `RuleResolver`. `business_rule.status` là
`missing_binding_or_evidence` nếu luật còn descriptive, `no_selected_rule` nếu không
có luật được chọn, hoặc `compiled_fragment_only` nếu producer đã cung cấp structured
validated rule. COUNT trong output vẫn chỉ kiểm tra JOIN, không phải doanh thu.
Consumer không tự bind luật, không nâng trạng thái và không thực thi SQL nghiệp vụ
khi thiếu điều kiện. Fixture tích hợp ở `tests/test_business_context_integration.py`
minh họa caller bind công thức với evidence, áp filter và đối chiếu SQL độc lập.

Metadata 1.0/1.1 cũ vẫn đọc được. Thay đổi có chủ đích: positive declaration chỉ có
evidence string không còn tự validated; producer muốn xác minh phải cấp structured
attestation và profile đầy đủ, hoặc dùng pipeline review + SQL. B02 không thay đổi.

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
