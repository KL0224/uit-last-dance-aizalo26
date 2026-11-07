# Báo Cáo Kiểm Toán Mã Nguồn & Phân Tích Xung Đột Toàn Tuyến End-to-End (B0.1 → B0.5)

> **Người thực hiện:** Senior Staff Code Reviewer & QA Architect (10+ năm kinh nghiệm)  
> **Phạm vi kiểm toán:** Toàn bộ mã nguồn từ `B0.1` (Ingestion & Schema Catalog) → `B0.2` (Business Context & Rules) → `B0.3` (LLM Prompt, Parser & Generator) → `B0.4` (DuckDB Read-Only Executor) → `B0.5` (Basic Output Gate & Submission Writer)  
> **Mục tiêu trọng tâm:** Đảm bảo thông luồng hoạt động **End-to-End (B0.1 → B0.5)** không bị đứt gãy hợp đồng dữ liệu, không xung đột trạng thái điều phối, và không làm sai lệch kết quả chấm thi trên dữ liệu thực tế.

---

## 1. Sơ Đồ Luồng Hoạt Động End-to-End & Các Điểm Xung Đột Liên Tầng (Markdown ASCII Diagram)

Sơ đồ dưới đây mô tả chi tiết đường đi của dữ liệu và câu hỏi qua toàn bộ 5 tầng của kiến trúc **DataMate Baseline B0**, chỉ rõ **8 điểm xung đột/lỗi End-to-End (`E2E-01` → `E2E-08`)** còn tồn tại khi ghép nối các module của các thành viên khác nhau thành một hệ thống hoàn chỉnh:

