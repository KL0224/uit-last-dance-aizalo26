# Luồng Dữ Liệu Tổng Thể (End-to-End Data Flow) — Từ Dữ Liệu Thô Đến Kết Quả Baseline B0

> **Dự án:** DataMate 2026 — Baseline B0 (`B0.1 → B0.2 → B0.3 → B0.4 → B0.5`)  
> **Mục đích tài liệu:** Mô tả chi tiết **sự biến đổi của dữ liệu (Data Transformation & Contract Flow)** ở từng chặng — từ các tệp dữ liệu thô trên đĩa (`CSV`, `XLSX`, `SQLite`, `Markdown`, `JSONL`), qua các cấu trúc dữ liệu trung gian trong bộ nhớ và DuckDB, cho tới khi xuất ra tệp nộp bài chuẩn `submission.jsonl` và nhật ký kiểm toán `gate_trace.jsonl`.  
> **Lưu ý định dạng:** Toàn bộ sơ đồ trong tài liệu này được vẽ bằng **Markdown/ASCII thuần** (không sử dụng Mermaid).

---

## 1. Bức Tranh Toàn Cảnh: 7 Chặng Biến Đổi Dữ Liệu (Data Lifecycle)

Dữ liệu đi qua hệ thống Baseline B0 được chia thành **7 chặng biến đổi liên tiếp** thuộc 2 pha (**Pha 1: Offline Data Preparation** và **Pha 2: Online Question Answering**):

```text
+==========================================================================================+
|                         PHA 1: OFFLINE DATA & CONTEXT PREPARATION                        |
|                        (Chạy 1 lần cho mỗi doanh nghiệp, có Cache)                       |
+==========================================================================================+

  [CHẶNG 1: DỮ LIỆU THÔ TRÊN ĐĨA (RAW FILES)]
   ├── data/<split>/data/<biz_id>/*.csv | *.xlsx | *.sqlite
   ├── data/<split>/data/<biz_id>/README.md
   ├── data/<split>/rulebook.md
   └── data/<split>/calendar.csv
                 |
                 |  B0.1 Readers (CSVReader / XLSXReader / SQLiteReader)
                 v
  [CHẶNG 2: LUỒNG DÒNG VẬT LÝ & BẢNG TẠM (SOURCE STREAM & RAW DUCKDB)]
   ├── SourceTable(source_id, headers, header_row, logical_family, year, ...)
   ├── SourceRow(number, values: tuple[Any, ...], formulas: dict[int, str])
   └── Bảng tạm DuckDB: `raw."s_<12_hex>"` (__dm_source_row, c_1..c_n, __dm_formula_cache)
                 |
                 |  B0.1 Normalization (ColumnParser) + DuckDB Materialization
                 v
  [CHẶNG 3: BẢNG CHUẨN HÓA & THỐNG KÊ HỒ SƠ (NORMALIZED DUCKDB & PROFILING)]
   ├── Bảng chính DuckDB: `main."<family>_<8_hex>"` (__dm_row_id, typed columns...)
   ├── DuckDBMetadataProvider -> BusinessMetadata (TableMetadata, ColumnMetadata)
   └── SchemaCatalogBuilder(DuckDBProfileProvider) -> SchemaCatalog
       (key_candidates, join_graph [coverage >= 0.8], relationship_candidates)
                 |
                 |  B0.2 BusinessRuleCompiler + ContractBuilder
                 v
  [CHẶNG 4: HỢP ĐỒNG NGỮ CẢNH DOANH NGHIỆP (ATOMIC BUNDLE ARTIFACTS)]
   └── Thư mục `<output_dir>/<biz_id>/<sha256_cache_key>/`
       ├── data.duckdb                 (Cơ sở dữ liệu phân tích đã định kiểu)
       ├── business_context.json       (BusinessContextContract: Schema + Rules + Ranges)
       ├── foundation_metadata.json    (Metadata vật lý & sample 5 dòng đầu)
       ├── normalization_report.json   (Thống kê dòng thô / dòng loại bỏ / dòng sạch)
       └── source_manifest.json        (SHA-256 checksum & trạng thái "ready")

+==========================================================================================+
|                       PHA 2: ONLINE QUESTION ANSWERING & OUTPUT GATE                     |
|                     (Chạy cho từng câu hỏi trong `questions.jsonl`)                      |
+==========================================================================================+

  [CHẶNG 5: ĐẦU VÀO CÂU HỎI & PROMPT TEXT-TO-SQL (B0.3 GENERATION)]
   ├── Đầu vào: `QuestionMeta(id, business_id, question, as_of_date)`
   │          + `business_context.json` (từ Chặng 4)
   ├── Biến đổi: `build_text2sql_messages()` -> `list[ChatMessage(system, user)]`
   ├── Suy luận LLM (`BaseLLM.chat`) + `parse_text2sql_response()`
   └── Đầu ra B0.3: `Text2SQLResult(status, answer_type, sql, tables_used,
                                    answer_semantics, missing_fields, reason)`
                 |
                 +------------------------------+
                 | status == "answerable"       | status == "unanswerable"
                 v                              | (Tạo `EvidenceProof` qua `evidence.py`,
  [CHẶNG 6: THỰC THI SQL AN TOÀN (B0.4)]        |  bỏ qua B0.4, gửi `not_executed`)
   ├── Đầu vào: `ExecutionRequest`              |
   ├── Kiểm duyệt: `sanitize_and_validate_sql()`|
   ├── Thực thi: `data.duckdb` (Read-Only)      |
   │   + ẩn cột `__dm_row_id`                   |
   │   + chuẩn hóa `_normalize_value()`         |
   └── Đầu ra B0.4: `ExecutionResponse`         |
       ──► `.to_b05_execution_result()`         |
                 |                              |
                 +--------------+---------------+
                                |
                                v
  [CHẶNG 7: CỔNG KIỂM DUYỆT, BOUNDED RETRY & ĐỊNH DẠNG ĐẦU RA (B0.5 GATE)]
   ├── Đầu vào: `GateRequest(question, generation, execution, evidence, attempt)`
   ├── Bước 7.1: `evaluate_answerability()` -> Kiểm chứng `catalog_verified`
   ├── Bước 7.2: `validate_execution()`     -> Kiểm tra lỗi SQL, `truncated`, shape `1x1`
   ├── Bước 7.3: `classify_error()` & `decide_retry()`
   │     ├── Nếu `action == "RETRY"` (attempt == 0):
   │     │     Sinh `RepairRequest` ──► Quay lại B0.3 `generator.repair()` (attempt = 1)
   │     └── Nếu `action == "FINAL"`:
   │           Định dạng qua `format_answer()` -> `FinalAnswer(id, type, answer, reason)`
   └── Xuất tệp (`SubmissionWriter`):
       ├── `submission.jsonl`  (Định dạng chấm điểm chính thức)
       └── `gate_trace.jsonl`  (Nhật ký kiểm toán từng câu hỏi)
```

