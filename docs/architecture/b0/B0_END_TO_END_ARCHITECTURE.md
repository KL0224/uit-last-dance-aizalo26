# Kiến Trúc & Luồng Hoạt Động Tổng Thể Hệ Thống B0 (End-to-End B0.1 → B0.5)

> **Dự án:** DataMate 2026 — Hệ thống hỏi đáp định lượng trên dữ liệu doanh nghiệp bán lẻ Việt Nam (Text-to-SQL Baseline B0)  
> **Phạm vi tài liệu:** Mô tả chi tiết luồng hoạt động End-to-End từ lúc tiếp nhận bộ dữ liệu thô (`data/train`, `data/public_test`) đi qua **B0.1 → B0.2 → B0.3 → B0.4 → B0.5** cho đến khi xuất ra tệp kết quả chấm điểm `submission.jsonl` và nhật ký kiểm toán `gate_trace.jsonl`.  
> **Điểm vào điều phối chính (Entrypoint):** [`B0Pipeline`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/pipeline.py#L28-L214) trong [`src/datamate/b0/pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/pipeline.py).

---

## 1. Cấu Trúc Bộ Dữ Liệu Thực Tế (`data/train` & `data/public_test`)

Hệ thống vận hành trên 2 tập dữ liệu chuẩn nằm trong thư mục `data/`:
- **Bộ huấn luyện / đối chuẩn (`data/train/`):** Gồm **30 doanh nghiệp** (`biz_101` → `biz_130`), tệp câu hỏi `questions.jsonl`, đáp án chuẩn `answers.jsonl`, sổ tay quy tắc mặc định toàn giải `rulebook.md`, và bảng lịch âm-dương `calendar.csv`.
- **Bộ kiểm thử công khai (`data/public_test/`):** Gồm **14 doanh nghiệp** (`dev_001` → `dev_014`), `questions.jsonl`, `rulebook.md`, và `calendar.csv`.

```text
data/
├── train/
│   ├── rulebook.md                # Quy tắc nghiệp vụ mặc định toàn giải (split_default, precedence=100)
│   ├── calendar.csv               # Bảng tra cứu lịch Âm - Dương & mùa Tết
│   ├── questions.jsonl            # Câu hỏi đầu vào: {"id", "business_id", "question", "as_of_date"}
│   ├── answers.jsonl              # Đáp án chuẩn (chỉ có ở train): {"id", "type", "answer", "alias"}
│   └── data/
│       ├── biz_101/               # Dữ liệu CSV đơn bảng (`ban_hang.csv` + `README.md`)
│       ├── biz_105/               # Dữ liệu Excel đa sheet theo tháng (`SoBanHang_1.xlsx`, `SoBanHang_2026.xlsx`, ...)
│       ├── biz_124/               # Dữ liệu kết hợp phần mềm (`BanHang_*.xlsx`), sổ tay (`SoTay_*.xlsx`) & `ton_kho.csv`
│       ├── biz_128/               # Dữ liệu nhà hàng/quán ăn đa bảng (`DanhSachHoaDon.xlsx`, `DanhSachHoaDonPhongBan.xlsx`, ...)
│       └── ... (biz_101..biz_130)
└── public_test/
    ├── rulebook.md
    ├── calendar.csv
    ├── questions.jsonl
    └── data/
        └── dev_001 .. dev_014/
```

### Đặc trưng thực tế của dữ liệu doanh nghiệp trong bộ dữ liệu:
1. **Đa định dạng nguồn:** `.csv` (nhiều bảng mã `utf-8-sig`, `cp1258`, dấu phân cách `,`, `;`, `\t`, `|`), `.xlsx` (nhiều sheet theo tháng như `Tháng 01-2025`, dòng tiêu đề không nằm ở dòng 1, chứa dòng tổng cộng cuối bảng hoặc ô công thức Excel), và `.sqlite`/`.db`.
2. **Gộp phân mảnh theo họ bảng (Logical Family):** Ví dụ tại `biz_105`, hai tệp `SoBanHang_1.xlsx` và `SoBanHang_2026.xlsx` chứa **17 sheets** theo từng tháng (tổng cộng **138.023 dòng**). B0.1 tự động phát hiện chúng cùng họ `SoBanHang` và hợp nhất thành một bảng chuẩn hóa duy nhất `so_ban_hang_17d6a4c9`.
3. **Quy tắc nghiệp vụ đa tầng:** Luật chung nằm ở `rulebook.md` (ví dụ: cách tính doanh thu, đơn hủy, ca sáng/ca chiều, kỳ tháng này tính đến `as_of_date`), trong khi luật đặc thù của từng cửa hàng nằm ở `data/<biz_id>/README.md` (ví dụ tại `biz_105`: *"hàng trả ghi số lượng âm, cùng mã đơn với đơn đã bán: đơn có dòng số lượng âm là đơn có trả hàng"*).

---

## 2. Sơ Đồ Kiến Trúc Tổng Thể Luồng Hoạt Động B0 (B0.1 → B0.5)

```text
+========================================================================================+
|                        GIAI ĐOẠN 1: OFFLINE BUNDLE PREPARATION                         |
|                    B0Pipeline.prepare_bundle(business_dir, output_dir)                 |
+========================================================================================+
  [data/train/data/biz_XXX/*]  +  [data/train/rulebook.md]  +  [data/train/calendar.csv]
                 |
                 v
  +------------------------------------------------------------------------------------+
  | MODULE B0.1: DATA INGESTION & SCHEMA CATALOG (src/datamate/b0/b01/)                |
  |  1. Readers (readers.py): Quét CSV/XLSX/SQLite, tìm dòng header, giữ tên cột gốc.  |
  |  2. Normalization (normalization.py): Chuẩn hóa số, tiền VND, 14+ định dạng ngày,  |
  |     loại bỏ dòng "Tổng cộng" / lặp header, điền tiếp (fill-down) mã đơn gộp dòng.  |
  |  3. DuckDB Materialization (preparation.py): Ghi bảng vào `data.duckdb`, đánh      |
  |     khóa dòng nội bộ `__dm_row_id` và lưu vết nguồn `raw.<source_id>`.             |
  |  4. Profiling & Schema Catalog (profiling.py, schema_catalog.py):                  |
  |     - Thống kê null_count, distinct_count, min/max date trên toàn bảng DuckDB.     |
  |     - Suy luận khóa chính (`key_candidates`) & đồ thị nối bảng (`join_graph`)      |
  |       với kiểm chứng độ phủ SQL toàn bảng >= 80%.                                  |
  +------------------------------------------------------------------------------------+
                 |
                 v
  +------------------------------------------------------------------------------------+
  | MODULE B0.2: BUSINESS RULE COMPILER & CONTEXT CONTRACT (src/datamate/b0/b02/)      |
  |  1. Rule Compiler (rule_compiler.py): Đọc `README.md` (scope="business", prec=300) |
  |     & `rulebook.md` (scope="split_default", prec=100; "industry", prec=200).       |
  |  2. Field Linking: Ánh xạ cả tên cột SQL (`tri_gia`) lẫn tên gốc tiếng Việt        |
  |     trong `provenance` (`"Trị giá"`) vào `linked_fields`.                          |
  |  3. Contract Builder (contracts.py): Đóng gói thành `business_context.json`.       |
  +------------------------------------------------------------------------------------+
                 |
                 v
  [Thư mục Bundle bất biến: `<output_dir>/<biz_id>/<sha256_cache_key>/`]
   ├── data.duckdb                 (Cơ sở dữ liệu phân tích đã chuẩn hóa kiểu)
   ├── business_context.json       (Hợp đồng ngữ cảnh B0.1 + B0.2 cho B0.3 & B0.5)
   ├── foundation_metadata.json    (Siêu dữ liệu bảng và cột vật lý)
   ├── normalization_report.json   (Báo cáo thống kê số dòng thô / chuẩn hóa / loại bỏ)
   └── source_manifest.json        (Băm SHA-256 toàn vẹn nguồn & trạng thái "ready")

+========================================================================================+
|                     GIAI ĐOẠN 2: ONLINE QUESTION ANSWERING PIPELINE                    |
|              B0Pipeline.run_questions(questions, bundles, output_dir)                  |
+========================================================================================+
  Câu hỏi từ `questions.jsonl`: {"id", "business_id", "question", "as_of_date"}
                 |
                 v
  +------------------------------------------------------------------------------------+
  | MODULE B0.3: TEXT-TO-SQL LLM LAYER (src/datamate/b0/b03/)                          |
  |  1. Prompt Builder (prompt.py):                                                    |
  |     - Kết xuất bảng, kiểu dữ liệu, `[tên gốc: "..."]`, `[Khóa chính: ...]`.        |
  |     - Kết xuất `[Gợi ý JOIN bảng]` từ `join_graph` & khoảng thời gian `min -> max`.|
  |     - Lọc rule qua `_select_rules()`: loại bỏ ngành khác, chỉ giữ rule có          |
  |       `precedence` cao nhất cho mỗi `topic`.                                       |
  |  2. Generator & Parser (generator.py, parser.py):                                  |
  |     - Gọi LLM (`VLLMModel` / `BaseLLM`), xóa khối `<think>...</think>`.            |
  |     - Chuẩn hóa `answer_type` về 7 kiểu hợp lệ; trích `tables_used` bằng `sqlglot`.|
  |     - Tự suy luận `numeric_kind` (`count`, `money_vnd`, `average_money_vnd`).      |
  |  3. Evidence Verifier (evidence.py):                                               |
  |     - Nếu `status == "unanswerable"`: kiểm tra `missing_fields` trên toàn bộ       |
  |       `schema_catalog` để cấp bằng chứng `catalog_verified` hoặc bác bỏ ảo giác.   |
  +------------------------------------------------------------------------------------+
                 |
       +---------+---------------------------------------------------+
       | Nhánh A: status == "answerable"                             | Nhánh B: status == "unanswerable"
       v                                                             | (Bỏ qua thực thi SQL ở B0.4,
  +--------------------------------------------------------------+   |  gửi `status="not_executed"`
  | MODULE B0.4: SAFE SQL EXECUTION LAYER (src/datamate/b0/b04/) |   |  kèm `EvidenceProof` sang B0.5)
  |  1. Sanitizer (sanitizer.py):                                |   |
  |     - Che literal & comment trước khi quét `FORBIDDEN_KEYWORDS`| |
  |     - Kiểm tra nút gốc AST thuộc `ALLOWED_ROOT_NODES`        |   |
  |       (`Select`, `Union`, `Intersect`, `Except`, `Subquery`).|   |
  |  2. DuckDB Read-Only Engine (engine.py):                     |   |
  |     - Mở trực tiếp `bundle_dir/data.duckdb` ở chế độ R/O.    |   |
  |     - Thực thi với watchdog timeout (`timeout_sec=10.0s`).   |   |
  |     - Đọc `fetchmany(max_rows + 1)` để phát hiện `truncated`.|   |
  |     - Ẩn cột nội bộ `__dm_row_id` khỏi kết quả `SELECT *`.   |   |
  |     - Chuẩn hóa kiểu Python (`Decimal`, `date`, `bool`).     |   |
  +--------------------------------------------------------------+   |
       |                                                             |
       +-----------------------------+-------------------------------+
                                     |
                                     v
  +------------------------------------------------------------------------------------+
  | MODULE B0.5: BASIC OUTPUT GATE & VALIDATION (src/datamate/b0/b05/)                 |
  |  1. Evidence Answerability (answerability.py):                                     |
  |     - Có `catalog_verified` + `unsupported` -> Quyết định `FINAL (unanswerable)`.  |
  |     - Tự nhận `unanswerable` nhưng không qua được kiểm chứng -> `FINAL (abstain)`. |
  |  2. Execution & Shape Validator (validators.py):                                   |
  |     - Kiểm tra lỗi thực thi SQL, cờ `truncated`, kết quả rỗng, lệch hình dạng      |
  |       (`number`/`string`/`date`/`boolean`/`percent` đòi hỏi đúng 1 dòng x 1 cột).  |
  |  3. Bounded Retry Classifier (retry.py):                                           |
  |     - Nếu lỗi thuộc nhóm sửa được (`SyntaxError`, `CatalogError`, `BinderError`,   |
  |       `DataError`, `EmptyQueryError`, `SCALAR_SHAPE_MISMATCH`) VÀ `attempt == 0`   |
  |       --> Phát tín hiệu `GateAction.RETRY` kèm `RepairRequest`.                    |
  |  4. Typed Output Formatter (formatter.py):                                         |
  |     - Định dạng chuẩn xác theo `NumericKind` (làm tròn VND bằng `ROUND_HALF_UP`),  |
  |       chuẩn hóa ngày `YYYY-MM-DD`, chuyển đổi `boolean`, `list`, `table`.          |
  +------------------------------------------------------------------------------------+
                 |                                           |
                 | Nếu `action == "RETRY"` (attempt == 0)    | Nếu `action == "FINAL"`
                 v                                           v
  +----------------------------------------------+   +---------------------------------+
  | VÒNG LẶP BOUNDED RETRY (TỐI ĐA 1 LẦN)        |   | SUBMISSION WRITER (writer.py)   |
  | `generator.repair()` nhận `previous_sql` +   |   | - Ghi `submission.jsonl`        |
  | `error_message` -> chạy lại B0.4 & B0.5      |   | - Ghi `gate_trace.jsonl`        |
  | với `attempt = 1` (nếu vẫn lỗi -> `abstain`).|   +---------------------------------+
  +----------------------------------------------+
```

---

## 3. Chi Tiết Hoạt Động Của Từng Module (B0.1 → B0.5) Kèm Minh Chứng Thực Tế

### 3.1. Module B0.1: Data Ingestion, Normalization & Schema Catalog
- **Vị trí mã nguồn:** [`src/datamate/b0/b01/`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/)
- **Điểm vào chính:** [`prepare_business()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py#L95-L335) trong [`preparation.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py).

#### Các bước xử lý bên trong B0.1:
1. **Khám phá nguồn dữ liệu (`readers.py`):**
   - [`CSVReader`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L188-L259), [`XLSXReader`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L262-L420), và [`SQLiteReader`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L423-L476) quét toàn bộ tệp trong thư mục doanh nghiệp.
   - Tự động chấm điểm dòng tiêu đề (`_score`) dựa trên từ điển từ khóa nghiệp vụ tiếng Việt (`ma`, `ngay`, `ten`, `tien`, `luong`, `gia`, `khach`, `don`, `hang`, ...).
   - Tự động gom các tệp phân mảnh hoặc các sheet theo tháng (như `SoBanHang_1.xlsx` và `SoBanHang_2026.xlsx` của `biz_105`) vào cùng một `logical_family` (`SoBanHang`).
   - Bảo vệ các cột có tiêu đề tự sinh (`column_1`, `column_2`) qua hàm [`_is_repeated_header`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L169-L174) và chỉ lazy-open workbook công thức `.xlsx` tối đa 1 lần cho mỗi tệp.
2. **Làm sạch & Chuẩn hóa kiểu dữ liệu (`normalization.py`):**
   - [`ColumnParser`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/normalization.py#L230-L315) phân tích từng cột để chọn kiểu SQL tối ưu (`DECIMAL(38,0)`, `DECIMAL(38,4)`, `BIGINT`, `DATE`, `TIMESTAMP`, `BOOLEAN`, `VARCHAR`).
   - Hỗ trợ hơn 14 định dạng ngày/giờ Việt Nam và ISO trong [`parse_date`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/normalization.py#L102-L163) (bao gồm `dd/mm/yyyy`, `dd-mm-yyyy HH:MM`, `yyyy-mm-dd HH:MM`, số serial ngày Excel).
   - Loại bỏ các dòng tổng cộng cuối bảng (`Tổng`, `Tổng tháng`, `Tổng cộng`, `Ghi chú...`) và các dòng lặp lại tiêu đề giữa bảng.
   - Tự động điền tiếp (fill-down) thông tin cấp đơn hàng (`ma_hoa_don`, `ngay_giao_dich`, `khach`, `status`) cho các bảng xuất từ phần mềm chỉ ghi mã đơn ở dòng đầu tiên của mỗi đơn.
3. **Nạp DuckDB & Suy luận Schema Catalog (`profiling.py` & `schema_catalog.py`):**
   - Ghi toàn bộ dữ liệu chuẩn hóa vào `data.duckdb` kèm cột định danh dòng vật lý `__dm_row_id`.
   - [`DuckDBProfileProvider`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/profiling.py#L31-L133) truy vấn trực tiếp trên `data.duckdb` để lấy `null_count`, `distinct_count`, `min/max` cho các cột ngày/thời gian.
   - [`SchemaCatalogBuilder`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L37-L300) suy luận khóa chính (`key_candidates`) và đề xuất các cặp khóa nối bảng (`ma_*`, `*_id`, `id`, `sku`, `code`), sau đó gọi `check_join` kiểm tra độ phủ thực tế trên toàn bảng DuckDB (chỉ giữ cạnh nối có độ phủ `coverage >= 0.8`).

#### Minh chứng thực tế khi chạy B0.1 trên `data/train/data/biz_105`:
- **Đầu vào:** 6 tệp `.xlsx` (`BangGia.xlsx`, `DanhMuc.xlsx`, `SoBanHang_1.xlsx`, `SoBanHang_2026.xlsx`, `SoNhapHang.xlsx`, `TonKho.xlsx`) + `README.md`.
- **Đầu ra bảng trong `data.duckdb`:**
  - `so_ban_hang_17d6a4c9`: **138.023 dòng** (hợp nhất từ 17 sheets tháng của 2 tệp `SoBanHang_1.xlsx` và `SoBanHang_2026.xlsx`), các cột được chuẩn hóa thành `hang (VARCHAR)`, `so_luong (DECIMAL(38,0))`, `tri_gia (DECIMAL(38,4))`, `status (VARCHAR)`, `gia_le (DECIMAL(38,0))`, `gio (TIMESTAMP)`, `ma_hoa_don (VARCHAR)`, `ngay_giao_dich (DATE)`, `khach (VARCHAR)`.
  - `so_nhap_hang_3fc02a9b`: **1.373 dòng** (`Khóa chính: so_phieu+ten_mat_hang`).
  - `bang_gia_532c31ba`: **78 dòng** (`Khóa chính: ngay_ap_dung+ten_hang`).
  - `ton_kho_9137e3d2`: **50 dòng** (`Khóa chính: hang_hoa`).
  - `danh_muc_7f781a3a`: **2 dòng** (`Khóa chính: ten_mon`).

---

### 3.2. Module B0.2: Business Rule Compiler & Context Contract
- **Vị trí mã nguồn:** [`src/datamate/b0/b02/`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/)
- **Điểm vào chính:** [`BusinessContextService.prepare()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/context_service.py#L28-L82) trong [`context_service.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/context_service.py).

#### Các bước xử lý bên trong B0.2:
1. **Biên dịch quy tắc từ Markdown (`rule_compiler.py`):**
   - Đọc các bảng Markdown và danh sách gạch đầu dòng từ `data/train/rulebook.md` và `data/train/data/<biz_id>/README.md`.
   - Gán phạm vi (`scope`) và độ ưu tiên (`precedence`) rõ ràng:
     - Quy tắc trong `README.md` của doanh nghiệp: `scope = "business"`, **`precedence = 300`** (ưu tiên cao nhất).
     - Quy tắc ngành hàng trong `rulebook.md` (ví dụ: *Nhà thuốc*, *Quán ăn*, *Thời trang*): `scope = "industry"`, **`precedence = 200`**.
     - Quy tắc mặc định toàn giải trong `rulebook.md`: `scope = "split_default"`, **`precedence = 100`**.
2. **Liên kết trường dữ liệu (`_linked_fields`):**
   - Đối chiếu nội dung từng quy tắc với cả tên cột SQL đã chuẩn hóa (`tri_gia`, `ngay_giao_dich`) lẫn **tên cột gốc tiếng Việt** lưu trong `column.provenance` (`"Trị giá"`, `"Ngày giao dịch"`) để gắn kết chính xác quy tắc với cột vật lý trong bảng.
3. **Đóng gói Hợp đồng Ngữ cảnh (`business_context.json`):**
   - [`ContractBuilder`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/contracts.py#L228-L320) kiểm tra tính toàn vẹn (mọi cạnh nối trong `join_graph` phải trỏ tới bảng và cột có thật; mọi rule phải thuộc đúng `business_id` hoặc `global`) trước khi xuất ra tệp `business_context.json`.

---

### 3.3. Module B0.3: Text-to-SQL LLM Layer & Evidence Verifier
- **Vị trí mã nguồn:** [`src/datamate/b0/b03/`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/)
- **Điểm vào chính:** [`Text2SQLGenerator`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/generator.py#L13-L59) trong [`generator.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/generator.py).

#### Các bước xử lý bên trong B0.3:
1. **Xây dựng Prompt có chọn lọc (`prompt.py`):**
   - [`format_context_for_prompt()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py#L136-L249) chuyển `business_context.json` thành văn bản cấu trúc gồm 3 phần:
     - **`LƯỢC ĐỒ DỮ LIỆU (TABLE SCHEMAS)`:** Liệt kê từng bảng, khóa chính `[Khóa chính: ...]`, từng cột kèm kiểu SQL, `NULL/NOT NULL`, `[tên gốc: "..."]`, và `[Gợi ý JOIN bảng]` từ `join_graph`.
     - **`PHẠM VI THỜI GIAN QUAN SÁT ĐƯỢC (DATA PROFILING)`:** Hiển thị khoảng thời gian thực tế có trong từng cột ngày (ví dụ tại `biz_105`: `so_ban_hang_17d6a4c9.ngay_giao_dich: 2025-02-01 → 2026-06-24`).
     - **`QUY TẮC NGHIỆP VỤ (BUSINESS RULES & METRICS)`:** Hàm [`_select_rules()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py#L103-L133) lọc bỏ các quy tắc của ngành khác và chỉ giữ lại quy tắc có `precedence` cao nhất cho mỗi chủ đề (`topic`).
2. **Phân tích đầu ra LLM & Chuẩn hóa Ngữ nghĩa (`parser.py` & `types.py`):**
   - [`parse_text2sql_response()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L156-L270) tự động bóc tách khối suy luận `<think>...</think>` (nếu dùng mô hình Qwen3/DeepSeek R1), giải mã JSON hoặc khối mã ```sql ... ```.
   - [`normalize_answer_type()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L44-L66) ánh xạ mọi biến thể kiểu trả lời (`int`, `float`, `money`, `text`, `timestamp`, ...) về đúng **7 kiểu trả lời hợp lệ** (`number`, `percent`, `string`, `date`, `boolean`, `list`, `table`), tuyệt đối không sinh kiểu `"generic"`.
   - [`extract_tables_from_sql()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L69-L115) phân tích cây cú pháp AST bằng `sqlglot` để trích xuất danh sách bảng thực sự được truy vấn (loại trừ tên bảng ảo CTE `WITH ... AS` và biểu thức `EXTRACT(MONTH FROM col)`).
   - [`_infer_numeric_kind()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L182-L194) tự động suy luận ngữ nghĩa số cho B0.5:
     - `SELECT COUNT(...)` → `numeric_kind = "count"`
     - `SELECT SUM(tri_gia)` / `SUM(thanh_tien)` → `numeric_kind = "money_vnd"`
     - `SELECT AVG(tri_gia)` / `AVG(don_gia)` → `numeric_kind = "average_money_vnd"`
3. **Kiểm chứng bằng chứng `unanswerable` (`evidence.py`):**
   - Khi LLM trả `status = "unanswerable"`, phương thức [`Text2SQLResult.to_b05_evidence_proof(context)`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L166-L174) gọi [`build_evidence_proof()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/evidence.py#L61-L154) để đối chiếu danh sách `missing_fields` với toàn bộ cột trong `schema_catalog`:
     - Nếu tất cả các trường báo thiếu thực sự **không tồn tại** trong bất kỳ bảng nào của doanh nghiệp → trả về `EvidenceProof(source_kind="catalog_verified", capability_status="unsupported", checked_all_sources=True)`.
     - Nếu LLM báo thiếu một cột mà thực tế **đang tồn tại** trong bảng (ảo giác của LLM) → bác bỏ bằng cách trả `EvidenceProof(source_kind="unverified", capability_status="supported")` để B0.5 chặn lại và hạ xuống `abstain`.

---

### 3.4. Module B0.4: Safe SQL Execution Layer
- **Vị trí mã nguồn:** [`src/datamate/b0/b04/`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/)
- **Điểm vào chính:** [`execute_query()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L118-L320) trong [`engine.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py).

#### Các bước xử lý bên trong B0.4:
1. **Kiểm duyệt An ninh SQL 3 lớp (`sanitizer.py`):**
   - **Lớp 1:** Bóc tách `<think>...</think>` và markdown code block để lấy câu lệnh SQL thuần.
   - **Lớp 2:** Che (mask) toàn bộ chuỗi ký tự `'...'`, định danh `"..."` và chú thích `--` / `/*...*/` trước khi quét biểu thức chính quy `FORBIDDEN_KEYWORDS` (`DROP`, `DELETE`, `UPDATE`, `INSERT`, `COPY`, `ATTACH`, `INSTALL`, ...). Nhờ đó các câu truy vấn hợp lệ như `WHERE status = 'delete'` hoặc `WHERE ghi_chu LIKE '%update%'` không bị chặn nhầm.
   - **Lớp 3:** Phân tích AST qua `sqlglot` (`dialect="duckdb"`), bắt buộc câu lệnh phải là đơn câu lệnh (single statement) và nút gốc phải thuộc `ALLOWED_ROOT_NODES` (`Select`, `Union`, `Intersect`, `Except`, `Subquery`). Mọi lệnh `TRUNCATE`, `SHOW`, `DESCRIBE`, `CALL` đều bị chặn với ngoại lệ `SecurityViolation`. Riêng các lỗi gõ sai cú pháp `SELEC * FORM ...` được phép đi tiếp xuống DuckDB để nhận thông báo `SyntaxError` chi tiết phục vụ bước Retry.
2. **Thực thi Cô lập Read-Only trên DuckDB (`engine.py` & `schemas.py`):**
   - Khi `db_path` trỏ tới thư mục bundle của B0.1, `engine.py` phát hiện tệp `data.duckdb` bên trong và mở kết nối trực tiếp ở chế độ `read_only=True`.
   - Khởi chạy luồng giám sát thời gian chạy (`watchdog timer`, mặc định `10.0s`); nếu truy vấn bị treo hoặc chạy quá lâu, gọi `con.interrupt()` và trả lỗi `TimeoutError`.
   - Đọc tối đa `max_rows + 1` dòng (`10.001` dòng): nếu vượt quá `max_rows`, cắt đúng `max_rows` và bật cờ `truncated = True` để báo cho B0.5.
   - Tự động ẩn các cột nội bộ bắt đầu bằng `__dm_` (như `__dm_row_id`) khỏi danh sách cột và dòng trả về khi truy vấn dùng `SELECT *`.
   - Chuẩn hóa toàn bộ giá trị trả về qua `_normalize_value()` (`bool` giữ nguyên kiểu boolean, `Decimal` số nguyên đổi sang `int`, `Decimal` thập phân đổi sang `float`, `date`/`datetime`/`time` đổi sang chuỗi ISO).

---

### 3.5. Module B0.5: Basic Output Gate, Bounded Retry & Submission Writer
- **Vị trí mã nguồn:** [`src/datamate/b0/b05/`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/)
- **Điểm vào chính:** [`evaluate_gate()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/gate.py#L20-L139) trong [`gate.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/gate.py) và [`SubmissionWriter`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/writer.py#L10-L53) trong [`writer.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/writer.py).

#### Các bước kiểm duyệt bên trong B0.5:
1. **Kiểm duyệt tính trả lời được (`answerability.py`):**
   - Nếu `evidence.source_kind == "catalog_verified"` và `capability_status == "unsupported"` và `checked_all_sources == True` → trả về quyết định cuối cùng `Decision.UNANSWERABLE` (`{"id": "...", "type": "unanswerable", "reason": "..."}`).
   - Nếu LLM trả `answer_type == "unanswerable"` nhưng không vượt qua kiểm chứng catalog → hạ xuống `Decision.ABSTAIN` (`{"id": "...", "type": "abstain"}`) để tránh bị phạt điểm đoán sai `unanswerable`.
2. **Kiểm tra Hình dạng Kết quả (`validators.py`):**
   - Nếu `execution.status == "error"` → báo lỗi thực thi để chuyển sang bộ phân loại Retry.
   - Nếu `execution.truncated == True` → từ chối kết quả bị cắt cụt (`TRUNCATED_RESULT`).
   - Với các kiểu vô hướng (`number`, `percent`, `string`, `date`, `boolean`): bắt buộc kết quả phải có **đúng 1 dòng và 1 cột** (`1x1`) và giá trị không được là `NULL` (`SCALAR_NULL`, `EMPTY_RESULT`, `SCALAR_SHAPE_MISMATCH`).
   - Với kiểu `list`: bắt buộc kết quả chỉ có **1 cột** (`LIST_MULTI_COLUMN`).
3. **Phân loại Lỗi & Quyết định Bounded Retry (`retry.py`):**
   - [`classify_error()`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py#L14-L108) phân loại cả lỗi thực thi từ B0.4 lẫn lỗi hình dạng từ B0.5:
     - **Cho phép Retry (`retryable = True` khi `attempt == 0`):** `SyntaxError` / `ParserException` / `EmptyQueryError` (`SQL_SYNTAX`), `CatalogError` / `BinderError` (`SCHEMA_ERROR`), `ConversionException` / `DataError` (`SQL_TYPE_ERROR`), và `SCALAR_SHAPE_MISMATCH`.
     - **Không Retry (`retryable = False` → `abstain` ngay):** `SecurityViolation`, `TimeoutError`, `TRUNCATED_RESULT`, `EMPTY_RESULT`, `SCALAR_NULL`.
   - Khi `attempt == 0` và `retryable == True`, `evaluate_gate()` trả về `GateOutcome(action="RETRY", repair_request=RepairRequest(...))`. `B0Pipeline` nhận tín hiệu này, gọi `generator.repair()` để LLM sửa câu SQL dựa trên thông báo lỗi của DuckDB, sau đó chạy lại B0.4 và B0.5 với `attempt = 1`. Nếu ở `attempt = 1` vẫn lỗi, cổng tự động trả `Decision.ABSTAIN` (`reason_code = "RETRY_EXHAUSTED"`).
4. **Định dạng Đáp án Chuẩn cuộc thi (`formatter.py`):**
   - `number`: Định dạng theo `NumericKind`:
     - `count` / `money_vnd` / `average_money_vnd`: Làm tròn chuẩn kế toán `ROUND_HALF_UP` thành số nguyên `int` (ví dụ: `89526400`).
     - `quantity` / `average_nonmoney` / `generic`: Làm tròn tối đa 2 chữ số thập phân, tự động bỏ `.0` nếu là số nguyên.
   - `percent`: Nếu `percent_unit == "fraction"` thì nhân `100`, làm tròn 2 chữ số thập phân (ví dụ: `2.08`).
   - `date`: Chấp nhận `datetime.date`, `datetime.datetime` hoặc chuỗi ISO timestamp và chuẩn hóa về đúng định dạng `YYYY-MM-DD`.
   - `list` & `table`: Chuẩn hóa toàn bộ phần tử con (`Decimal`, `date`, `datetime`) sang kiểu JSON thuần.

---

## 4. Minh Họa Thực Tế: Hành Trình Của Một Câu Hỏi Từ `data/train/questions.jsonl`

Xét câu hỏi thực tế trong `data/train/questions.jsonl` của doanh nghiệp **`biz_105`**:

```json
{
  "id": "q_00558c1410ef",
  "business_id": "biz_105",
  "question": "tỉ lệ huỷ đơn tháng 6/2025 là nhiêu %",
  "as_of_date": "2026-06-24"
}
```

### Bước 1 — B0.1 & B0.2 chuẩn bị Bundle cho `biz_105`:
- Gộp 17 sheets bán hàng từ `SoBanHang_1.xlsx` và `SoBanHang_2026.xlsx` thành bảng `so_ban_hang_17d6a4c9` (138.023 dòng) trong `data.duckdb`.
- Ghi nhận các cột: `ma_hoa_don (VARCHAR)`, `ngay_giao_dich (DATE)`, `status (VARCHAR)`, `tri_gia (DECIMAL(38,4))`, `so_luong (DECIMAL(38,0))`.
- Biên dịch quy tắc từ `rulebook.md`:
  > *"Tỉ lệ đơn huỷ trong kỳ: phần trăm đơn huỷ trong mọi đơn đặt trong kỳ (theo ngày đặt, mọi trạng thái: cả đơn huỷ, đơn trả, đơn đang giao). Làm tròn 2 chữ số thập phân."*

### Bước 2 — B0.3 tạo Prompt và sinh kết quả `Text2SQLResult`:
- `B0Pipeline.answer_question()` nạp `business_context.json` của `biz_105`, tạo prompt gửi cho LLM và nhận về `Text2SQLResult`:
  ```json
  {
    "status": "answerable",
    "answer_type": "percent",
    "sql": "SELECT COUNT(DISTINCT CASE WHEN LOWER(status) LIKE '%huỷ%' OR LOWER(status) LIKE '%huy%' THEN ma_hoa_don END) * 100.0 / NULLIF(COUNT(DISTINCT ma_hoa_don), 0) FROM so_ban_hang_17d6a4c9 WHERE ngay_giao_dich >= DATE '2025-06-01' AND ngay_giao_dich <= DATE '2025-06-30'",
    "answer_semantics": {
      "percent_unit": "percent_points"
    }
  }
  ```

### Bước 3 — B0.4 kiểm duyệt AST & thực thi trên `data.duckdb`:
- `sanitize_and_validate_sql()` xác nhận câu lệnh là `exp.Select` hợp lệ, không chứa từ khóa cấm.
- `execute_query()` chạy câu lệnh trên `bundle_dir/data.duckdb` của `biz_105` và trả về:
  - `is_valid = True`, `route = "yes"`, `row_count = 1`, `truncated = False`
  - `rows = [{"col_0": 2.0833333333333335}]`

### Bước 4 — B0.5 kiểm tra hình dạng & định dạng đáp án:
- `validate_execution()` xác nhận kết quả là bảng `1x1` khác `NULL`.
- `format_percent()` nhận giá trị `2.0833333333333335` với `percent_unit = "percent_points"`, làm tròn `ROUND_HALF_UP` đến 2 chữ số thập phân → **`2.08`**.
- `SubmissionWriter` ghi dòng kết quả vào `submission.jsonl` (khớp 100% với đáp án chuẩn trong `data/train/answers.jsonl`):
  ```json
  {"id": "q_00558c1410ef", "type": "percent", "answer": 2.08}
  ```

---

## 5. Hướng Dẫn Sử Dụng `B0Pipeline` Trong Code

```python
import json
from pathlib import Path
from datamate.b0 import B0Pipeline
from datamate.b0.b03 import Text2SQLGenerator, VLLMModel, load_config

# 1. Chuẩn bị bundle B0.1 + B0.2 cho các doanh nghiệp trong data/train
train_root = Path("data/train")
bundles_root = Path("artifacts/bundles/train")
bundles = {}

for biz_dir in sorted((train_root / "data").iterdir()):
    if biz_dir.is_dir():
        artifacts = B0Pipeline.prepare_bundle(
            business_dir=biz_dir,
            output_dir=bundles_root,
            rulebook=train_root / "rulebook.md",
            calendar=train_root / "calendar.csv",
        )
        bundles[biz_dir.name] = artifacts.bundle_dir

# 2. Khởi tạo mô hình LLM (B0.3) và B0Pipeline
model_cfg, gen_opts = load_config("configs/b03_qwen.toml")
llm = VLLMModel(model_cfg)
llm.load()

pipeline = B0Pipeline(
    generator=Text2SQLGenerator(llm),
    timeout_sec=10.0,
    max_rows=10000,
    options=gen_opts,
)

# 3. Đọc danh sách câu hỏi và chạy End-to-End B0.3 -> B0.4 -> B0.5
questions = [
    json.loads(line)
    for line in (train_root / "questions.jsonl").read_text(encoding="utf-8").splitlines()
    if line.strip()
]

outcomes = pipeline.run_questions(
    questions=questions,
    bundles=bundles,
    output_dir=Path("artifacts/submissions/train"),
)
```

---

## 6. Bảng Tham Chiếu Nhanh Các Tệp Mã Nguồn Trong B0

| Tầng | File mã nguồn | Vai trò chính |
| :--- | :--- | :--- |
| **Orchestrator** | [`src/datamate/b0/pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/pipeline.py) | Điều phối End-to-End `B0Pipeline` (chuẩn bị bundle, chạy câu hỏi, điều phối 1 lần Bounded Retry, ghi kết quả). |
| **B0.1 Ingestion** | [`src/datamate/b0/b01/ingestion/readers.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py) | Đọc streaming `.csv`, `.xlsx`, `.sqlite`, phát hiện dòng tiêu đề và gom nhóm `logical_family`. |
| **B0.1 Ingestion** | [`src/datamate/b0/b01/ingestion/normalization.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/normalization.py) | Chuẩn hóa kiểu dữ liệu (số, tiền VND, ngày giờ Việt Nam), lọc dòng tổng cộng. |
| **B0.1 Ingestion** | [`src/datamate/b0/b01/ingestion/preparation.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py) | Đóng gói nguyên tử bundle (`data.duckdb`, `business_context.json`, `source_manifest.json`). |
| **B0.1 Catalog** | [`src/datamate/b0/b01/schema_catalog.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py) | Suy luận khóa chính (`key_candidates`) và đồ thị nối bảng (`join_graph`) kiểm chứng trên toàn bảng DuckDB. |
| **B0.2 Context** | [`src/datamate/b0/b02/rule_compiler.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/rule_compiler.py) | Biên dịch quy tắc từ `README.md` và `rulebook.md`, liên kết tên cột gốc tiếng Việt vào `linked_fields`. |
| **B0.2 Context** | [`src/datamate/b0/b02/context_service.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/context_service.py) | Hợp nhất `SchemaCatalog` (B0.1) và `RuleCatalog` (B0.2) thành `BusinessContextContract`. |
| **B0.3 LLM** | [`src/datamate/b0/b03/prompt.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py) | Kết xuất prompt tiếng Việt gồm Schema, gợi ý JOIN, khoảng thời gian dữ liệu và Rule đã lọc theo `precedence`. |
| **B0.3 LLM** | [`src/datamate/b0/b03/parser.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py) | Phân tích JSON/SQL từ LLM, xóa `<think>`, chuẩn hóa `answer_type`, trích bảng bằng `sqlglot`. |
| **B0.3 LLM** | [`src/datamate/b0/b03/evidence.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/evidence.py) | Kiểm chứng `missing_fields` với `schema_catalog` để tạo `EvidenceProof` cho câu hỏi `unanswerable`. |
| **B0.4 Executor** | [`src/datamate/b0/b04/sanitizer.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/sanitizer.py) | Kiểm duyệt AST chỉ đọc (`ALLOWED_ROOT_NODES`), chặn từ khóa phá hoại và multi-statement. |
| **B0.4 Executor** | [`src/datamate/b0/b04/engine.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py) | Thực thi SQL Read-Only trên DuckDB với timeout watchdog, ẩn cột `__dm_row_id` và phát hiện `truncated`. |
| **B0.5 Gate** | [`src/datamate/b0/b05/gate.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/gate.py) | Cổng quyết định trung tâm (`FINAL` vs `RETRY`), điều phối xác thực `unanswerable`, kiểm tra shape và định dạng đáp án. |
| **B0.5 Gate** | [`src/datamate/b0/b05/formatter.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py) | Định dạng chuẩn xác 7 kiểu dữ liệu trả lời (`number`, `percent`, `string`, `date`, `boolean`, `list`, `table`). |