```text
+===================================================================================================+
|                     LUỒNG HOẠT ĐỘNG END-TO-END: B0.1 -> B0.2 -> B0.3 -> B0.4 -> B0.5              |
+===================================================================================================+

  [ Dữ liệu thô: .csv / .xlsx / .sqlite ] + [ Tài liệu: rulebook.md / README.md / calendar.csv ]
         |
         |  * [E2E-08] readers.py:240,270,386: Bỏ qua dòng trùng header chưa kiểm tra bảng 1 cột /
         |             tên cột tự sinh `column_1`; XLSXReader mở lại workbook nhiều lần.
         v
+---------------------------------------------------------------------------------------------------+
| TẦNG B0.1: INGESTION & SCHEMA CATALOG (src/datamate/b0/b01/)                                      |
|  1. prepare_business() tạo `data.duckdb` (chứa bảng chuẩn hóa + cột ẩn `__dm_row_id` BIGINT)      |
|  2. DuckDBMetadataProvider nạp metadata (chỉ lấy LIMIT 5 dòng vào `profile_rows`)                 |
|  3. SchemaCatalogBuilder + DuckDBProfileProvider kiểm tra khóa chính & cạnh Join                  |
|                                                                                                   |
|  * [E2E-05] XUNG ĐỘT B0.1 Metadata <-> B0.1 Catalog (schema_catalog.py:133-148):                  |
|             Cạnh join tự động bị lọc bỏ nếu 5 dòng đầu (`profile_rows`) có coverage < 0.8,        |
|             khiến `DuckDBProfileProvider.check_join()` không bao giờ được gọi trên toàn bảng!     |
+---------------------------------------------------------------------------------------------------+
         |
         v
+---------------------------------------------------------------------------------------------------+
| TẦNG B0.2: BUSINESS CONTEXT & RULE COMPILER (src/datamate/b0/b02/)                                |
|  1. BusinessRuleCompiler nạp toàn bộ dòng từ `rulebook.md` (mọi ngành) và `README.md`             |
|  2. ContractBuilder đóng gói `BusinessContext` (`business_context.json`)                          |
|                                                                                                   |
|  * [E2E-06] XUNG ĐỘT B0.2 RuleResolver <-> B0.3 Prompt (prompt.py:106-115):                       |
|             B0.2 có `RuleResolver` để lọc theo ngành (`industry`) và độ ưu tiên (`precedence`),   |
|             nhưng B0.3 lại đổ toàn bộ `rule_catalog.rules` thô (gồm cả quy tắc ngành khác và      |
|             quy tắc mặc định đã bị ghi đè) vào prompt khiến LLM bị nhiễu!                         |
+---------------------------------------------------------------------------------------------------+
         |
         |  * [E2E-01] THIẾU BỘ ĐIỀU PHỐI TRUNG TÂM (`B0Pipeline` / Orchestrator):
         |             Chưa có module nối tự động từ `BusinessContext` + `question` -> B0.3 -> B0.4
         |             -> B0.5 (kèm vòng lặp Bounded Retry gọi ngược lại `Text2SQLGenerator.repair`).
         v
+---------------------------------------------------------------------------------------------------+
| TẦNG B0.3: TEXT-TO-SQL LLM LAYER (src/datamate/b0/b03/)                                           |
|  1. build_text2sql_messages() -> VLLMModel.chat() -> parse_text2sql_response() -> Text2SQLResult  |
|                                                                                                   |
|  * [E2E-04] XUNG ĐỘT NGỮ NGHĨA B0.3 <-> B0.5 Formatter (types.py:134-158 & formatter.py:45-93):   |
|             Khi LLM không sinh `answer_semantics`, B0.3 mới chỉ đoán được `count`, chưa suy luận  |
|             được `money_vnd` / `average_money_vnd` (làm tròn đồng VND) và `fraction` (nhân 100    |
|             cho kiểu `percent`), dẫn đến sai kết quả làm tròn ở B0.5!                             |
+---------------------------------------------------------------------------------------------------+
         |
         +---------------------------------------------------+
         | Nhánh A: status == "unanswerable"                 | Nhánh B: status == "answerable"
         | (sql = None, reason = "...")                      | (sql = "SELECT ...")
         v                                                   v
+---------------------------------------------+   +-------------------------------------------------+
| * [E2E-02] XUNG ĐỘT LUỒNG UNANSWERABLE:     |   | TẦNG B0.4: DUCKDB EXECUTOR (src/datamate/b0/b04)|
| 1. Nếu đẩy qua `ExecutionRequest.from_b03`, |   |  Thực thi `cleaned_sql` trên `data.duckdb`      |
|    `sql=""` gây lỗi `EmptyQueryError` ở B0.4|   |                                                 |
| 2. Khi sang B0.5 `gate.py:25-53`, vì thiếu  |   |  * [E2E-07] RÒ RỈ CỘT NỘI BỘ `__dm_row_id`:     |
|    `EvidenceProof(source_kind=              |   |    Mọi bảng trong `data.duckdb` của B0.1 đều có |
|    "catalog_verified")`, B0.5 ép TẤT CẢ     |   |    cột ẩn `__dm_row_id`. Khi SQL dùng `SELECT *`|
|    câu trả lời `unanswerable` thành         |   |    cho câu hỏi kiểu `table`, B0.4 trả về luôn   |
|    `ABSTAIN` và xóa mất `reason`!           |   |    cột `__dm_row_id` làm sai cấu trúc bảng nộp! |
+---------------------------------------------+   +-------------------------------------------------+
         \                                                   /
          \                                                 /
           \     * [E2E-03] XUNG ĐỘT PHÂN LOẠI LỖI RETRY GIỮA B0.4 VÀ B0.5 (retry.py:20-65):
            \      - B0.4 trả `error_type="CatalogError"` (sai tên bảng/hàm: "Table ... does not exist")
             \       nhưng B0.5 `retry.py:28` chỉ tìm chữ "binder"/"not found"/"unknown table"/"column",
              \      bỏ sót "catalog" và "does not exist" -> B0.5 đánh thành `EXECUTOR_FAILURE`
               \     (`retryable=False`) và huỷ bỏ quyền Retry!
                \  - B0.4 trả `DataError` và `EmptyQueryError` là `recoverable`, nhưng B0.5 đánh
                 \   `retryable=False`.
                  v
+---------------------------------------------------------------------------------------------------+
| TẦNG B0.5: BASIC OUTPUT GATE & SUBMISSION WRITER (src/datamate/b0/b05/)                           |
|  1. evaluate_gate() -> GateOutcome (action = FINAL hoặc RETRY)                                    |
|  2. Nếu action == RETRY (attempt 0): Phản hồi `RepairRequest` ngược lên B0.3 `repair()`           |
|  3. Nếu action == FINAL: SubmissionWriter ghi `submission.jsonl` + `logs/<question_id>.json`      |
+---------------------------------------------------------------------------------------------------+
```

---

## 2. Tổng Hợp Toàn Bộ Danh Sách Lỗi & Xung Đột Từ B0.1 Đến B0.5