---

## 2. Chi Tiết Biến Đổi Dữ Liệu Qua Từng Chặng

### Chặng 1 → Chặng 2: Từ Tệp Thô Đến Luồng Dòng Vật Lý (`B0.1 Readers`)

- **Thành phần xử lý:** [`readers.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py) (`CSVReader`, `XLSXReader`, `SQLiteReader`).
- **Dữ liệu đầu vào:** Các tệp vật lý trong `data/train/data/<biz_id>/` (ví dụ `SoBanHang_1.xlsx`, `SoBanHang_2026.xlsx`, `ban_hang.csv`).
- **Quá trình biến đổi dữ liệu:**
  1. **Nhận diện bảng & tiêu đề (`discover`):**
     - Với `.csv`: Tự dò bảng mã (`utf-8-sig` → `cp1258`) và ký tự phân cách (`,`, `;`, `\t`, `|`).
     - Với `.xlsx`: Quét từng sheet, dùng hàm `_score()` chấm điểm các dòng dựa trên tập từ khóa tiêu đề tiếng Việt (`ma`, `ngay`, `ten`, `tien`, `luong`, `gia`, `status`, `khach`, `don`, `hang`, ...) để tìm dòng header thật sự (`header_row`) và tách các vùng bảng độc lập (`region`) nếu một sheet có nhiều bảng.
     - Gán nhãn họ bảng logic (`logical_family`) bằng hàm `_family()`: loại bỏ hậu tố số thứ tự (`_1`, `_2`) và tên sheet tháng/năm (`Tháng 01-2025`, `T02/2026`) để các phân mảnh cùng cấu trúc được gom về chung một tên họ (ví dụ: `SoBanHang`).
  2. **Đọc dòng dữ liệu kèm công thức (`rows`):**
     - Bỏ qua các dòng trống hoàn toàn và các dòng lặp lại tiêu đề giữa chừng (nhưng giữ lại dòng dữ liệu nếu tiêu đề là tên tự sinh `column_1`, `column_2`).
     - Trả về luồng `SourceRow(number, values, formulas)`.

```text
[File Excel: SoBanHang_1.xlsx (Sheet "Tháng 02-2025")]
  Dòng 1: (Trống / Tiêu đề báo cáo)
  Dòng 2: | Mã hóa đơn | Ngày giao dịch | Hàng      | so_luong | Trị giá   | Status     |
  Dòng 3: | HD001      | 01/02/2025     | Nước suối | 2        | 20.000 đ  | Hoàn thành |
                                     |
                                     v  XLSXReader.discover() & XLSXReader.rows()
[Đối tượng SourceTable & SourceRow trong bộ nhớ]
  SourceTable(
    source_id      = "s_98aa94e13082",
    headers        = ("Mã hóa đơn", "Ngày giao dịch", "Hàng", "so_luong", "Trị giá", "Status"),
    header_row     = 2,
    logical_family = "SoBanHang"
  )
  SourceRow(
    number   = 3,
    values   = ("HD001", "01/02/2025", "Nước suối", 2, "20.000 đ", "Hoàn thành"),
    formulas = {}
  )
```

---

### Chặng 2 → Chặng 3: Làm Sạch, Chuẩn Hóa Kiểu & Xây Dựng Schema Catalog (`B0.1 Normalization & Catalog`)

- **Thành phần xử lý:** [`normalization.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/normalization.py), [`preparation.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py), [`profiling.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/profiling.py), [`schema_catalog.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py).
- **Quá trình biến đổi dữ liệu:**
  1. **Ghi bảng thô tạm thời (`raw.<source_id>`):**
     - Mọi `SourceRow` được ghi vào bảng DuckDB `raw."s_..."` với toàn bộ cột ở dạng `VARCHAR` kèm cột số thứ tự dòng gốc `__dm_source_row` và `__dm_formula_cache`.
  2. **Lọc dòng rác & Điền tiếp dữ liệu gộp dòng (Fill-down):**
     - Loại bỏ các dòng chân trang tổng hợp có ô đầu tiên là `"tổng"`, `"tổng tháng"`, `"tổng cộng"` hoặc bắt đầu bằng `"ghi chú "`.
     - Nếu file xuất phần mềm chỉ ghi `Mã hóa đơn`, `Ngày giao dịch`, `Khách`, `Status` ở dòng đầu tiên của đơn và để trống ở các dòng mặt hàng tiếp theo thuộc cùng đơn đó, bộ chuẩn hóa tự động sao chép (fill-down) thông tin cấp đơn xuống các dòng con.
  3. **Chuẩn hóa tên cột SQL & Suy luận kiểu dữ liệu (`ColumnParser`):**
     - Tên cột tiếng Việt được chuyển sang `snake_case` không dấu qua `sql_name()` (ví dụ: `"Mã hóa đơn"` → `ma_hoa_don`, `"Trị giá"` → `tri_gia`, `"Ngày giao dịch"` → `ngay_giao_dich`), đồng thời lưu tên gốc vào `provenance`.
     - Giá trị từng ô được phân tích qua `parse_number()`, `parse_date()`, `parse_bool()`:
       - Tiền tệ / số Việt Nam (`"20.000 đ"`, `"1.250.000,50"`) → `Decimal("20000")`, `Decimal("1250000.50")` → kiểu cột `DECIMAL(38,0)` hoặc `DECIMAL(38,4)`.
       - Ngày giờ (`"15/03/2026"`, `"15-03-2026 09:30"`, `"2026/03/15 10:20:30"`, số serial Excel) → `DATE` (`YYYY-MM-DD`) hoặc `TIMESTAMP` (`YYYY-MM-DDTHH:MM:SS`).
  4. **Nạp bảng chính DuckDB & Khử trùng lặp liên file:**
     - Dữ liệu đã chuẩn hóa của tất cả các phân mảnh cùng một `logical_family` được gộp vào một bảng chính duy nhất `main."<family>_<8_hex>"` (ví dụ `so_ban_hang_17d6a4c9`), gắn khóa dòng tăng dần `__dm_row_id`.
  5. **Suy luận Khóa chính & Đồ thị nối bảng (`SchemaCatalog`):**
     - `DuckDBProfileProvider` chạy truy vấn thống kê trên toàn bảng để xác định `key_candidates` (cột/cặp cột không `NULL` và không trùng lặp) và kiểm chứng các cặp khóa ngoại tiềm năng (`ma_*`, `*_id`, `id`, `sku`, `code`) qua `check_join`. Chỉ những cạnh nối có độ phủ thực tế **`coverage >= 0.8`** trên toàn bảng mới được đưa vào `join_graph` với trạng thái `validated`.

```text
[Bảng thô `raw."s_98aa94e13082"` (VARCHAR)]
  __dm_source_row | ma_hoa_don | ngay_giao_dich | hang        | so_luong | tri_gia    | status
  ----------------+------------+----------------+-------------+----------+------------+------------
  3               | "HD001"    | "01/02/2025"   | "Nước suối" | "2"      | "20.000 đ" | "Hoàn thành"
  4               | ""         | ""             | "Khăn lạnh" | "1"      | "5.000 đ"  | ""
  5               | "Tổng cộng"| ""             | ""          | "3"      | "25.000 đ" | ""
                                     |
                                     |  1. Lọc bỏ dòng 5 ("Tổng cộng")
                                     |  2. Fill-down "HD001", "01/02/2025", "Hoàn thành" xuống dòng 4
                                     |  3. Ép kiểu DATE, DECIMAL(38,0), DECIMAL(38,4)
                                     v
[Bảng chuẩn hóa `main."so_ban_hang_17d6a4c9"` trong `data.duckdb`]
  __dm_row_id (BIGINT) | ma_hoa_don (VARCHAR) | ngay_giao_dich (DATE) | hang (VARCHAR) | so_luong (DECIMAL) | tri_gia (DECIMAL) | status (VARCHAR)
  ---------------------+----------------------+-----------------------+----------------+--------------------+-------------------+-----------------
  1                    | 'HD001'              | 2025-02-01            | 'Nước suối'    | 2                  | 20000.0000        | 'Hoàn thành'
  2                    | 'HD001'              | 2025-02-01            | 'Khăn lạnh'    | 1                  | 5000.0000         | 'Hoàn thành'
```

---

### Chặng 3 → Chặng 4: Biên Dịch Quy Tắc & Đóng Gói `business_context.json` (`B0.2 Context`)

- **Thành phần xử lý:** [`rule_compiler.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/rule_compiler.py), [`context_service.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/context_service.py), [`contracts.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/contracts.py).
- **Dữ liệu đầu vào:** `SchemaCatalog` từ B0.1 + `data/<split>/rulebook.md` + `data/<split>/data/<biz_id>/README.md`.
- **Quá trình biến đổi dữ liệu:**
  1. `BusinessRuleCompiler` tách từng dòng trong bảng Markdown và từng gạch đầu dòng quy ước thành các đối tượng `BusinessRule`:
     - Quy tắc từ `README.md` của cửa hàng → `scope = "business"`, `precedence = 300`.
     - Quy tắc từ mục ngành hàng trong `rulebook.md` → `scope = "industry"`, `precedence = 200`.
     - Quy tắc mặc định trong `rulebook.md` → `scope = "split_default"`, `precedence = 100`.
  2. Hàm `_linked_fields()` quét nội dung quy tắc, đối chiếu với cả tên cột SQL (`tri_gia`) lẫn tên cột gốc tiếng Việt trong `column.provenance` (`"Trị giá"`) để điền danh sách `linked_fields = ("so_ban_hang_17d6a4c9.tri_gia", ...)`.
  3. `ContractBuilder` kết hợp toàn bộ thành tệp JSON bất biến `business_context.json`:

```json
{
  "contract_version": "b0.context.v1",
  "business_id": "biz_105",
  "schema_catalog": {
    "tables": [
      {
        "name": "so_ban_hang_17d6a4c9",
        "row_count": 138023,
        "columns": [
          {
            "name": "tri_gia",
            "data_type": "DECIMAL(38,4)",
            "nullable": true,
            "provenance": ["s_98aa94e13082:Trị giá"]
          }
        ]
      }
    ],
    "key_candidates": [...],
    "join_graph": [...]
  },
  "data_profiling": {
    "tables": {
      "so_ban_hang_17d6a4c9": {
        "date_ranges": {
          "ngay_giao_dich": {"min": "2025-02-01", "max": "2026-06-24"}
        }
      }
    }
  },
  "rule_catalog": {
    "rules": [
      {
        "rule_id": "rule_...",
        "scope": "business",
        "precedence": 300,
        "topic": "Trả hàng",
        "text": "Trả hàng: hàng trả ghi số lượng âm, cùng mã đơn với đơn đã bán...",
        "linked_fields": ["so_ban_hang_17d6a4c9.so_luong", "so_ban_hang_17d6a4c9.ma_hoa_don"]
      }
    ]
  }
}
```

---

### Chặng 4 → Chặng 5: Từ Câu Hỏi & Context Đến Kết Quả Sinh SQL (`B0.3 Text-to-SQL`)

