# Báo Cáo Review Toàn Diện Source Code DataMate B0 (B0.1 – B0.5)

> **Người thực hiện:** Senior Staff Code Reviewer & QA Architect (10+ năm kinh nghiệm)  
> **Phạm vi kiểm toán:** Toàn bộ mã nguồn `src/datamate/b0/` (`b01`, `b01/ingestion`, `b02`, `b03`, `b04`, `b05`), `scripts/`, và `tests/`  
> **Trạng thái bộ test hiện tại:** `164 passed, 3 skipped` (Tuy nhiên có nhiều lỗi logic ngầm và đứt gãy hợp đồng dữ liệu liên tầng chưa được unit test bao phủ)  
> **Phương pháp đánh giá:** Multi-Axis Code Review (Correctness, Architecture & Data Contracts, Security, Performance, Readability & Testability)

---

## 1. Tổng Quan Kiến Trúc & Bản Đồ Phân Bố Lỗi (Markdown/ASCII Diagram)

Sơ đồ dưới đây mô tả luồng dữ liệu toàn cục của pipeline **Baseline B0 (Direct Text-to-SQL)** từ lúc nạp dữ liệu thô (B0.1 Ingestion) đến cổng kiểm duyệt đầu ra (B0.5 Output Gate), cùng các vị trí xuất hiện lỗi nghiêm trọng (`[CRITICAL]` và `[REQUIRED]`):