Để bạn có cái nhìn toàn cảnh và xuyên suốt, bảng dưới đây thống kê **toàn bộ các lỗi trong mã nguồn** chia làm 2 phần:
- **Phần A (8 Lỗi & Xung đột End-to-End cần xử lý để thông luồng B0.1 → B0.5):** Các xung đột phát sinh khi kết nối thực tế từ B0.1 qua B0.2, B0.3, B0.4 tới B0.5.
- **Phần B (Các lỗi nội bộ từng module đã được sửa và kiểm chứng ở vòng trước):** Đã có test bảo vệ trong `tests/test_remediation_b0.py`.

### Phần A: Danh sách 8 Lỗi & Xung đột End-to-End (Đang mở — Cần sửa theo Plan)

| Mã lỗi | Mức độ | Điểm giao cắt | Tệp và Dòng | Tóm tắt xung đột / lỗi |
| :--- | :---: | :---: | :--- | :--- |
| **E2E-01** | `[CRITICAL]` | B0.1→B0.5 | Thiếu `src/datamate/b0/pipeline.py` & [`b05/cli.py:79-121`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/cli.py#L79-L121) | Chưa có bộ điều phối (End-to-End Orchestrator) nối B0.1/B0.2 → B0.3 → B0.4 → B0.5 và chạy vòng lặp Bounded Retry thật với `Text2SQLGenerator.repair()`. |
| **E2E-02** | `[CRITICAL]` | B0.2↔B0.3↔B0.5 | [`types.py:125-136`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L125-L136), [`gate.py:25-53`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/gate.py#L25-L53), [`answerability.py:8-39`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/answerability.py#L8-L39) | Câu hỏi `unanswerable` từ B0.3 nếu đưa vào B0.4 sẽ gây `EmptyQueryError`, còn đưa vào B0.5 sẽ bị hạ xuống `ABSTAIN` 100% vì thiếu bộ tạo `EvidenceProof` (`catalog_verified`) từ `BusinessContext`. |
| **E2E-03** | `[CRITICAL]` | B0.4↔B0.5 | [`error_handler.py:20-65`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/error_handler.py#L20-L65) vs [`retry.py:20-65`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py#L20-L65) | B0.4 xuất `CatalogError` (`"Table ... does not exist"`), `DataError`, `EmptyQueryError` là `recoverable`, nhưng B0.5 `retry.py` không nhận diện được từ khóa `"catalog"` / `"does not exist"` / `"dataerror"` nên đánh thành `EXECUTOR_FAILURE` (`retryable=False`), làm mất quyền Retry! |
| **E2E-07** | `[CRITICAL]` | B0.1↔B0.4↔B0.5 | [`preparation.py:619`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py#L619) vs [`engine.py:129-147`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L129-L147) | B0.1 thêm cột ẩn `__dm_row_id` vào mọi bảng trong `data.duckdb`. Khi câu SQL dùng `SELECT *` (cho `answer_type="table"`), B0.4 trả về luôn cột `__dm_row_id` làm thừa cột trong `submission.jsonl`! |
| **E2E-04** | `[REQUIRED]` | B0.3↔B0.5 | [`types.py:131-158`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L131-L158), [`formatter.py:45-93`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py#L45-L93) | Chưa tự động suy luận `numeric_kind` (`money_vnd` / `average_money_vnd`) từ câu hỏi/cột tiền tệ và `percent_unit` (`fraction` khi giá trị trả về là tỉ lệ thập phân), dễ gây sai làm tròn VND hoặc sai đơn vị phần trăm. |
| **E2E-05** | `[REQUIRED]` | B0.1 Ingestion↔Catalog | [`schema_catalog.py:124-148`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L124-L148), [`profiling.py:65-135`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/profiling.py#L65-L135) | Khám phá cạnh Join tự động cho CSV/XLSX bị chặn bởi 5 dòng mẫu (`profile_rows`) trước khi `DuckDBProfileProvider.check_join()` được phép kiểm tra bằng SQL trên toàn bảng. |
| **E2E-06** | `[REQUIRED]` | B0.2↔B0.3 | [`rule_resolver.py:30-90`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/rule_resolver.py#L30-L90) vs [`prompt.py:106-115`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py#L106-L115) | `format_context_for_prompt` nạp toàn bộ `rule_catalog.rules` thô (bao gồm cả quy tắc của các ngành khác và quy tắc mặc định đã bị ghi đè) mà chưa lọc qua `RuleResolver`. |
| **E2E-08** | `[OPTIONAL]` | B0.1 Ingestion | [`readers.py:240-241,270-285,386-387`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L240-L285) | Lọc dòng lặp header chưa bảo vệ trường hợp bảng 1 cột hoặc tên cột tự sinh `column_N`; `XLSXReader.discover` mở lại workbook nhiều lần. |

---

### Phần B: Tóm tắt các lỗi đã được khắc phục & kiểm chứng ở Vòng 1

| Mã lỗi cũ | Module | Nội dung đã khắc phục | Trạng thái |
| :--- | :---: | :--- | :---: |
| **BUG-03** | B0.1 | Bổ sung các định dạng ngày giờ không có giây (`%Y-%m-%d %H:%M`, `%d-%m-%Y %H:%M`, `%Y/%m/%d`) vào `parse_date()`. | ✅ Đã sửa & Pass test |
| **BUG-07** | B0.2 | Liên kết quy tắc nghiệp vụ với tên cột tiếng Việt gốc thông qua `ColumnMetadata.provenance`. | ✅ Đã sửa & Pass test |
| **BUG-08** | B0.2↔B0.3 | Sửa `format_context_for_prompt` đọc đúng `join_graph`, `key_candidates`, `provenance` và khoảng ngày trong `data_profiling`. | ✅ Đã sửa & Pass test |
| **BUG-09** | B0.3↔B0.5 | Loại bỏ giá trị mặc định `answer_type="generic"`, chuẩn hóa mọi bí danh về đúng 9 `AnswerType` của B0.5. | ✅ Đã sửa & Pass test |
| **BUG-11/12/20** | B0.3 | Loại bỏ khối `<think>...</think>`, dùng `sqlglot` AST trích xuất tên bảng (bỏ qua CTE và `EXTRACT(... FROM col)`). | ✅ Đã sửa & Pass test |
| **BUG-13/19** | B0.4↔B0.5 | `format_date` chấp nhận chuỗi ISO timestamp từ B0.4; `format_list/table` chuẩn hóa `Decimal` và `date/time`. | ✅ Đã sửa & Pass test |
| **BUG-14/15/16/17** | B0.4 | Che string literal/comment trước khi quét từ khóa cấm, kiểm tra `ALLOWED_ROOT_NODES`, chống crash `Decimal('Infinity')`, thêm cờ `truncated`. | ✅ Đã sửa & Pass test |

---

## 3. Phân Tích Chi Tiết 8 Lỗi & Xung Đột End-to-End (Minh Chứng, Lý Do & Giải Pháp)

---

### [E2E-01] `[CRITICAL]` Thiếu Bộ Điều Phối End-to-End (`B0Pipeline`) nối liền B0.1 → B0.2 → B0.3 → B0.4 → B0.5
- **Vị trí:**
  - [`src/datamate/b0/b02/cli.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/cli.py) (Chỉ chạy B0.1 + B0.2)
  - [`src/datamate/b0/b05/cli.py#L79-L121`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/cli.py#L79-L121) (Chỉ giả lập retry trên fixture tĩnh)
- **Minh chứng trong code:**
  Tại [`src/datamate/b0/b05/cli.py#L80-L108`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/cli.py#L80-L108):
  ```python
  # If action is RETRY, simulate bounded repair attempt
  if outcome.action == GateAction.RETRY:
      counts["retry_attempts"] += 1
      # Check if simulated mock repair can succeed or if it's exhausted
      simulated_success = raw_record.get("_simulate_retry_success", False)
      corrected_rows = raw_record.get("_simulate_corrected_rows", [[125]])
  ```
- **Giải thích lý do & Hệ quả:**
  - Hiện tại các module B0.1, B0.2, B0.3, B0.4, B0.5 nằm rời rạc ở 5 thư mục con. Chưa có một lớp điều phối trung tâm (`B0Pipeline`) để nhận đầu vào là câu hỏi (`QuestionMeta`), ngữ cảnh doanh nghiệp (`PreparedBusinessArtifacts` / `BusinessContext`) và mô hình (`BaseLLM`), sau đó điều khiển toàn bộ chu trình:
    1. Gọi B0.3 `Text2SQLGenerator.generate(context, question, as_of_date)`.
    2. Nếu `status == "unanswerable"`: Kiểm tra bằng chứng `EvidenceProof` và chuyển thẳng tới B0.5 `evaluate_gate()` (bỏ qua B0.4).
    3. Nếu `status == "answerable"`: Gọi B0.4 `execute_query()` trên `data.duckdb`, rồi chuyển cả kết quả sinh và kết quả thực thi sang B0.5 `evaluate_gate(attempt=0)`.
    4. Nếu B0.5 trả về `outcome.action == GateAction.RETRY` (hoặc B0.3 gặp `Text2SQLParseError` ở lần đầu): Lấy `outcome.repair_request` (chứa `failed_sql`, `error_message`, `instruction`), gọi B0.3 `Text2SQLGenerator.repair(...)`, thực thi lại qua B0.4 với `retry_count=1`, và đánh giá qua B0.5 với `attempt=1`.
    5. Ghi nhật ký từng lần thử (`writer.record_attempt`) và kết quả cuối cùng (`writer.write_final`) vào `submission.jsonl`.
- **Hướng giải quyết:**
  Xây dựng module [`src/datamate/b0/pipeline.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/pipeline.py) cung cấp lớp `B0Pipeline` (hỗ trợ cả chạy từng câu hỏi `answer_question()` và chạy toàn bộ file `questions.jsonl` `run_dataset()`), và xuất ra ở [`src/datamate/b0/__init__.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/__init__.py).

---

### [E2E-02] `[CRITICAL]` Xung đột điều phối `unanswerable` giữa B0.2, B0.3, B0.4 và B0.5
- **Vị trí:**
  - [`src/datamate/b0/b03/types.py#L125-L136`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L125-L136)
  - [`src/datamate/b0/b04/schemas.py#L44-L64`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/schemas.py#L44-L64)
  - [`src/datamate/b0/b05/gate.py#L24-L53`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/gate.py#L24-L53)
  - [`src/datamate/b0/b05/answerability.py#L8-L39`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/answerability.py#L8-L39)
- **Minh chứng trong code:**
  Tại [`src/datamate/b0/b05/gate.py#L25-L53`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/gate.py#L25-L53):
  ```python
  # 1. Evidence-Based Answerability Check (Prioritized before execution)
  is_unanswerable, ua_reason = evaluate_answerability(request)
  if is_unanswerable:
      return GateOutcome(..., decision=Decision.UNANSWERABLE, ...)

  # If generation claims unanswerable without trusted catalog-verified proof -> abstain
  if request.generation and request.generation.answer_type == AnswerType.UNANSWERABLE:
      return GateOutcome(
          action=GateAction.FINAL,
          question_id=question_id,
          decision=Decision.ABSTAIN,
          final_answer=FinalAnswer(id=question_id, type=AnswerType.ABSTAIN),
          reason_code=ErrorCode.MISSING_EVIDENCE, ...
      )
  ```
- **Giải thích lý do & Hệ quả:**
  - Khi câu hỏi không thể trả lời từ dữ liệu (ví dụ hỏi về dữ liệu năm 2020 trong khi bảng chỉ có dữ liệu năm 2026, hoặc hỏi cột không có trong `SchemaCatalog`), B0.3 trả về `Text2SQLResult(status="unanswerable", sql=None, reason="...")`.
  - Thứ nhất: Nếu caller truyền kết quả này vào `ExecutionRequest.from_b03()`, `sql_query` sẽ là `""` và B0.4 sẽ báo lỗi `EmptyQueryError` thay vì bỏ qua bước thực thi SQL.
  - Thứ hai: Khi sang B0.5, vì không có hàm nào đối chiếu `Text2SQLResult` với `BusinessContext` (schema catalog, data profiling, answerability constraints) để sinh ra `EvidenceProof(source_kind="catalog_verified", capability_status="unsupported", checked_all_sources=True, ...)`, hàm `evaluate_answerability(request)` luôn trả về `False` và dòng 43 của `gate.py` biến **100% câu trả lời `unanswerable` thành `abstain`**!
- **Hướng giải quyết:**
  - Bổ sung hàm `build_evidence_proof(context, b03_result, question="", as_of_date="") -> EvidenceProof` trong B0.3/pipeline: kiểm tra thực tế trên `SchemaCatalog`, `answerability_constraints`, và `data_profiling` của `BusinessContext`. Khi xác nhận tất cả các bảng trong catalog đã được kiểm tra (`checked_all_sources=True`, `available_fields=[...]`) và có căn cứ thiếu trường/không hỗ trợ (`missing_fields` hoặc `proof` trích xuất từ `answerability_constraints` / kiểm tra catalog), trả về `EvidenceProof(source_kind="catalog_verified", capability_status="unsupported", ...)`.
  - Trong [`answerability.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/answerability.py), nếu `request.generation` có `reason` cụ thể (hoặc `proof` có mô tả), giữ hoặc kết hợp lý do rõ ràng cho `FinalAnswer.reason`.

---

### [E2E-03] `[CRITICAL]` Xung đột phân loại lỗi giữa B0.4 (`error_handler.py`) và B0.5 (`retry.py`) làm mất quyền Bounded Retry
- **Vị trí:**
  - [`src/datamate/b0/b04/error_handler.py#L20-L65`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/error_handler.py#L20-L65)
  - [`src/datamate/b0/b05/retry.py#L20-L65`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py#L20-L65)
- **Minh chứng trong code:**
  Tại B0.4 [`error_handler.py:36-47`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/error_handler.py#L36-L47):
  ```python
  if isinstance(exc, duckdb.CatalogException):
      return "CatalogError", True
  if isinstance(exc, duckdb.BinderException):
      return "BinderError", True
  if isinstance(exc, duckdb.ConversionException):
      return "ConversionError", True
  if isinstance(exc, (duckdb.DataError, duckdb.OutOfRangeException)):
      return "DataError", True
  ```
  Nhưng tại B0.5 [`retry.py:28-50`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py#L28-L50):
  ```python
  if "binder" in text or "not found" in err_msg or "unknown table" in err_msg or "column" in err_msg:
      return ErrorClassification(code=ErrorCode.SCHEMA_ERROR, retryable=True, ...)
  if "parser" in text or "syntax" in text or "syntax error" in err_msg:
      return ErrorClassification(code=ErrorCode.SQL_SYNTAX, retryable=True, ...)
  if "cast" in text or "type mismatch" in text or "conversion" in text:
      return ErrorClassification(code=ErrorCode.SQL_TYPE_ERROR, retryable=True, ...)
  ```
- **Giải thích lý do & Hệ quả:**
  - Khi LLM viết sai tên bảng trong DuckDB (ví dụ `SELECT * FROM orders` trong khi bảng tên là `don_hang_a1b2c3d4`), DuckDB ném `CatalogException: Catalog Error: Table with name orders does not exist!`.
  - B0.4 gán `error.type = "CatalogError"`, `error.message = "Catalog Error: Table with name orders does not exist!"`.
  - Khi chuyển sang B0.5 `classify_error()`, chuỗi `text` không chứa `"binder"`, không chứa `"not found"`, không chứa `"unknown table"`, không chứa `"column"`. Do đó B0.5 rơi xuống cuối hàm và trả về `ErrorCode.EXECUTOR_FAILURE` với **`retryable=False`**!
  - Tương tự, `DataError` (`OutOfRangeException`, `Invalid Input Error`, `divide by zero`) và `EmptyQueryError` từ B0.4 cũng bị B0.5 đánh thành `EXECUTOR_FAILURE` (`retryable=False`).
  - **Hệ quả:** Những lỗi điển hình nhất mà vòng lặp Bounded Retry được thiết kế để sửa (LLM gọi tên bảng chưa chuẩn hóa `don_hang` thay vì `don_hang_a1b2c3d4`, gọi sai tên hàm SQLite thay vì DuckDB, lỗi ép kiểu ngày tháng) đều bị B0.5 chặn đứng không cho retry!
- **Hướng giải quyết:**
  Trong [`src/datamate/b0/b05/retry.py#L28-L50`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/retry.py#L28-L50):
  - Nhánh `SCHEMA_ERROR`: Bổ sung `"catalog" in text or "does not exist" in err_msg`.
  - Nhánh `SQL_SYNTAX`: Bổ sung `"emptyqueryerror" in err_type or "empty" in err_msg`.
  - Nhánh `SQL_TYPE_ERROR`: Bổ sung `"dataerror" in err_type or "out of range" in text or "invalid input" in text`.

---

### [E2E-07] `[CRITICAL]` Cột ẩn nội bộ `__dm_row_id` của B0.1 bị rò rỉ vào kết quả `SELECT *` ở B0.4 & B0.5
- **Vị trí:**
  - [`src/datamate/b0/b01/ingestion/preparation.py#L618-L620`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py#L618-L620)
  - [`src/datamate/b0/b04/engine.py#L128-L147`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L128-L147)
- **Minh chứng trong code:**
  Tại B0.1 [`preparation.py:618-620`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py#L618-L620):
  ```python
  normalized.load(
      connection, quote(name), {"__dm_row_id": "BIGINT", **types}
  )
  ```
  Tại B0.4 [`engine.py:128-146`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L128-L146):
  ```python
  cursor = con.execute(cleaned_sql)
  columns = [desc[0] for desc in cursor.description] if cursor.description else []
  raw_rows = cursor.fetchmany(request.max_rows + 1)
  ```
- **Giải thích lý do & Hệ quả:**
  - Mọi bảng dữ liệu do B0.1 tạo ra trong `data.duckdb` đều có cột đầu tiên là `__dm_row_id` (dùng nội bộ để nối với `meta.lineage`). Cột này đã được ẩn khỏi `SchemaCatalog` nên LLM không biết sự tồn tại của nó.
  - Khi LLM viết câu truy vấn `SELECT * FROM don_hang_...` (hoặc `SELECT t.* FROM ...`), DuckDB trả về cột `__dm_row_id` ở vị trí đầu tiên!
  - Với câu hỏi `answer_type="table"`, kết quả nộp bài sẽ bị dư cột `__dm_row_id`! Với câu hỏi `answer_type="number"` hoặc `"string"` mà bảng chỉ có 1 cột nghiệp vụ và LLM viết `SELECT * FROM ... LIMIT 1`, kết quả trả về sẽ có 2 cột (`__dm_row_id` và cột nghiệp vụ), dẫn đến lỗi `SCALAR_SHAPE_MISMATCH` ở B0.5!
- **Hướng giải quyết:**
  Trong [`src/datamate/b0/b04/engine.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/engine.py#L129-L147), sau khi lấy `columns` từ `cursor.description`, nếu có các cột không bắt đầu bằng `"__dm_"`, tự động lọc bỏ các cột nội bộ có tên bắt đầu bằng `"__dm_"` (như `__dm_row_id`, `__dm_source_row`, `__dm_formula_cache`) khỏi cả `columns` và từng dòng dữ liệu `rows`.

---

### [E2E-04] `[REQUIRED]` Suy luận tự động `AnswerSemantics` (`money_vnd`, `average_money_vnd`, `fraction`) giữa B0.3 và B0.5
- **Vị trí:**
  - [`src/datamate/b0/b03/types.py#L131-L158`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py#L131-L158)
  - [`src/datamate/b0/b05/formatter.py#L45-L93`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b05/formatter.py#L45-L93)
- **Giải thích lý do & Hệ quả:**
  - Trong thực tế, LLM thường chỉ trả về `"answer_type": "number"` hoặc `"percent"` mà quên điền object `"answer_semantics"`.
  - Nếu câu SQL tính `AVG(thanh_tien)` hoặc `SUM(don_gia * so_luong * 0.9)` mà không có `numeric_kind="money_vnd"` (hoặc `"average_money_vnd"`), B0.5 sẽ trả về số thực có 2 chữ số thập phân (ví dụ `125000.5`) thay vì làm tròn đến hàng đơn vị đồng (`125001`).
- **Hướng giải quyết:**
  Trong `Text2SQLResult.to_b05_generation_result()`, nếu `answer_type == "number"` và chưa có `numeric_kind`, tự động suy luận từ biểu thức SQL:
  - Nếu biểu thức chiếu là `COUNT(...)` -> `"count"`.
  - Nếu biểu thức chiếu chứa các tên cột tiền tệ phổ biến (`tien`, `gia`, `doanh_thu`, `chi_phi`, `lai`, `no`, `chiet_khau`, `amount`, `cost`, `price`, `revenue`, `profit`) kết hợp `AVG(` -> `"average_money_vnd"`, kết hợp `SUM(` -> `"money_vnd"`.

---

### [E2E-05] `[REQUIRED]` Khám phá cạnh Join tự động trong B0.1 (`schema_catalog.py`) bị chặn bởi 5 dòng mẫu khi dùng `DuckDBProfileProvider`
- **Vị trí:**
  - [`src/datamate/b0/b01/schema_catalog.py#L124-L148,L218-L227`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L124-L227)
  - [`src/datamate/b0/b01/ingestion/profiling.py#L65-L107`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/profiling.py#L65-L107)
- **Minh chứng trong code:**
  Tại [`schema_catalog.py:133-148`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py#L133-L148):
  ```python
  left_values = value_profiles[(left.name, left_col.name)]
  right_values = value_profiles[(right.name, right_col.name)]
  if not left_values or not right_values:
      continue
  shared = left_values & right_values
  ...
  if coverage < 0.8:
      continue
  ```
- **Giải thích lý do & Hệ quả:**
  - Khi chạy `prepare_business()` trên CSV/XLSX, `DuckDBMetadataProvider` chỉ lấy 5 dòng đầu tiên vào `table.profile_rows`.
  - Nếu 5 dòng đầu của bảng `don_hang` và 5 dòng đầu của bảng `khach_hang` không trùng đủ 80% mã khách (`coverage < 0.8`), cặp cột `ma_khach` bị `continue` bỏ qua ngay lập tức mà không bao giờ được đưa xuống `self.profile_provider.check_join()` ở dòng 225!
- **Hướng giải quyết:**
  - Khi `self.profile_provider is not None`, không lọc bỏ theo 5 dòng `profile_rows` ở dòng 135–148; thay vào đó, tạo cạnh ứng viên cho các cột khóa trùng tên (`ma_*`, `*_id`, `id`, `sku`, `code`) và để `self.profile_provider.check_join()` chạy SQL `INTERSECT` trên toàn bộ bảng DuckDB.
  - Trong `DuckDBProfileProvider.check_join()`, khi kiểm tra cạnh tự suy luận (`not edge.evidence`), tính `coverage = max(overlap / ldistinct, overlap / rdistinct)`. Nếu `coverage < 0.8`, trả về `status="invalid", confidence=0.0`, và lọc bỏ các cạnh tự suy luận có `status == "invalid"` khỏi `edges` trong `SchemaCatalogBuilder.build()`.

---

### [E2E-06] `[REQUIRED]` Lọc và sắp xếp quy tắc nghiệp vụ qua `RuleResolver` trước khi đưa vào Prompt B0.3
- **Vị trí:**
  - [`src/datamate/b0/b02/rule_resolver.py#L30-L90`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b02/rule_resolver.py#L30-L90)
  - [`src/datamate/b0/b03/prompt.py#L106-L115`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py#L106-L115)
- **Giải thích lý do & Hệ quả:**
  - Trong `rulebook.md`, có nhiều mục quy tắc theo từng ngành (`scope="industry"`, ví dụ: Nhà thuốc, F&B, Bán lẻ...) và quy tắc mặc định (`scope="split_default"`). Trong `README.md` của từng doanh nghiệp lại có quy tắc riêng (`scope="business"`, `precedence=300`) ghi đè quy tắc mặc định (`precedence=100`) và khai báo ngành của doanh nghiệp đó.
  - Hiện tại `format_context_for_prompt` trong `prompt.py` in toàn bộ danh sách `rules` thô mà không phân biệt `scope`/`industry` hay loại bỏ quy tắc `split_default` đã bị `business` ghi đè cùng `topic`.
- **Hướng giải quyết:**
  Trong `format_context_for_prompt()`, tự động nhận diện ngành của doanh nghiệp (nếu có nêu trong các quy tắc `scope="business"` của `README.md`), lọc bỏ các quy tắc `scope="industry"` của những ngành khác không liên quan, và khi có nhiều quy tắc cùng `topic`, chỉ giữ lại quy tắc có `precedence` cao nhất (hoặc ghi rõ nhãn `[Ưu tiên doanh nghiệp]` vs `[Mặc định]`).

---

### [E2E-08] `[OPTIONAL]` Bảo vệ dòng lặp Header cho bảng 1 cột & Tối ưu hóa `XLSXReader.discover` trong B0.1
- **Vị trí:** [`src/datamate/b0/b01/ingestion/readers.py#L240-L241,L270-L285,L386-L387`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/readers.py#L240-L285)
- **Hướng giải quyết:**
  - Tách hàm `_is_repeated_header(values, headers)`: chỉ trả về `True` khi bảng có ít nhất 2 cột (hoặc cột duy nhất không phải tên tự sinh `column_1`) và dòng dữ liệu khớp với `headers`.
  - Trong `XLSXReader.discover`, chỉ mở `original = load_workbook(..., data_only=False)` tối đa 1 lần duy nhất cho cả file Excel (lazy-open) và đóng ở khối `finally` ngoài cùng.

---

## 4. Kết Luận Kiểm Toán

Bản phân tích trên đã quét sạch mọi ngóc ngách từ **B0.1 → B0.2 → B0.3 → B0.4 → B0.5**. Toàn bộ kế hoạch triển khai chi tiết theo cấu trúc **Vertical Slices & ADRs** được lưu tại [`docs/plan/B0_REMEDIATION_PLAN.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/plan/B0_REMEDIATION_PLAN.md).