- **Thành phần xử lý:** [`prompt.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py), [`generator.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/generator.py), [`parser.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py), [`evidence.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/evidence.py).
- **Quá trình biến đổi dữ liệu:**

```text
[1. Đầu vào câu hỏi (từ questions.jsonl)]
  {"id": "q_00558c1410ef", "business_id": "biz_105",
   "question": "tỉ lệ huỷ đơn tháng 6/2025 là nhiêu %", "as_of_date": "2026-06-24"}
          +
[2. Đầu vào ngữ cảnh (từ business_context.json)]
          |
          |  build_text2sql_messages(context, question, as_of_date)
          |  - _select_rules(): lọc bỏ ngành khác, chọn rule có precedence cao nhất mỗi topic
          v
[3. Danh sách tin nhắn gửi vào LLM: list[ChatMessage]]
  - ChatMessage(role="system", content="Bạn là chuyên gia phân tích dữ liệu và kỹ sư DuckDB SQL...")
  - ChatMessage(role="user", content="
      ### LƯỢC ĐỒ DỮ LIỆU (TABLE SCHEMAS):
      Bảng: `so_ban_hang_17d6a4c9`
        - ma_hoa_don (VARCHAR, NOT NULL) [tên gốc: \"Mã hóa đơn\"]
        - ngay_giao_dich (DATE, NOT NULL) [tên gốc: \"Ngày giao dịch\"]
        - status (VARCHAR, NOT NULL) [tên gốc: \"Status\"]
      ### PHẠM VI THỜI GIAN QUAN SÁT ĐƯỢC (DATA PROFILING):
      - so_ban_hang_17d6a4c9.ngay_giao_dich: 2025-02-01 → 2026-06-24
      ### QUY TẮC NGHIỆP VỤ (BUSINESS RULES & METRICS):
      - [rule_...] Tỉ lệ đơn huỷ trong kỳ | phần trăm đơn huỷ trong mọi đơn đặt trong kỳ...
      ### NGÀY MỐC HIỆN TẠI (AS OF DATE): 2026-06-24
      ### CÂU HỎI CỦA NGƯỜI DÙNG: tỉ lệ huỷ đơn tháng 6/2025 là nhiêu %")
          |
          |  BaseLLM.chat() -> GenerationResult(text="<think>...</think>\n{...}")
          |  parse_text2sql_response(text)
          v
[4. Đối tượng Text2SQLResult (Đầu ra chuẩn của B0.3)]
  Text2SQLResult(
    status           = "answerable",
    answer_type      = "percent",
    sql              = "SELECT COUNT(DISTINCT CASE WHEN LOWER(status) LIKE '%huỷ%' ... END) * 100.0 / ...",
    tables_used      = ("so_ban_hang_17d6a4c9",),
    assumptions      = (),
    reason           = None,
    answer_semantics = {"percent_unit": "percent_points"},
    missing_fields   = ()
  )
```