```text
+---------------------------------------------------------------------------------------------------+
|                                  PIPELINE BASELINE B0 - DATAMATE                                  |
+---------------------------------------------------------------------------------------------------+

  [ Raw Files: CSV / XLSX / SQLite + README.md + rulebook.md ]
         |
         |  (BUG-03: parse_date thiếu format "%Y-%m-%d %H:%M", "%d-%m-%Y %H:%M")
         |  (BUG-04: CSVReader/XLSXReader nuốt dòng dữ liệu trùng tên header không ghi log)
         |  (BUG-05: XLSXReader mở lại toàn bộ file .xlsx nhiều lần gây nghẽn I/O)
         v
+---------------------------------------------------------------------------------------------------+
| B0.1: INGESTION & SCHEMA/JOIN CATALOG (src/datamate/b0/b01/)                                      |
|  - preparation.py -> data.duckdb + foundation_metadata.json                                       |
|  - schema_catalog.py -> SchemaCatalog (tables, key_candidates, join_graph)                        |
|                                                                                                   |
|  * [CRITICAL] BUG-01: schema_catalog.py:223 xóa sạch `evidence=()` trước khi gọi                  |
|                       DuckDBProfileProvider.check_join(), làm đoạn code kiểm chứng FK             |
|                       ở profiling.py:108-134 trở thành DEAD CODE 100%!                            |
|  * [REQUIRED] BUG-02: schema_catalog.py:133 lọc join dựa trên 5 dòng sample trước khi             |
|                       chạy SQL profile toàn bảng, làm mất các cạnh join hợp lệ!                   |
+---------------------------------------------------------------------------------------------------+
         |
         |  (BUG-06: rule_compiler.py:59 gán nhầm scope="business" cho mọi file tên readme.md)
         |  (BUG-07: _linked_fields chỉ dò tên cột ASCII đã chuẩn hóa, bỏ sót tên tiếng Việt gốc)
         v
+---------------------------------------------------------------------------------------------------+
| B0.2: CONTEXT & BUSINESS RULES (src/datamate/b0/b02/)                                             |
|  - context_service.py / contracts.py -> BusinessContext (business_context.json)                   |
+---------------------------------------------------------------------------------------------------+
         |
         |  =====================================================================================
         |  [ĐỨT GÃY HỢP ĐỒNG LIÊN TẦNG B0.2 ---> B0.3]
         |  * [CRITICAL] BUG-08: prompt.py:75,80 đọc sai key `join_edges` (thực tế là `join_graph`)
         |                       và `primary_key_candidates` (thực tế nằm ở `key_candidates`).
         |                       -> LLM mất 100% thông tin Join Graph, Khóa chính và Original Name!
         |  =====================================================================================
         v
+---------------------------------------------------------------------------------------------------+
| B0.3: TEXT-TO-SQL LLM LAYER (src/datamate/b0/b03/)                                                |
|  - prompt.py / parser.py / generator.py -> Text2SQLResult                                         |
|                                                                                                   |
|  * [REQUIRED] BUG-11: extract_tables_from_sql() dùng regex bắt nhầm `EXTRACT(YEAR FROM col)`      |
|                       thành tên bảng `col` và bắt nhầm tên bảng tạm CTE!                          |
|  * [REQUIRED] BUG-12: clean_markdown_block() bắt nhầm code block bên trong thẻ `<think>...</think>`|
|                       của mô hình Qwen3.5-9B thay vì JSON kết quả cuối cùng!                      |
+---------------------------------------------------------------------------------------------------+
         |
         |  =====================================================================================
         |  [ĐỨT GÃY HỢP ĐỒNG LIÊN TẦNG B0.3 ---> B0.5]
         |  * [CRITICAL] BUG-09: Text2SQLResult.to_b05_generation_result() gán mặc định             |
         |                       `answer_type="generic"` -> B0.5 bác bỏ với lỗi CONTRACT_ERROR!     |
         |  * [CRITICAL] BUG-10: B0.3 không truyền `AnswerSemantics` (money_vnd, count, fraction)   |
         |                       và `EvidenceProof` sang B0.5 -> Sai làm tròn tiền VND & mất điểm   |
         |                       câu hỏi `unanswerable`!                                            |
         |  =====================================================================================
         v
+---------------------------------------------------------------------------------------------------+
| B0.4: DUCKDB READ-ONLY EXECUTION ENGINE (src/datamate/b0/b04/)                                    |
|  - sanitizer.py / engine.py / error_handler.py / schemas.py -> ExecutionResponse                  |
|                                                                                                   |
|  * [CRITICAL] BUG-15: sanitizer.py chặn nhầm câu SELECT hợp lệ có chứa từ khóa trong chuỗi        |
|                       literal (vd: `WHERE note LIKE '%update%'`), bỏ quên `ALLOWED_ROOT_NODES`,   |
|                       và cho phép lách luật multi-statement khi `sqlglot` báo `ParseError`!       |
|  * [CRITICAL] BUG-14: normalize_value() ép kiểu `Decimal` sang `float` gây sai số dấu phẩy động   |
|                       và crash `InvalidOperation` khi gặp `Decimal('NaN')` / `Decimal('Inf')`!    |
|  * [REQUIRED] BUG-16: _load_directory_into_duckdb() đè mất dữ liệu khi trùng tên file stem        |
|                       và chỉ nạp sheet đầu tiên của file `.xlsx`!                                 |
|  * [REQUIRED] BUG-17: execute_query() không phát hiện kết quả bị cắt ngọn (`truncated=True`).     |
|  * [REQUIRED] BUG-18: B0.4 và B0.5 mâu thuẫn nhau về quyền retry đối với `TimeoutError`           |
|                       và `SecurityViolation`.                                                     |
+---------------------------------------------------------------------------------------------------+
         |
         |  =====================================================================================
         |  [ĐỨT GÃY HỢP ĐỒNG LIÊN TẦNG B0.4 ---> B0.5]
         |  * [CRITICAL] BUG-13: B0.4 `normalize_value()` biến `datetime.datetime` thành chuỗi      |
         |                       `"YYYY-MM-DDTHH:MM:SS"`, nhưng B0.5 `format_date()` chỉ chấp nhận  |
         |                       chuỗi `"YYYY-MM-DD"` hoặc `"YYYY-MM"` -> Mọi câu hỏi kiểu `date`   |
         |                       truy vấn cột `TIMESTAMP` hoặc `DATE_TRUNC` đều bị lỗi và ABSTAIN!  |
         |  =====================================================================================
         v
+---------------------------------------------------------------------------------------------------+
| B0.5: BASIC OUTPUT GATE (src/datamate/b0/b05/)                                                    |
|  - validators.py / formatter.py / gate.py / writer.py -> submission.jsonl                         |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Đánh Giá Theo 5 Trục Chất Lượng (5-Axis Quality Matrix)

| Trục đánh giá (Axis) | Điểm hiện tại | Nhận định tổng quan từ Chuyên gia Review & QA |
| :--- | :---: | :--- |
| **1. Correctness (Tính đúng đắn)** | **5.5 / 10** | Từng module đơn lẻ vượt qua unit test nội bộ, nhưng khi ghép nối toàn tuyến xuất hiện **6 lỗi `[CRITICAL]`** làm hỏng kết quả (mất Join Graph trong prompt, lỗi định dạng ngày `TIMESTAMP` -> `DATE`, lỗi `answer_type="generic"`, mất chứng cứ khóa ngoại SQLite). |
| **2. Architecture & Contracts (Kiến trúc & Hợp đồng dữ liệu)** | **6.0 / 10** | Kiến trúc phân tầng B0.1 -> B0.5 rất rõ ràng, nhưng thiếu **End-to-End Integration Test** kiểm tra hợp đồng giao tiếp giữa B0.1/B0.2 <-> B0.3 <-> B0.4 <-> B0.5 dẫn đến lệch tên trường (`join_graph` vs `join_edges`, `key_candidates` vs `primary_key_candidates`). |
| **3. Security (Bảo mật & An toàn thực thi)** | **6.5 / 10** | B0.4 có cơ chế giới hạn tài nguyên DuckDB và kiểm tra AST bằng `sqlglot`, nhưng regex tiền kiểm tra (`FORBIDDEN_KEYWORDS`) quá thô gây lỗi giả (false positive), quên kiểm tra `ALLOWED_ROOT_NODES`, và mở lỗ hổng bypass khi `sqlglot.parse` gặp `ParseError`. |
| **4. Performance (Hiệu năng & Tài nguyên)** | **7.5 / 10** | B0.1 Ingestion dùng CSV spooling và streaming khá tốt, tuy nhiên `XLSXReader.discover` mở lại file `.xlsx` nhiều lần không cần thiết và `DuckDBMetadataProvider` chạy $O(N \times M)$ câu truy vấn SQL riêng lẻ cho từng cột. |
| **5. Readability & Testability (Khả năng bảo trì & Kiểm thử)** | **8.0 / 10** | Codebase sạch sẽ, tuân thủ typing Python 3.12+, tách biệt tốt giữa I/O và logic thuần. Tuy nhiên bộ test hiện tại dùng mock/fixture tự tạo ở từng tầng nên chưa phát hiện được lỗi lệch schema giữa các tầng. |

---

## 3. Thống Kê Danh Sách Lỗi Theo Mức Độ Nghiêm Trọng

| Mã lỗi | Mức độ | Module | Tệp và Dòng | Tóm tắt lỗi |
| :--- | :---: | :---: | :--- | :--- |
| **BUG-01** | `[CRITICAL]` | B0.1 | [`schema_catalog.py:222-227`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L222-L227) | Xóa trắng `evidence=()` trước khi gọi `check_join()`, biến toàn bộ logic xác thực FK trong [`profiling.py:108-134`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/profiling.py#L108-L134) thành dead code. |
| **BUG-08** | `[CRITICAL]` | B0.2 / B0.3 | [`prompt.py:75-89`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py#L75-L89) | Đọc sai tên trường `join_edges` (đúng là `join_graph`) và `primary_key_candidates` (đúng là `key_candidates`), bỏ sót `original_name` và `data_profiling`. |
| **BUG-09** | `[CRITICAL]` | B0.3 / B0.5 | [`types.py:137`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L137), [`parser.py:106`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L106) | Gán mặc định `answer_type="generic"` (vốn là `NumericKind`, không phải `AnswerType`), khiến B0.5 báo lỗi `CONTRACT_ERROR` và `ABSTAIN`. |
| **BUG-10** | `[CRITICAL]` | B0.3 / B0.5 | [`types.py:123-142`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L123-L142), [`gate.py:43-53`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/gate.py#L43-L53) | Thiếu truyền đạt `AnswerSemantics` (`numeric_kind`, `percent_unit`) và `EvidenceProof`, làm sai quy tắc làm tròn tiền VND và biến mọi câu `unanswerable` của LLM thành `abstain`. |
| **BUG-13** | `[CRITICAL]` | B0.4 / B0.5 | [`schemas.py:152-153`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py#L152-L153), [`formatter.py:106-127`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py#L106-L127) | B0.4 chuẩn hóa `datetime.datetime` thành `"YYYY-MM-DDTHH:MM:SS"`, nhưng B0.5 `format_date()` từ chối chuỗi có hậu tố thời gian `T...`, gây lỗi hàng loạt cho câu hỏi kiểu `date`. |
| **BUG-14** | `[CRITICAL]` | B0.4 | [`schemas.py:140-159`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py#L140-L159) | `normalize_value()` crash với `Decimal('NaN')`/`Decimal('Infinity')`, mất độ chính xác khi ép `Decimal` sang `float`, và bỏ sót kiểu `datetime.time`. |
| **BUG-15** | `[CRITICAL]` | B0.4 | [`sanitizer.py:59-64,108-146`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/sanitizer.py#L59-L146) | Chặn nhầm câu `SELECT` có từ khóa trong string literal/comment, không kiểm tra `ALLOWED_ROOT_NODES`, và cho phép multi-statement lọt qua khi `sqlglot` báo `ParseError`. |
| **BUG-02** | `[REQUIRED]` | B0.1 | [`schema_catalog.py:124-146`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L124-L146) | Tự động dò join bị phụ thuộc vào 5 dòng `profile_rows` mẫu, dẫn đến bỏ sót cạnh join khi 5 dòng đầu không giao nhau. |
| **BUG-03** | `[REQUIRED]` | B0.1 | [`normalization.py:234-255`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/normalization.py#L234-L255) | `parse_date()` thiếu định dạng `"%Y-%m-%d %H:%M"` và `"%d-%m-%Y %H:%M"`, gây lỗi `parse_failure` (mất dữ liệu ngày giờ) với các chuỗi giờ 1 chữ số hoặc không có giây. |
| **BUG-04** | `[REQUIRED]` | B0.1 | [`readers.py:240-241,386-387`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L240-L241) | Bỏ qua dòng dữ liệu trùng với `source.headers` mà không ghi nhận vào `excluded_non_data_rows` hay `meta.quality_issues`. |
| **BUG-06** | `[REQUIRED]` | B0.2 | [`rule_compiler.py:59-62`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/rule_compiler.py#L59-L62) | Mọi tài liệu có tên `readme.md` đều bị gán `scope="business"` (precedence 300) kể cả khi không thuộc thư mục doanh nghiệp, đè lên luật ngành (`industry`, precedence 200). |
| **BUG-07** | `[REQUIRED]` | B0.2 | [`rule_compiler.py:255-265`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/rule_compiler.py#L255-L265) | `_linked_fields()` chỉ đối chiếu `column.name` (đã bỏ dấu), không đối chiếu `column.original_name` (tiếng Việt có dấu), làm rỗng `required_fields`. |
| **BUG-11** | `[REQUIRED]` | B0.3 | [`parser.py:13-25`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L13-L25) | `extract_tables_from_sql()` dùng regex `\b(?:FROM|JOIN)` bắt nhầm tên cột trong `EXTRACT(YEAR FROM col)` và bắt nhầm tên CTE. |
| **BUG-12** | `[REQUIRED]` | B0.3 | [`parser.py:42-74`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L42-L74) | `clean_markdown_block()` và regex JSON không loại bỏ thẻ `<think>...</think>` của Qwen3.5, dễ bắt nhầm nháp SQL/JSON trong phần suy luận. |
| **BUG-16** | `[REQUIRED]` | B0.4 | [`engine.py:26-66`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L26-L66) | `_load_directory_into_duckdb()` trùng tên bảng khi 2 file cùng tên gốc (`stem`) và chỉ đọc sheet đầu tiên của file `.xlsx`. |
| **BUG-17** | `[REQUIRED]` | B0.4 | [`engine.py:130`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L130), [`schemas.py:67-108`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py#L67-L108) | `cursor.fetchmany(request.max_rows)` không kiểm tra xem còn dòng thứ `max_rows + 1` hay không để bật cờ `truncated=True` cho B0.5. |
| **BUG-18** | `[REQUIRED]` | B0.4 / B0.5 | [`error_handler.py:8-33`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/error_handler.py#L8-L33), [`retry.py:20-58`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py#L20-L58) | Xung đột chính sách retry: B0.4 đánh dấu `SecurityViolation` và `TimeoutError` là `recoverable`, nhưng B0.5 đánh dấu `retryable=False`. |
| **BUG-05** | `[OPTIONAL]` | B0.1 | [`readers.py:255-285`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L255-L285), [`preparation.py:243`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py#L243) | Mở đi mở lại cùng một file `.xlsx` tới 3 lần trong quá trình `discover()`. |
| **BUG-19** | `[OPTIONAL]` | B0.5 | [`formatter.py:148-198`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py#L148-L198) | `format_list()` và `format_table()` chưa chuẩn hóa số `Decimal` hoặc chuỗi ngày/giờ bên trong phần tử mảng/bảng đồng nhất với kiểu scalar. |
| **BUG-20** | `[NIT]` | B0.3 | [`parser.py:37`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L37) | `sql.split("FROM")[0]` phân biệt chữ hoa/thường (`"from"` viết thường không tách được chuỗi). |

---

## 4. Phân Tích Chi Tiết Từng Lỗi, Minh Chứng & Hướng Giải Quyết

### 4.1. Nhóm Lỗi Mức Độ `[CRITICAL]` (Bắt buộc sửa ngay vì gây sai kết quả hoặc sập luồng)

---

#### [BUG-01] `[CRITICAL]` Xóa trắng `evidence=()` trước khi kiểm chứng Join làm vô hiệu hóa toàn bộ nhánh xác thực Foreign Key
- **Vị trí:**
  - [`src/datamate/b0/b01/schema_catalog.py#L222-L227`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L222-L227)
  - [`src/datamate/b0/b01/ingestion/profiling.py#L94-L134`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/profiling.py#L94-L134)
- **Minh chứng trong code:**
  Tại [`schema_catalog.py:222-227`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L222-L227):
  ```python
  if self.profile_provider is not None:
      edges = [
          self.profile_provider.check_join(replace(e, evidence=()))
          if e.status != "invalid"
          else e
          for e in edges
      ]
  ```
  Và tại [`profiling.py:94-108`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/profiling.py#L94-L108):
  ```python
  evidence = edge.evidence + (
      f"exact SQL tuple coverage: left={overlap}/{ldistinct}, right={overlap}/{rdistinct}; observed={observed}",
  )
  if not ldistinct or not rdistinct:
      return replace(edge, status="uncertain", confidence=0.2, evidence=evidence)
  if not edge.evidence:
      return replace(
          edge,
          status="uncertain",
          confidence=0.75,
          evidence=evidence,
          cardinality=observed,
          fanout_warning=observed != "one_to_one",
      )
  # Toàn bộ dòng 108-134 bên dưới kiểm tra valid_shapes và trả về status="validated", confidence=0.95
  ```
- **Giải thích lý do sai & Hệ quả:**
  - Trong `SchemaCatalogBuilder.build()`, các cạnh join được khai báo tường minh (ví dụ khóa ngoại SQLite từ `_relationships()` trong `preparation.py:716` có `evidence=("SQLite foreign_key_list: ...",)`) đã được xử lý ở dòng 148–220.
  - Tuy nhiên, ở dòng 223, `replace(e, evidence=())` **xóa sạch `e.evidence` về tuple rỗng `()`** trước khi truyền vào `self.profile_provider.check_join(...)`.
  - Bên trong `DuckDBProfileProvider.check_join()`, lệnh `if not edge.evidence:` (dòng 99) kiểm tra `edge.evidence` đầu vào (vốn vừa bị xóa thành `()`). Do đó, điều kiện `if not edge.evidence:` **luôn luôn đúng (100% True)**!
  - **Hệ quả:** Toàn bộ dòng 108–134 của `profiling.py` trở thành **Dead Code** không bao giờ chạy tới khi gọi qua `SchemaCatalogBuilder`. Mọi khóa ngoại SQLite hợp lệ đều bị mất nguồn gốc (`SQLite foreign_key_list`) và bị ép về `status="uncertain", confidence=0.75` thay vì `status="validated", confidence=0.95`. Khi `JoinGraphNavigator.find_safe_path()` chạy với `allow_uncertain=False` (mặc định), nó sẽ **không tìm thấy đường join nào** dù database có khai báo Foreign Key đầy đủ!
- **Hướng giải quyết:**
  Trong [`schema_catalog.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py), chỉ giữ lại các chứng cứ gốc từ nguồn khai báo (không giữ chứng cứ sample tạm thời) thay vì xóa trắng `evidence=()` đối với các cạnh có trong `relationships` ban đầu:
  ```python
  # Giữ nguyên evidence gốc của relationship đã khai báo (ví dụ SQLite FK),
  # chỉ xóa sample evidence tạm thời nếu cạnh được sinh tự động từ sample:
  declared_ evidence_map = { ... } # hoặc truyền trực tiếp original_evidence
  ```
  Cụ thể: trước khi bước sample check gắn thêm `"validated against complete table profiles..."` hoặc `"complete table profiles are unavailable..."` ở dòng 159/212, nếu `self.profile_provider is not None`, không cần gắn thông báo sample giả tạm thời vào `e.evidence`, để truyền nguyên vẹn `e` (cùng `e.evidence` gốc từ `relationships`) vào `self.profile_provider.check_join(e)`.

---

#### [BUG-08] `[CRITICAL]` Đứt gãy hợp đồng B0.1/B0.2 -> B0.3: `format_context_for_prompt` đọc sai tên trường làm mất 100% Join Graph, Khóa chính và Tên cột gốc
- **Vị trí:**
  - [`src/datamate/b0/b03/prompt.py#L60-L89`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py#L60-L89)
  - Đối chiếu với [`src/datamate/b0/b01/contracts.py#L19-L80`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/contracts.py#L19-L80)
- **Minh chứng trong code:**
  Tại [`src/datamate/b0/b03/prompt.py#L75-L89`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py#L75-L89):
  ```python
  pks = tbl.get("primary_key_candidates", [])
  pk_str = f" [Khóa chính: {', '.join(pks)}]" if pks else ""
  sections.append(f"Bảng: `{tbl_name}`{grain_str}{pk_str}\n" + "\n".join(cols_info))

  # 2. Join Relationships
  join_edges = schema_catalog.get("join_edges", [])
  if join_edges:
      sections.append("\n### QUAN HỆ JOIN (RELATIONSHIPS):")
  ```
  Trong khi đó, [`SchemaCatalog`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/contracts.py#L73-L80) định nghĩa:
  ```python
  @dataclass(frozen=True)
  class SchemaCatalog:
      tables: tuple[TableMetadata, ...]
      key_candidates: tuple[KeyCandidate, ...]
      join_graph: tuple[JoinEdge, ...]
      warnings: tuple[str, ...] = ()
  ```
- **Giải thích lý do sai & Hệ quả:**
  1. `SchemaCatalog` lưu danh sách quan hệ join dưới khóa **`"join_graph"`**, không phải `"join_edges"`. Do đó `schema_catalog.get("join_edges", [])` luôn trả về `[]` khi nhận `BusinessContext` thật từ B0.2! Ngoài ra, `JoinEdge` hỗ trợ khóa phức hợp (`additional_key_pairs`), nhưng `prompt.py` chỉ đọc `left_column` và `right_column`.
  2. `TableMetadata` không có trường `"primary_key_candidates"`. Các ứng viên khóa chính nằm ở `schema_catalog["key_candidates"]` dưới dạng danh sách các dict `{"table": ..., "columns": [...], "status": ...}`. Thậm chí nếu `primary_key_candidates` có chứa dict thì `', '.join(pks)` sẽ nổ lỗi `TypeError`.
  3. Trong quá trình Ingestion (`preparation.py`), tên cột tiếng Việt có dấu (ví dụ `"Thành tiền"`, `"Mã hóa đơn"`) đã bị đổi thành tên cột SQL (`thanh_tien`, `ma_hoa_don`) và lưu tên gốc vào `col["original_name"]`. Hàm `format_context_for_prompt` hoàn toàn không in `original_name`, cũng không in thông tin `data_profiling` (khoảng ngày `observed_min`..`observed_max`, mẫu dữ liệu `samples`), khiến LLM phải "đoán mò" ý nghĩa cột và giá trị thực tế trong bảng!
- **Hướng giải quyết:**
  Cập nhật [`format_context_for_prompt`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py#L49-L108) để:
  - Đọc cả `schema_catalog.get("join_graph") or schema_catalog.get("join_edges", [])` (tương thích ngược với cả test mock cũ và contract B0.1 thật), đồng thời hiển thị đầy đủ các cặp khóa trong `additional_key_pairs`.
  - Trích xuất khóa chính từ `schema_catalog.get("key_candidates", [])` lọc theo `table == tbl_name` và `status in ("validated", "candidate")` (vẫn hỗ trợ fallback `tbl.get("primary_key_candidates", [])`).
  - Hiển thị `original_name` (nếu khác `name`) và `description` cho từng cột: `- {col_name} ({c_type}, {nullable}) [Tên gốc: "{original_name}"]`.
  - Bổ sung mục tóm tắt `data_profiling` (min/max của cột ngày tháng và tối đa 3 dòng sample) để LLM viết bộ lọc `WHERE` chính xác.

---

#### [BUG-09] `[CRITICAL]` Đứt gãy hợp đồng B0.3 -> B0.5: Giá trị mặc định `answer_type="generic"` bị B0.5 bác bỏ với lỗi `CONTRACT_ERROR`
- **Vị trí:**
  - [`src/datamate/b0/b03/types.py#L136-L142`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L136-L142)
  - [`src/datamate/b0/b03/parser.py#L100-L107`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L100-L107)
  - Đối chiếu với [`src/datamate/b0/b05/contracts.py#L8-L27`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/contracts.py#L8-L27) và [`src/datamate/b0/b05/validators.py#L228-L234`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/validators.py#L228-L234)
- **Minh chứng trong code:**
  Tại [`src/datamate/b0/b03/types.py#L136-L142`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L136-L142):
  ```python
  return B05GenerationResult(
      answer_type=self.answer_type or "generic",
      sql=self.sql or "",
      ...
  )
  ```
  Trong khi tại [`src/datamate/b0/b05/contracts.py#L8-L17`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/contracts.py#L8-L17):
  ```python
  class AnswerType(str, Enum):
      NUMBER = "number"
      PERCENT = "percent"
      STRING = "string"
      DATE = "date"
      BOOLEAN = "boolean"
      LIST = "list"
      TABLE = "table"
      UNANSWERABLE = "unanswerable"
      ABSTAIN = "abstain"
  ```
- **Giải thích lý do sai & Hệ quả:**
  - `"generic"` là một giá trị của `NumericKind` (`NumericKind.GENERIC`), **không phải** là một `AnswerType` hợp lệ của B0.5!
  - Khi `answer_type` bị thiếu hoặc LLM trả về một chuỗi không chuẩn, B0.3 gán `"generic"`. Khi chuyển sang B0.5, `validate_execution()` rơi vào nhánh `else:` (dòng 228): `Unsupported answer_type: generic` và trả về `ErrorCode.CONTRACT_ERROR`. Vì `CONTRACT_ERROR` có `retryable=False`, câu hỏi bị ép về **`ABSTAIN`** ngay lập tức mà không được phép retry!
- **Hướng giải quyết:**
  - Chuẩn hóa `answer_type` trong `parser.py` và `Text2SQLResult.to_b05_generation_result()`: chỉ chấp nhận tập hợp hợp lệ `{"number", "percent", "string", "date", "boolean", "list", "table", "unanswerable", "abstain"}`.
  - Nếu LLM trả về bí danh như `"integer"`, `"float"`, `"decimal"`, `"money"`, `"count"` -> ánh xạ về `"number"` (đồng thời lưu `"count"` / `"money_vnd"` vào `numeric_kind`). Nếu vẫn không xác định được thì dùng `infer_answer_type_from_sql(self.sql or "")` (mặc định là `"table"` hoặc `"number"`).

---

#### [BUG-10] `[CRITICAL]` Đứt gãy ngữ nghĩa B0.3 -> B0.5: Thiếu `AnswerSemantics` (`numeric_kind`, `percent_unit`) và `EvidenceProof`
- **Vị trí:**
  - [`src/datamate/b0/b03/types.py#L101-L142`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L101-L142)
  - [`src/datamate/b0/b05/formatter.py#L45-L94`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py#L45-L94)
  - [`src/datamate/b0/b05/gate.py#L24-L53`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/gate.py#L24-L53)
- **Minh chứng trong code:**
  Tại [`src/datamate/b0/b03/types.py#L136-L142`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L136-L142):
  ```python
  return B05GenerationResult(
      answer_type=self.answer_type or "generic",
      sql=self.sql or "",
      tables_used=list(self.tables_used),
      assumptions=list(self.assumptions),
      answer_semantics=AnswerSemantics(),  # <-- Luôn luôn rỗng!
  )
  ```
- **Giải thích lý do sai & Hệ quả:**
  1. **Sai lệch làm tròn số học (Numeric Rounding):** Trong B0.5 `formatter.py:55-57`, tiền tệ Việt Nam (`NumericKind.MONEY_VND` và `AVERAGE_MONEY_VND`) bắt buộc phải làm tròn đến hàng đơn vị đồng (`Decimal("1")`, trả về `int`), còn `COUNT` bắt buộc phải là số nguyên. Khi `AnswerSemantics()` luôn rỗng (`numeric_kind=None`), một câu hỏi tính trung bình doanh thu đơn hàng trả về `125000.67` sẽ rơi vào nhánh `generic` và trả về số thực `125000.67` thay vì số nguyên `125001`, dẫn đến **sai đáp án chấm thi (0 điểm)**!
  2. **Mất toàn bộ điểm câu hỏi `unanswerable`:** Trong `gate.py:43-53`, nếu `generation.answer_type == "unanswerable"` nhưng `request.evidence` không có `source_kind == "catalog_verified"`, cổng B0.5 sẽ hạ cấp câu trả lời từ `unanswerable` xuống `abstain`! Hiện tại `Text2SQLResult` không có hàm hỗ trợ đối chiếu `reason` / `missing_fields` với `BusinessContext.answerability_constraints` hoặc `SchemaCatalog` để sinh `EvidenceProof`.
- **Hướng giải quyết:**
  - Bổ sung trường tùy chọn `answer_semantics: dict[str, Any]` (hoặc suy luận tự động `numeric_kind` từ câu hỏi/SQL: nếu có `COUNT` -> `"count"`, nếu hỏi tiền/doanh thu/chi phí/lãi gộp/giá -> `"money_vnd"`) vào `Text2SQLResult` và truyền sang `B05GenerationResult`.

---

#### [BUG-13] `[CRITICAL]` Đứt gãy hợp đồng B0.4 -> B0.5: `normalize_value()` biến `datetime.datetime` thành chuỗi ISO có chữ `T`, bị `format_date()` của B0.5 từ chối
- **Vị trí:**
  - [`src/datamate/b0/b04/schemas.py#L152-L153`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py#L152-L153)
  - [`src/datamate/b0/b05/formatter.py#L106-L127`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py#L106-L127)
- **Minh chứng trong code:**
  Tại B0.4 [`src/datamate/b0/b04/schemas.py#L152-L153`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py#L152-L153):
  ```python
  if isinstance(val, (datetime.datetime, datetime.date)):
      return val.isoformat()
  ```
  Tại B0.5 [`src/datamate/b0/b05/formatter.py#L106-L127`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py#L106-L127):
  ```python
  def format_date(value: Any, semantics: Dict[str, Any]) -> str:
      """Format date to ISO YYYY-MM-DD or YYYY-MM."""
      if isinstance(value, (datetime.date, datetime.datetime)):
          return value.isoformat()[:10]

      s = str(value).strip()
      # Check YYYY-MM-DD
      if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
          ...
      # Check YYYY-MM
      if re.match(r"^\d{4}-\d{2}$", s):
          ...
      raise FormattingError(f"Invalid date format '{s}', expected ISO YYYY-MM-DD or YYYY-MM", code=ErrorCode.OUTPUT_TYPE_ERROR)
  ```
- **Giải thích lý do sai & Hệ quả:**
  - Trong DuckDB, rất nhiều cột thời gian có kiểu `TIMESTAMP` (do B0.1 `ColumnParser.sql_type()` nâng cấp lên `TIMESTAMP` khi có cả giờ phút) hoặc các hàm như `DATE_TRUNC('day', col)` trong DuckDB trả về kiểu `TIMESTAMP` (`datetime.datetime(2026, 3, 15, 0, 0)`).
  - Khi đi qua B0.4 `execute_query()`, hàm `normalize_value()` chuyển `datetime.datetime(2026, 3, 15, 0, 0)` thành chuỗi `"2026-03-15T00:00:00"`.
  - Khi kết quả này đi vào B0.5 `format_date()`, `value` đã là kiểu `str` (`"2026-03-15T00:00:00"`), nên nhánh `if isinstance(value, (datetime.date, datetime.datetime)):` ở dòng 108 bị bỏ qua! Tiếp theo, regex `^\d{4}-\d{2}-\d{2}$` ở dòng 113 không khớp vì có `"T00:00:00"` ở cuối!
  - **Hệ quả:** `format_date()` ném lỗi `FormattingError: Invalid date format '2026-03-15T00:00:00'`, khiến câu truy vấn hoàn toàn đúng bị đánh trượt sang RETRY rồi ABSTAIN!
- **Hướng giải quyết:**
  Trong [`src/datamate/b0/b05/formatter.py#L106-L127`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py#L106-L127), hỗ trợ parse chuỗi ISO datetime hợp lệ (ví dụ `"2026-03-15T00:00:00"` hoặc `"2026-03-15 00:00:00"`) bằng `datetime.datetime.fromisoformat(s).date().isoformat()` trước khi báo lỗi.

---

#### [BUG-14] `[CRITICAL]` Lỗi mất độ chính xác `Decimal`, crash `InvalidOperation` trên `Decimal('NaN')`, và bỏ sót `datetime.time` trong B0.4 `normalize_value()`
- **Vị trí:** [`src/datamate/b0/b04/schemas.py#L140-L159`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py#L140-L159)
- **Minh chứng trong code:**
  ```python
  if isinstance(val, (float, int)):
      if math.isnan(val) or math.isinf(val):
          return None
      return val
  ...
  if isinstance(val, (datetime.datetime, datetime.date)):
      return val.isoformat()

  if isinstance(val, decimal.Decimal):
      if val % 1 == 0:
          return int(val)
      return float(val)
  ```
- **Giải thích lý do sai & Hệ quả:**
  1. **Crash `decimal.InvalidOperation`:** Nếu một phép tính `DECIMAL` trả về `Decimal('NaN')` hoặc `Decimal('Infinity')`, phép chia lấy dư `val % 1` sẽ ném ngoại lệ `decimal.InvalidOperation` không được bắt, làm hỏng toàn bộ `execute_query()` thay vì trả về `None` như nhánh `float`.
  2. **Sai số dấu phẩy động nhị phân (`float`):** Việc ép `Decimal` có phần thập phân sang `float` ở B0.4 có thể tạo ra sai số biểu diễn nhị phân trước khi B0.5 kịp dùng `Decimal.quantize(..., ROUND_HALF_UP)`.
  3. **Bỏ sót `datetime.time`:** Các cột kiểu `TIME` trong DuckDB trả về đối tượng `datetime.time`. Vì dòng 152 chỉ kiểm tra `(datetime.datetime, datetime.date)`, đối tượng `datetime.time` bị giữ nguyên dạng object Python, gây lỗi khi `json.dumps` ở các bước sau.
  4. **Thứ tự kiểm tra `bool`:** Trong Python, `bool` là lớp con của `int` (`isinstance(True, int) == True`), nên `bool` đi vào nhánh `isinstance(val, (float, int))` ở dòng 140. Cần tách riêng `if isinstance(val, bool): return val` lên trước để rõ ràng và an toàn tuyệt đối.
- **Hướng giải quyết:**
  ```python
  if isinstance(val, bool):
      return val
  if isinstance(val, (float, int)):
      if math.isnan(val) or math.isinf(val):
          return None
      return val
  if isinstance(val, (datetime.datetime, datetime.date, datetime.time)):
      return val.isoformat()
  if isinstance(val, decimal.Decimal):
      if not val.is_finite():
          return None
      if val == val.to_integral_value():
          return int(val)
      return float(val)
  ```

---

#### [BUG-15] `[CRITICAL]` Lỗi bảo mật & False-Positive trong B0.4 `validate_read_only_sql`: Chặn nhầm câu `SELECT` có từ khóa trong chuỗi literal, bỏ quên `ALLOWED_ROOT_NODES`, và lách luật qua `ParseError`
- **Vị trí:** [`src/datamate/b0/b04/sanitizer.py#L44-L147`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/sanitizer.py#L44-L147)
- **Minh chứng trong code:**
  ```python
  ALLOWED_ROOT_NODES = (
      exp.Select,
      exp.Union,
      exp.Intersect,
      exp.Except,
  )
  ...
  # Fast-path check for explicit destructive keywords
  for word in FORBIDDEN_KEYWORDS:
      if re.search(rf"\b{word}\b", fast_check):
          raise SecurityViolation(f"Forbidden SQL operation '{word}' detected.")

  try:
      parsed_statements = sqlglot.parse(cleaned_sql, read="duckdb")
  except ParseError:
      # If sqlglot cannot parse, let DuckDB's native parser generate precise line/column hints
      return cleaned_sql
  ```
- **Giải thích lý do sai & Hệ quả:**
  1. **False Positive trên câu truy vấn hợp lệ:** Vòng lặp `FORBIDDEN_KEYWORDS` (`"update"`, `"delete"`, `"create"`, `"copy"`, `"load"`, `"drop"`, ...) quét regex trực tiếp trên chuỗi `fast_check` chưa loại bỏ string literal và comment! Nếu câu hỏi yêu cầu lọc `WHERE ghi_chu LIKE '%update%'`, `WHERE trang_thai = 'delete'`, hoặc LLM viết comment `-- do not drop null rows`, hàm sẽ ném lỗi `SecurityViolation` oan!
  2. **Quên kiểm tra `ALLOWED_ROOT_NODES`:** Hằng số `ALLOWED_ROOT_NODES` được khai báo ở dòng 59 nhưng **không hề được sử dụng** ở bất kỳ đâu trong hàm `validate_read_only_sql`! Do đó các câu lệnh không phải `SELECT` như `SHOW TABLES`, `DESCRIBE`, `EXPLAIN`, `SUMMARIZE`, `TRUNCATE TABLE` (vốn không nằm trong `FORBIDDEN_KEYWORDS` và `FORBIDDEN_AST_NODES`), `EXPORT DATABASE`, `CALL`, `RESET` đều vượt qua bộ lọc!
  3. **Bypass Multi-Statement khi `ParseError`:** Khi `sqlglot.parse` gặp lỗi `ParseError`, hàm trả thẳng `cleaned_sql` về cho `con.execute(cleaned_sql)`. Vì `extract_clean_sql` chỉ xóa dấu `;` ở cuối chuỗi (`;+\s*$`), một chuỗi chứa nhiều câu lệnh cách nhau bởi dấu `;` kèm cú pháp đặc thù khiến `sqlglot` báo `ParseError` sẽ được DuckDB thực thi toàn bộ!
- **Hướng giải quyết:**
  - Xóa bỏ string literals (`'...'`) và comments (`--...`, `/*...*/`) khỏi bản sao chuỗi trước khi chạy `fast_check` tìm từ khóa cấm và kiểm tra dấu `;` ở nhánh fallback `ParseError`.
  - Bổ sung kiểm tra `if not isinstance(stmt, ALLOWED_ROOT_NODES): raise SecurityViolation(...)` sau dòng 133.
  - Bổ sung `exp.TruncateTable`, `exp.Export`, `exp.LoadData`, `exp.Use` vào `FORBIDDEN_AST_NODES` và `"truncate"`, `"export"`, `"call"`, `"execute"` vào `FORBIDDEN_KEYWORDS`.

---

### 4.2. Nhóm Lỗi Mức Độ `[REQUIRED]` (Cần sửa để đảm bảo độ chính xác và tính toàn vẹn dữ liệu)

---

#### [BUG-02] `[REQUIRED]` Tự động khám phá cạnh Join trong `SchemaCatalogBuilder` bị chặn sớm bởi 5 dòng mẫu (`profile_rows`)
- **Vị trí:** [`src/datamate/b0/b01/schema_catalog.py#L124-L146`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L124-L146)
- **Minh chứng trong code:**
  ```python
  left_values = value_profiles[(left.name, left_col.name)]
  right_values = value_profiles[(right.name, right_col.name)]
  overlap = len(left_values & right_values)
  if not overlap:
      continue
  ```
- **Giải thích lý do sai & Hệ quả:**
  - Khi dùng `DuckDBMetadataProvider` (`profiling.py:204`), `table.profile_rows` chỉ lấy đúng 5 dòng đầu tiên (`LIMIT 5`).
  - Nếu 5 dòng đầu tiên của bảng `don_hang` và 5 dòng đầu tiên của bảng `khach_hang` không tình cờ trùng mã `ma_khach` nào, `overlap` trên tập mẫu 5 dòng sẽ bằng `0` và vòng lặp `continue` bỏ qua luôn cặp cột đó **trước khi** `DuckDBProfileProvider.check_join()` có cơ hội kiểm tra giao thoa (INTERSECT) trên toàn bộ bảng trong DuckDB!
- **Hướng giải quyết:**
  Khi `self.profile_provider is not None`, nếu hai bảng có cột trùng tên thuộc nhóm khóa (`_is_join_column_name`), vẫn tạo cạnh ứng viên để `self.profile_provider.check_join()` kiểm tra bằng SQL `INTERSECT` trên toàn bảng; chỉ loại bỏ những cạnh mà sau khi chạy `check_join` có `overlap == 0` (tức `status in {"invalid", "uncertain"}` với `left=0/`).

---

#### [BUG-03] `[REQUIRED]` `parse_date` thiếu định dạng ngày giờ không có giây (`%Y-%m-%d %H:%M`, `%d-%m-%Y %H:%M`) và lỗi khi giờ có 1 chữ số
- **Vị trí:** [`src/datamate/b0/b01/ingestion/normalization.py#L234-L255`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/normalization.py#L234-L255)
- **Minh chứng trong code:**
  ```python
  for fmt in (
      "%d/%m/%Y %H:%M:%S",
      "%d/%m/%Y %H:%M",
      "%d-%m-%Y %H:%M:%S",
      "%Y-%m-%d %H:%M:%S",
  ):
  ```
- **Giải thích lý do sai & Hệ quả:**
  - Trong dữ liệu Excel/CSV xuất từ phần mềm bán hàng tại Việt Nam, định dạng `"15-03-2026 9:30"` hoặc `"2026-03-15 9:30"` (giờ có 1 chữ số, không có giây) rất phổ biến.
  - `datetime.fromisoformat("2026-03-15 9:30")` trong Python 3.12 ném `ValueError` vì giờ chỉ có 1 chữ số (`9` thay vì `09`). Sau đó vòng lặp `strptime` ở dòng 246 lại thiếu `"%Y-%m-%d %H:%M"` và `"%d-%m-%Y %H:%M"`, khiến giá trị ngày giờ hợp lệ bị biến thành `NULL` (`parse_failure`)!
- **Hướng giải quyết:**
  Bổ sung `"%d-%m-%Y %H:%M"`, `"%Y-%m-%d %H:%M"`, `"%Y/%m/%d %H:%M:%S"`, `"%Y/%m/%d %H:%M"`, `"%Y/%m/%d"` vào danh sách `strptime` trong `parse_date()`.

---

#### [BUG-04] `[REQUIRED]` `CSVReader.rows` và `XLSXReader.rows` âm thầm bỏ qua dòng trùng header mà không đối soát trong audit report
- **Vị trí:** [`src/datamate/b0/b01/ingestion/readers.py#L240-L241`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L240-L241) và [`#L386-L387`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L386-L387)
- **Giải thích lý do sai & Hệ quả:**
  Khi gặp dòng có `_headers(tuple(row)) == source.headers`, reader gọi `continue` bỏ qua dòng đó trước khi `yield SourceRow`. Với bảng 1 cột hoặc bảng có tên cột chung chung, nếu dữ liệu trùng tên cột thì dòng dữ liệu bị mất âm thầm mà không hề được ghi vào `meta.quality_issues`. Hơn nữa, nếu `_headers` tự điền `column_1` cho ô trống ở cuối, việc so sánh `_headers(tuple(row))` thay vì so sánh các ô thực sự có chữ sẽ thiếu chặt chẽ.
- **Hướng giải quyết:**
  Chỉ bỏ qua dòng lặp header khi bảng có ít nhất 2 cột có tên tường minh (không phải `column_N` tự sinh) và mọi giá trị trên dòng khớp chính xác với header gốc.

---

#### [BUG-06] `[REQUIRED]` `BusinessRuleCompiler.ingest_documents` gán nhầm `scope="business"` cho mọi file tên `readme.md`
- **Vị trí:** [`src/datamate/b0/b02/rule_compiler.py#L59-L62`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/rule_compiler.py#L59-L62)
- **Minh chứng trong code:**
  ```python
  is_business_document = path.name.casefold() == "readme.md" or (
      business_id is not None and business_id in path.parts
  )
  default_scope = "business" if is_business_document else "split_default"
  ```
- **Giải thích lý do sai & Hệ quả:**
  Nếu người dùng truyền một file `README.md` cấp toàn tập dữ liệu (split-level) nhưng không nằm trong thư mục `biz_XX`, biểu thức `path.name.casefold() == "readme.md"` vẫn bằng `True`, làm toàn bộ quy tắc trong file đó được nâng lên `scope="business"` (precedence = 300), đè bẹp cả quy tắc theo ngành (`industry`, precedence = 200)!
- **Hướng giải quyết:**
  Nếu `business_id` được cung cấp và đường dẫn file chứa cấu trúc thư mục phân tách nhưng không chứa `business_id`, cần kiểm tra kỹ phạm vi hoặc chỉ coi `readme.md` là `business` khi không phải tài liệu dùng chung cấp root.

---

#### [BUG-07] `[REQUIRED]` `_linked_fields` trong `rule_compiler.py` không nhận diện được tên cột tiếng Việt có dấu (`original_name`)
- **Vị trí:** [`src/datamate/b0/b02/rule_compiler.py#L255-L265`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/rule_compiler.py#L255-L265)
- **Minh chứng trong code:**
  ```python
  def _linked_fields(text: str, schema: SchemaCatalog | None) -> list[str]:
      if schema is None:
          return []
      lowered = text.casefold()
      found: list[str] = []
      for table in schema.tables:
          for column in table.columns:
              pattern = rf"(?<![\w]){re.escape(column.name.casefold())}(?![\w])"
              if re.search(pattern, lowered):
                  found.append(column.name)
      return found
  ```
- **Giải thích lý do sai & Hệ quả:**
  Trong `SchemaCatalog`, `column.name` là tên cột ASCII không dấu (`thanh_tien`, `ngay_ban`), còn `column.original_name` mới là `"Thành tiền"`, `"Ngày bán"`. Văn bản trong `README.md` và `rulebook.md` viết bằng tiếng Việt có dấu, nên regex tìm `thanh_tien` trong `"Tổng thành tiền..."` luôn thất bại, làm `BusinessRule.required_fields` bị rỗng!
- **Hướng giải quyết:**
  Kiểm tra cả `column.name.casefold()` và `column.original_name.casefold()` (nếu `column.original_name` tồn tại và dài từ 2 ký tự trở lên), khi khớp thì thêm `column.name` vào danh sách `found`.

---

#### [BUG-11] `[REQUIRED]` `extract_tables_from_sql` bắt nhầm tên cột trong hàm `EXTRACT(... FROM col)` và tên bảng tạm CTE
- **Vị trí:** [`src/datamate/b0/b03/parser.py#L13-L25`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L13-L25)
- **Minh chứng trong code:**
  ```python
  def extract_tables_from_sql(sql: str) -> tuple[str, ...]:
      if not sql:
          return ()
      pattern = r"\b(?:FROM|JOIN)\s+([\"`]?[\w\.]+[\"`]?)"
      matches = re.findall(pattern, sql, re.IGNORECASE)
  ```
- **Giải thích lý do sai & Hệ quả:**
  - Trong DuckDB SQL, cú pháp chuẩn để lấy năm/tháng là `EXTRACT(YEAR FROM order_date)` hoặc `TRIM(BOTH ' ' FROM customer_name)`. Từ khóa `FROM` xuất hiện ngay trước tên cột `order_date`! Regex trên sẽ trích xuất nhầm cột `order_date` thành tên bảng trong `tables_used`.
  - Ngoài ra, nếu câu SQL dùng `WITH monthly_sales AS (SELECT * FROM orders) SELECT * FROM monthly_sales`, regex sẽ đưa cả tên CTE `monthly_sales` vào `tables_used`.
- **Hướng giải quyết:**
  Sử dụng `sqlglot` (đã có sẵn trong `pyproject.toml`) để duyệt AST (`stmt.find_all(exp.Table)`), loại trừ tên các bảng tạm định nghĩa trong `stmt.find_all(exp.CTE)`, và chỉ dùng regex (đã loại trừ `EXTRACT\s*\([^)]*?FROM`) làm fallback khi câu SQL bị lỗi cú pháp chưa parse được.

---

#### [BUG-12] `[REQUIRED]` `clean_markdown_block` và `parse_text2sql_response` bị nhiễu bởi thẻ `<think>...</think>` của Qwen3.5
- **Vị trí:** [`src/datamate/b0/b03/parser.py#L42-L74`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L42-L74)
- **Minh chứng trong code:**
  ```python
  def clean_markdown_block(text: str) -> str:
      text = text.strip()
      match = re.search(r"```(?:json|sql)?\s*([\s\S]*?)\s*```", text, re.IGNORECASE)
      if match:
          return match.group(1).strip()
      return text
  ```
- **Giải thích lý do sai & Hệ quả:**
  Mô hình mặc định của dự án là `Qwen/Qwen3.5-9B` (xem `scripts/download_model.py`). Khi sinh văn bản có suy luận (`<think>...</think>`), mô hình thường viết nháp các đoạn ```` ```sql ... ``` ```` bên trong khối `<think>` trước khi xuất khối ```` ```json { ... } ``` ```` cuối cùng ở ngoài `</think>`. Vì `re.search` luôn lấy kết quả khớp **đầu tiên**, `clean_markdown_block` sẽ bóc nhầm đoạn code nháp trong `<think>` thay vì JSON kết quả cuối cùng!
- **Hướng giải quyết:**
  Trước khi bóc tách markdown/JSON trong `parse_text2sql_response` (và `extract_clean_sql` của B0.4), loại bỏ toàn bộ phần `<think>[\s\S]*?</think>` (nếu có), đồng thời ưu tiên khối ` ```json ` hoặc khối code cuối cùng.

---

#### [BUG-16] `[REQUIRED]` `_load_directory_into_duckdb` đè mất bảng khi trùng file stem và chỉ đọc sheet đầu tiên của `.xlsx`
- **Vị trí:** [`src/datamate/b0/b04/engine.py#L26-L66`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L26-L66)
- **Giải thích lý do sai & Hệ quả:**
  1. `os.walk(dir_path)` không sắp xếp thứ tự thư mục/file (không tất định trên Linux).
  2. Nếu có 2 file cùng tên gốc ở 2 thư mục con (hoặc `orders.csv` và `orders.parquet`), lệnh `CREATE TABLE "orders"` lần thứ 2 sẽ ném lỗi `CatalogException` và bị nuốt vào `logger.warning`, gây mất dữ liệu âm thầm.
  3. Với file `.xlsx`, `pd.read_excel(file_path)` mặc định chỉ đọc sheet đầu tiên (`sheet_name=0`), bỏ rơi toàn bộ các sheet còn lại trong workbook.
- **Hướng giải quyết:**
  Sắp xếp `os.walk` tất định, kiểm tra nếu `data.duckdb` đã tồn tại trong thư mục bundle thì kết nối trực tiếp tới `data.duckdb` (`read_only=True`) thay vì nạp lại từng file lẻ; nếu nạp file lẻ thì xử lý hậu tố chống trùng tên bảng và đọc tất cả các sheet của `.xlsx` (`sheet_name=None`).

---

#### [BUG-17] `[REQUIRED]` `execute_query` không phát hiện tình trạng cắt ngọn kết quả (`truncated=True`)
- **Vị trí:** [`src/datamate/b0/b04/engine.py#L128-L160`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L128-L160) và [`src/datamate/b0/b04/schemas.py#L67-L108`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py#L67-L108)
- **Giải thích lý do sai & Hệ quả:**
  `cursor.fetchmany(request.max_rows)` chỉ lấy đúng `max_rows` dòng. Nếu kết quả thực tế có `max_rows + 1` dòng, B0.4 vẫn báo `row_count = max_rows` và `to_b05_execution_result()` luôn gán `truncated=False` (mặc định). Do đó, luật kiểm tra `if execution.truncated:` trong B0.5 (`validators.py:34`) không bao giờ được kích hoạt!
- **Hướng giải quyết:**
  Trong `engine.py`, gọi `cursor.fetchmany(request.max_rows + 1)`. Nếu `len(raw_rows) > request.max_rows`, cắt `raw_rows = raw_rows[:request.max_rows]` và đặt `truncated = True` trên `ExecutionResponse`, sau đó truyền `truncated=self.truncated` sang `ExecutionResult` của B0.5.

---

#### [BUG-18] `[REQUIRED]` Mâu thuẫn chính sách Retry giữa B0.4 (`error_handler.py`) và B0.5 (`retry.py`)
- **Vị trí:**
  - [`src/datamate/b0/b04/error_handler.py#L8-L33`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/error_handler.py#L8-L33)
  - [`src/datamate/b0/b05/retry.py#L20-L58`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py#L20-L58)
- **Giải thích lý do sai & Hệ quả:**
  - B0.4 coi `SecurityViolation` và `TimeoutError` là `is_recoverable = True` (`route = "recoverable"`).
  - Ngược lại, B0.5 `retry.py` coi `SECURITY_VIOLATION` và `QUERY_TIMEOUT` là `retryable = False` (dừng ngay và trả về `ABSTAIN`).
  - Sự bất nhất này khiến luồng điều phối bị rối loạn tùy thuộc vào việc caller hỏi `b04_res.route` hay hỏi `b05_outcome.action`. Theo đúng đặc tả B0.5 Gate (§5, §11), `SECURITY_VIOLATION` và `QUERY_TIMEOUT` là lỗi dừng (non-retryable) để bảo vệ ngân sách thời gian (time budget) và an toàn hệ thống; hoặc nếu cho phép retry cần thống nhất một nguồn chân lý duy nhất.

---

### 4.3. Nhóm Lỗi Mức Độ `[OPTIONAL]` & `[NIT]` (Tối ưu hóa hiệu năng và làm sạch mã nguồn)

#### [BUG-05] `[OPTIONAL]` `XLSXReader.discover` và `prepare_business` mở lại cùng một file `.xlsx` tới 3 lần
- **Vị trí:** [`src/datamate/b0/b01/ingestion/readers.py#L255-L285`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L255-L285), [`src/datamate/b0/b01/ingestion/preparation.py#L243`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py#L243)
- **Hướng giải quyết:** Lazy-load `original` workbook (`data_only=False`) tối đa 1 lần cho toàn bộ file `.xlsx` trong `XLSXReader.discover` thay vì mở mới trong mỗi vòng lặp sheet, và tái sử dụng thông tin sheet đã quét thay vì mở lại workbook ở `preparation.py:243`.

#### [BUG-19] `[OPTIONAL]` `format_list` và `format_table` trong B0.5 chưa chuẩn hóa kiểu `Decimal` bên trong phần tử
- **Vị trí:** [`src/datamate/b0/b05/formatter.py#L148-L198`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py#L148-L198)
- **Hướng giải quyết:** Nếu caller truyền trực tiếp `Decimal` hoặc `datetime.date` vào `format_list` / `format_table` (không qua B0.4), `json.dumps` ở `SubmissionWriter` sẽ báo lỗi `Object of type Decimal is not JSON serializable`. Cần chuẩn hóa các phần tử con (`Decimal`, `date`, `datetime`) trong `format_list` và `format_table`.

#### [BUG-20] `[NIT]` `infer_answer_type_from_sql` tách chuỗi `"FROM"` phân biệt hoa thường
- **Vị trí:** [`src/datamate/b0/b03/parser.py#L37`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py#L37)
- **Hướng giải quyết:** Thay `sql.split("FROM")[0]` bằng `re.split(r"\bFROM\b", sql, maxsplit=1, flags=re.IGNORECASE)[0]`.

---

## 5. Kết Luận Của Chuyên Gia Review & QA

1. **Điểm mạnh của dự án:** Cấu trúc thư mục hiện tại (`src/datamate/b0/b01` .. `b05`) đã được chuẩn hóa rất sạch sẽ, tách biệt rõ ràng trách nhiệm của từng tầng, và có hệ thống kiểm soát chất lượng dữ liệu (Data Lineage, Quality Issues, Answerability Proof) rất bài bản.
2. **Điểm nghẽn chí mạng cần xử lý ngay:** Các lỗi nặng nhất (**BUG-01, BUG-08, BUG-09, BUG-10, BUG-13, BUG-14, BUG-15**) đều nằm ở **điểm giao cắt hợp đồng dữ liệu (Interface Boundary)** giữa các thành viên phát triển độc lập từng module B0.1–B0.5.
3. **Kế hoạch hành động:** Toàn bộ lộ trình khắc phục theo từng bước nhỏ (Atomic Vertical Slices), kèm tiêu chí nghiệm thu và lệnh kiểm thử đã được lập chi tiết tại tài liệu kế hoạch: [`docs/plan/B0_REMEDIATION_PLAN.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/plan/B0_REMEDIATION_PLAN.md).