- **Chuyển đổi sang hợp đồng của B0.4 và B0.5:**
  - `Text2SQLResult.to_b05_generation_result()` → tạo đối tượng `B05GenerationResult` (nếu `answer_type == "number"` mà thiếu `numeric_kind`, hàm `_infer_numeric_kind(sql)` tự động điền `"count"`, `"money_vnd"` hoặc `"average_money_vnd"`).
  - `Text2SQLResult.to_b05_evidence_proof(context)` → tạo đối tượng `EvidenceProof` (nếu `status == "unanswerable"`, hàm `build_evidence_proof()` kiểm tra `missing_fields` trên toàn bộ `schema_catalog` để cấp `source_kind = "catalog_verified"` hoặc từ chối nếu cột thực chất có tồn tại).

---

### Chặng 5 → Chặng 6: Thực Thi SQL Chỉ Đọc & Chuẩn Hóa Kết Quả (`B0.4 Safe Executor`)

- **Thành phần xử lý:** [`sanitizer.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/sanitizer.py), [`engine.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py), [`schemas.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py).
- **Lưu ý rẽ nhánh:** Nếu `Text2SQLResult.status == "unanswerable"`, `B0Pipeline` **bỏ qua Chặng 6** và tạo thẳng `ExecutionResult(status="not_executed")` để chuyển sang Chặng 7.
- **Quá trình biến đổi dữ liệu (khi `status == "answerable"`):**

```text
[1. Đầu vào B0.4: ExecutionRequest]
  ExecutionRequest(
    question_id = "q_00558c1410ef",
    db_path     = "<bundle_dir>",      # Chứa tệp data.duckdb đã chuẩn bị ở Chặng 4
    sql_query   = "SELECT ...",
    answer_type = "percent",
    retry_count = 0,
    timeout_sec = 10.0,
    max_rows    = 10000
  )
          |
          |  1. sanitize_and_validate_sql():
          |     - Che chuỗi literal & comment, quét FORBIDDEN_KEYWORDS
          |     - Kiểm tra AST root node thuộc ALLOWED_ROOT_NODES (Select/Union/...)
          |  2. duckdb.connect("<bundle_dir>/data.duckdb", read_only=True)
          |  3. cursor.fetchmany(max_rows + 1)  -> Phát hiện cờ `truncated`
          |  4. Lọc bỏ các cột nội bộ bắt đầu bằng `__dm_` (như `__dm_row_id`)
          |  5. _normalize_value(): Decimal -> int/float, date/datetime -> ISO str, bool -> bool
          v
[2. Đầu ra B0.4: ExecutionResponse]
  ExecutionResponse(
    question_id       = "q_00558c1410ef",
    is_valid          = True,
    route             = "yes",
    cleaned_sql       = "SELECT ...",
    columns           = ["ti_le_huy"],
    rows              = [{"ti_le_huy": 2.0833333333333335}],
    row_count         = 1,
    truncated         = False,
    error_type        = None,
    error_message     = None,
    execution_time_ms = 14.2
  )
          |
          |  response.to_b05_execution_result()
          |  (Chuyển `rows` từ list[dict] sang ma trận 2 chiều `list[list[Any]]`)
          v
[3. Đầu vào cho B0.5: ExecutionResult]
  ExecutionResult(
    status     = "success",
    columns    = ["ti_le_huy"],
    rows       = [[2.0833333333333335]],
    row_count  = 1,
    truncated  = False,
    elapsed_ms = 14.2,
    error      = None
  )
```

---

### Chặng 6 → Chặng 7: Cổng Kiểm Duyệt, Vòng Lặp Bounded Retry & Xuất Tệp (`B0.5 Output Gate`)

- **Thành phần xử lý:** [`gate.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/gate.py), [`answerability.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/answerability.py), [`validators.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/validators.py), [`retry.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py), [`formatter.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py), [`writer.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/writer.py).
- **Dữ liệu đầu vào:** `GateRequest(contract_version="b05.v1", question, generation, execution, evidence, attempt)`.

#### Cây quyết định biến đổi dữ liệu bên trong `evaluate_gate(request)`:

```text
                            [GateRequest (attempt = 0 hoặc 1)]
                                            |
                                            v
                    +-----------------------------------------------+
                    | Bước 1: evaluate_answerability(request)       |
                    | Có `source_kind == "catalog_verified"`        |
                    | VÀ `capability_status == "unsupported"`?      |
                    +-----------------------------------------------+
                         /                                     \
               ĐÚNG (Có bằng chứng)                     SAI (Không có / bị bác bỏ)
                       /                                         \
                      v                                           v
      +-------------------------------+           +-----------------------------------+
      | action   = "FINAL"            |           | LLM có tự khai                    |
      | decision = "unanswerable"     |           | `answer_type == "unanswerable"`?  |
      | FinalAnswer(                  |           +-----------------------------------+
      |   id     = q_id,              |                  /                     \
      |   type   = "unanswerable",    |            ĐÚNG /                       \ SAI (Câu hỏi answerable)
      |   reason = "Dữ liệu được..."  |                v                         v
      | )                             |   +------------------------+   +----------------------------------+
      +-------------------------------+   | action   = "FINAL"     |   | Bước 2: validate_execution()     |
                                          | decision = "abstain"   |   | - Lỗi thực thi SQL (`error`)?    |
                                          | reason   = MISSING_EVID|   | - Bị cắt dòng (`truncated`)?     |
                                          +------------------------+   | - Kết quả rỗng (`row_count==0`)? |
                                                                       | - Sai kích thước (Scalar != 1x1, |
                                                                       |   List != Nx1)?                  |
                                                                       | - Giá trị Scalar là `NULL`?      |
                                                                       +----------------------------------+
                                                                              /                    \
                                                                KHÔNG HỢP LỆ /                      \ HỢP LỆ (Passed)
                                                                            v                        v
                                                        +-------------------------------+   +-------------------------------+
                                                        | Bước 3: classify_error()      |   | Bước 4: format_answer()       |
                                                        | & decide_retry()              |   | Chuẩn hóa theo `answer_type`  |
                                                        | `retryable == True`           |   | & `answer_semantics`:         |
                                                        | VÀ `attempt == 0`?            |   | - number (VND -> int,         |
                                                        +-------------------------------+   |   generic -> int/float 2 số)  |
                                                               /                 \          | - percent (2 chữ số thập phân)|
                                                         ĐÚNG /                   \ SAI     | - date ("YYYY-MM-DD")         |
                                                             v                     v        | - boolean (True/False)        |
                                            +------------------------+   +----------------+ | - list ([...])                |
                                            | action   = "RETRY"     |   | action="FINAL" | | - table ({"columns","rows"})  |
                                            | decision = "retry"     |   | decision=      | +-------------------------------+
                                            | Sinh `RepairRequest`   |   |   "abstain"    |                 |
                                            | ──► Quay về B0.3       |   +----------------+                 v
                                            | `generator.repair()`   |                      +-------------------------------+
                                            | chạy lại với attempt=1 |                      | action   = "FINAL"            |
                                            +------------------------+                      | decision = "answer"           |
                                                                                            | FinalAnswer(id, type, answer) |
                                                                                            +-------------------------------+
```

---

## 3. Bảng Tổng Hợp Các Hợp Đồng Dữ Liệu (Data Contracts) Giữa Các Module

| Điểm giao cắt | Đối tượng / Tệp nguồn | Phương thức chuyển đổi (Adapter) | Đối tượng / Tệp đích | Các trường dữ liệu cốt lõi được truyền |
| :--- | :--- | :--- | :--- | :--- |
| **Đĩa → B0.1** | `.csv`, `.xlsx`, `.sqlite` | `READERS[ext].discover()` & `.rows()` | `SourceTable`, `SourceRow` | `source_id`, `headers`, `header_row`, `logical_family`, `values`, `formulas` |
| **B0.1 → B0.2** | `data.duckdb` | `DuckDBMetadataProvider.load()` & `SchemaCatalogBuilder.build()` | `BusinessMetadata`, `SchemaCatalog` | `tables`, `columns` (kèm `provenance`), `key_candidates`, `join_graph` (đã lọc `coverage >= 0.8`) |
| **B0.2 → Đĩa** | `SchemaCatalog` + `RuleCatalog` | `BusinessContextService.prepare()` → `.to_dict()` | `business_context.json` | `schema_catalog`, `data_profiling.tables.*.date_ranges`, `rule_catalog.rules` (kèm `precedence`, `linked_fields`), `answerability_constraints` |
| **B0.2 → B0.3** | `business_context.json` + `QuestionMeta` | `build_text2sql_messages()` | `list[ChatMessage]` | Lược đồ bảng, tên cột gốc tiếng Việt, gợi ý JOIN, khoảng ngày min→max, danh sách Rule đã lọc theo `industry` và `precedence` |
| **B0.3 → B0.4** | `Text2SQLResult` | `ExecutionRequest.from_b03()` (hoặc tạo trong `B0Pipeline`) | `ExecutionRequest` | `question_id`, `db_path` (trỏ tới `bundle_dir`), `sql_query`, `answer_type`, `retry_count` |
| **B0.3 → B0.5** | `Text2SQLResult` + `business_context.json` | `.to_b05_generation_result()` & `.to_b05_evidence_proof(ctx)` | `B05GenerationResult`, `EvidenceProof` | `answer_type` (7 kiểu chuẩn), `sql`, `answer_semantics` (đã suy luận `numeric_kind`), `source_kind` (`"catalog_verified"` hoặc `"unverified"`), `missing_fields` |
| **B0.4 → B0.5** | `ExecutionResponse` | `.to_b05_execution_result()` | `ExecutionResult` | `status` (`"success"` / `"error"`), `columns` (đã ẩn `__dm_row_id`), `rows` (ma trận 2D đã chuẩn hóa kiểu Python), `row_count`, `truncated`, `error` |
| **B0.5 → B0.3 (Retry)** | `GateOutcome` (`action == "RETRY"`) | `B0Pipeline.answer_question()` → `generator.repair()` | `list[ChatMessage]` (Prompt sửa lỗi) | `previous_sql` (`failed_sql`), `error_message` (`[error_type] message + instruction`), `attempt = 1` |
| **B0.5 → Đĩa** | `GateOutcome` (`action == "FINAL"`) | `SubmissionWriter.write_final()` | `submission.jsonl`, `gate_trace.jsonl` | Dòng JSONL nộp bài `{"id", "type", "answer"}` (hoặc `unanswerable` / `abstain`) và bản ghi trace đầy đủ |

---

## 4. Định Dạng Dữ Liệu Đầu Ra Cuối Cùng (`submission.jsonl` & `gate_trace.jsonl`)

Khi `B0Pipeline.run_questions()` kết thúc, `SubmissionWriter` ghi ra 2 tệp trong thư mục `output_dir`:

### 4.1. Tệp nộp bài chính thức: `submission.jsonl`
Mỗi dòng tương ứng với đúng 1 câu hỏi (được khử trùng lặp theo `id`), tuân thủ nghiêm ngặt quy tắc cấu trúc của từng loại câu trả lời:

```jsonl
{"id": "q_001883280e83", "type": "number", "answer": 89526400}
{"id": "q_00558c1410ef", "type": "percent", "answer": 2.08}
{"id": "q_date_example", "type": "date", "answer": "2026-03-16"}
{"id": "q_bool_example", "type": "boolean", "answer": true}
{"id": "q_list_example", "type": "list", "answer": ["SP01", "SP02", "SP03"]}
{"id": "q_table_example", "type": "table", "answer": {"columns": ["ma_don", "thanh_tien"], "rows": [["D1", 100000], ["D2", 250000]]}}
{"id": "q_unanswerable_example", "type": "unanswerable", "reason": "Dữ liệu được kiểm chứng thiếu các trường thông tin: chi_phi_quang_cao"}
{"id": "q_abstain_example", "type": "abstain"}
```

> **Quy tắc bất biến trên `submission.jsonl`:**
> - Khi `type == "abstain"`: Chỉ có đúng 2 trường `"id"` và `"type"`, **tuyệt đối không có trường `"answer"` hay `"reason"`**.
> - Khi `type == "unanswerable"`: Chỉ có `"id"`, `"type"` và `"reason"` (tùy chọn), **tuyệt đối không có trường `"answer"`**.
> - Khi `type` thuộc 7 kiểu trả lời (`number`, `percent`, `string`, `date`, `boolean`, `list`, `table`): Luôn có trường `"answer"` đã được chuẩn hóa kiểu JSON thuần (không còn `Decimal` hay `datetime`).

### 4.2. Tệp nhật ký kiểm toán: `gate_trace.jsonl`
Lưu lại toàn bộ quyết định của cổng B0.5 cho từng câu hỏi để phục vụ gỡ lỗi (debug) và phân tích sai số:

```json
{
  "question_id": "q_00558c1410ef",
  "action": "FINAL",
  "decision": "answer",
  "reason_code": "VALID_RESULT",
  "retry_count": 0,
  "validation": {
    "passed": true,
    "errors": [],
    "warnings": []
  },
  "final_answer": {
    "id": "q_00558c1410ef",
    "type": "percent",
    "answer": 2.08
  }
}
```

