# Neo grounding: Qwen2.5 + code verification

## Mục đích và luồng chạy

Luồng `llm_verified` dùng Qwen2.5-3B-Instruct trên mọi request hợp lệ có đủ prompt budget. Model trả proposal JSON; code kiểm schema, tham chiếu, phép tính, predicate, scope, unit references và phân giải thời gian. Proposal không có trust status do model tự xác nhận.

```text
Explicit bundle manifest + rulebook + calendar
    -> GroundingContextIndex (read-only, schema preflight)
Question + as_of_date + retrieved context
    -> NeoGroundingEngine -> one Qwen response -> Proposal
    -> verify_proposal + CalendarResolver + ValueVerificationProvider
    -> GroundedQuestion.planner_input (eight groups)
    -> GroundingToPlannerAdapter -> Planner generate / repair
```

Đường chạy mới nằm ở `scripts/run_neo_grounding.py`. Runner cũ tiếp tục dùng engine cũ để bảo toàn hành vi rollback. Không chạy ingestion, semantic discovery hoặc ghi lại bundle trong runner mới. Một instance Qwen được tái sử dụng cho tất cả câu; không có vòng model repair.

## Contract

Tám nhóm: `request`, `intent`, `source_plan`, `semantic_plan`, `temporal_plan`, `value_bindings`, `policies`, `assessment`. Version Planner `2.0` độc lập version bundle `1.1`.

Model trả proposal riêng trong `neo_contracts.py`; code tạo request identity, policies có nguồn, temporal boundaries và assessment. Schema cấm trường lạ, giới hạn số phần tử, enum phép toán và predicate. Không nhận SQL tự do.

Measures cơ sở khai báo aggregate + physical column refs; measure phái sinh khai báo operator + hai measure operands. Code kiểm cycle. Count có entity-key columns rõ ràng. Grain, entity scope và công thức còn là đề xuất ngữ nghĩa. Filter giữ nguyên cây AND/OR/NOT, scope row/group/measure/order. Unit có cột số lượng, đơn vị đích, conversion references và item scope; scope ứng dụng vẫn cần review.

`partial/unknown` là mặc định vì kiểm tham chiếu không chứng minh nghiệp vụ. Không tạo missing-evidence proof từ proposal hoặc lookup không tìm thấy. Không có fast-path unsupported do engine mới tự suy đoán.

## Thời gian và lịch âm

`TemporalSpec` phân biệt Gregorian và Vietnamese lunar. `CalendarResolver` đọc CSV có date, lunar_year/month/day/leap; kiểm mapping unique và ngày dương liên tục. Không dùng LLM hoặc thư viện bên ngoài để đoán ngày dương.

Hỗ trợ ngày, tháng/năm, this/previous period, tuần thứ Hai, N ngày gần nhất, khoảng explicit, snapshot, Tết, ngày âm lặp lại trong phạm vi dương có giới hạn. Khoảng dương nhập vào `range.end` là exclusive. Khoảng âm dùng `lunar_start` và `lunar_end_inclusive`.

Tết năm Y: 23 tháng Chạp Y-1 đến hết 10 tháng Giêng Y. Ví dụ nguồn hiện tại: Tết 2026 là `[2026-02-10, 2026-02-27)`, trước Tết cùng độ dài là `[2026-01-24, 2026-02-10)`. Rằm tháng Giêng 2026 là `[2026-03-03, 2026-03-04)`.

Tháng/năm âm dùng ngày từ calendar, không suy độ dài bằng Gregorian calendar. `leap=unspecified` gặp tháng thường và nhuận thì unresolved. Kỳ không có năm chọn theo năm của as_of trong đúng lịch, lùi một năm nếu kỳ có tên nằm sau anchor. Tháng explicit lấy cả tháng, `relative=this` đến hết anchor. Ngày lặp trả `ranges` với OR, không phủ bằng một khoảng min/max.

Mọi biên event dùng start-inclusive/end-exclusive. Snapshot dùng as_of_exclusive và history_start=unbounded. Evidence chứa calendar hash và spec. Thiếu coverage hoặc mơ hồ tạo TEMPORAL_UNRESOLVED. Tháng/năm bị cắt ở rìa calendar không được xác nhận đủ kỳ.

So sánh hỗ trợ previous_equal_days, previous_year, Gregorian previous_month_matched. So sánh lunar YTD/matched-month và Gregorian leap-day không có policy rõ được giữ unresolved. Không tự clamp ngày âm không tồn tại. Timezone theo ngày nghiệp vụ của nguồn; engine không tự đổi timezone.

## Verification và trust

Preflight mở DuckDB read-only, đối chiếu schema metadata với bảng/cột thật. Runtime không reprofile toàn bộ bảng. Prompt giữ source directory, rulebook, schema cards, business rules, metric/uncertain JOIN/unit candidates; bỏ phần evidence phụ theo budget. Thiếu budget cho phần bắt buộc thì fail trước inference.

Value verifier chỉ tra exact equality, giá trị bind parameters, identifier từ allowlist. Tối đa 2 query/request, 100ms/query và 200ms tổng budget query (thời gian mở connection không nằm trong deadline cancellation). Timer interrupt được cancel/join trước khi đóng connection. Cache LRU 4096 kết quả; timeout không cache như negative evidence. Không share connection đồng thời. Lookup không tìm thấy vẫn giữ literal của filter và ghi unresolved, không tự đổi câu hỏi.

JOIN mới giữ uncertain; chỉ kiểm refs/key pairs, chưa attestation cardinality. UNION ALL yêu cầu tên/type cột tương thích; model chọn explicit members và điều kiện ngày. Unit factor kiểm Decimal dương hữu hạn, target và item-column; không nhân lại cột already_converted. Scope sản phẩm vẫn semantic_unreviewed.

## Chạy local

Tạo manifest JSON ánh xạ business ID tới đúng thư mục fingerprint, đường dẫn tương đối với manifest:

```json
{"dev_001": "bundles/dev_001/exact-fingerprint"}
```

```bash
uv run python scripts/run_neo_grounding.py \
  --bundles artifacts/neo_input/bundles.json \
  --questions data/test/public_test/questions.jsonl \
  --rulebook data/test/public_test/rulebook.md \
  --calendar data/test/public_test/calendar.csv \
  --output artifacts/runs/neo_preflight --preflight
```

Bỏ `--preflight`, đổi output sang thư mục trống, truyền `--grounding-model /path/to/Qwen2.5-3B-Instruct` để inference. `--planner-config configs/qwen3_5_9b.toml` bật generate SQL, execution và Gate. Mặc định `--mode llm_verified`; rollback `rules`, `hybrid`, `off`. Model thiếu lỗi startup. Lỗi từng câu ghi failed; pipeline mode fallback theo pipeline hiện hữu.

Output: `preflight.json` và `results.jsonl` gồm ID, contract hoặc Gate outcome, diagnostics engine. Không ghi raw prompt/response mặc định. Output không được nằm trong bundle nguồn hoặc thư mục đã có dữ liệu.

## Chạy Modal

`scripts/modal_run_neo_grounding.py` nhận thư mục local `NEO_DATA_DIR` có manifest, questions, rulebook, calendar và bundle theo relative paths. Entrypoint tự tải Qwen2.5-3B-Instruct vào cache volume nếu chưa có. Xem [modal_smoke_3.md](modal_smoke_3.md) cho bộ ba câu đã chuẩn bị và output so sánh tải về local.

```bash
NEO_DATA_DIR=artifacts/neo_input uv run modal run scripts/modal_run_neo_grounding.py \
  --run-name neo_smoke --model-path /vol/models/Qwen--Qwen2.5-3B-Instruct
```

Entrypoint Modal hiện xuất grounding contracts; end-to-end Planner dùng local runner trên môi trường GPU. Không tự deploy/chạy GPU trong quá trình implementation.

## Kiểm thử và giới hạn

`tests/grounding/test_neo_grounding.py` kiểm ngày âm, Tết, tháng nhuận, khoảng âm, recurrence, missing coverage, MTD, one-call, invalid JSON, fake refs, cycle, predicate OR, exact-value SQL injection resistance và fallback context. Bộ hồi quy grounding/bridge/pipeline kiểm tương thích cũ. Preflight thực tế đọc đủ 14 business / 903 cột.

Chưa đo GPU quality/latency/OOM hoặc accuracy cuối. Budget output đã tăng từ 768 lên 2048 sau smoke test fail JSON; câu phức tạp vẫn có thể truncate; không chấp nhận JSON thiếu. Không tuyên bố p95 đạt 2s.

Các phần của plan chưa tự động hóa đầy đủ: semantic attestation metric/JOIN, JOIN coverage query, family routing tự động từ min/max, fuzzy alias verification, unit product-scope proof, proposal cache và chat_batch. Hint truyền JSON đầy đủ thay vì cắt theo 1024 token; giới hạn cuối chịu prompt budget Planner. Những mục này cần benchmark và bổ sung trước khi coi toàn bộ acceptance criteria của upgrade_grounding.md đã đạt. Implementation hiện tại giữ chúng partial/unresolved hoặc fallback; không giả vờ xác minh.

## Tài liệu module

Mỗi file Python trong `src/datamate/grounding` có file Markdown cùng tên trong thư mục này. Module mới: calendar_resolver, context_index, neo_contracts, neo_engine, neo_verifier, value_verifier. Các module C1–C5 cũ được ghi rõ vai trò rollback; contracts/adapters là bridge chung.

## Thay đổi sau hai lượt smoke fail: neo-compact-v3

Luồng model chuyển sang WireProposal với ID T*/C*/M*, giới hạn 8 measures và 8 time specs, ví dụ ngắn độc lập với dữ liệu evaluation và constrained decoding bắt buộc. Không đưa toàn bộ JSON Schema vào prompt. QwenStructuredBackend thay đường tái sử dụng C1 parser trong engine mới; model vẫn chỉ load một lần. Chi tiết ở compact_proposal.md, neo_prompt.md và neo_backend.md.

Cohort là field optional trong semantic_plan; tám nhóm cấp cao vẫn giữ nguyên. Verifier đối chiếu cohort.group_by với grain của measure rồi truyền result=count_groups/list_groups cho Planner. Trường hợp này cần hai cấp tổng hợp, không dùng số đơn thay số khách.

Core policies được code đưa vào contract dù model không chọn policy_refs. Context giữ tên cột nguồn/provenance và nhãn cảnh báo registry; budget trimming giữ ít nhất hai README policy rows được xếp cao. Budget output giữ 2048, không tăng thêm để che vòng lặp.

Debug lưu prompt system/user, decoding_schema, reference_map và raw_response. Model API không hỗ trợ schema-constrained sampling phải lỗi rõ; không âm thầm chạy text generation. Cách chạy Modal giữ nguyên, dùng output/run name mới.

## Temporal completeness v4

Prompt version hiện tại: neo-temporal-v4. WireProposal yêu cầu temporal_intent và time; mỗi WireTimeSpec phải chọn extent, comparison, role và scope. Thiếu hoặc sai metadata không bị che bởi default. CalendarResolver hỗ trợ full_period/to_as_of, còn temporal_validation kiểm cặp t0/t1 theo nguồn/measure. Các field mới cùng lỗi cụ thể giữ trong temporal_plan/assessment, không thêm nhóm cấp cao.

Hai kỳ explicit có thể là hai specs primary/comparison; một spec có previous_year hoặc previous_month_matched được code mở rộng thành hai constraints. Compare giữa hai measures cùng một kỳ có thể không cần hai window, nhưng phải có hai operands bind rõ.

Khi chỉ có t0, giữ t0 và các nhóm source/semantic hữu ích; đánh dấu incomplete + MISSING_COMPARISON_WINDOW, không nhận là complete và không tự thêm t1. Calculation_status tách semantic_status để không gọi toàn claim verified chỉ từ date arithmetic.

Tests ở test_temporal_completeness.py kiểm kỳ năm trước, MTD, Tết, scope mismatch, explicit roles, required fields, unknown metadata và YTD qua năm nhuận. Vẫn cần inference mới để đánh giá model chọn đúng temporal intent; schema/validator không chứng minh hiểu đúng ngôn ngữ.

## Cập nhật v6: giữ bằng chứng và partial theo claim

Prompt hiện tại là neo-partial-v6. Context budget giữ source/cột theo capability trước khi bỏ bằng chứng phụ; DATE-only decoding ngăn chọn mã đơn/giá làm ngày. Optional proposal items được parse/materialize độc lập. Verifier giữ phần hợp lệ, loại các dependent claims bị hỏng và ghi rejected_claims/unresolved/warnings. Measure bị thiếu dependency mang requires_repair; ngày tính được nhưng chưa bind giữ ở unbound_constraints. Planner nhận partial hint để sửa từ câu hỏi và context đầy đủ, không coi raw rejected claims là constraints hoạt động.

Xem [context_budget.md](context_budget.md), [proposal_recovery.md](proposal_recovery.md), [neo_verifier.md](neo_verifier.md). Replay trên CPU của run v5 `neo_smoke3_20261116_064222_419403` nằm ở `replay_partial_v6.json` trong cùng thư mục run: ba output cũ đều tạo được partial. Đây là kiểm recovery trên response đã lưu, không phải inference Qwen mới hoặc chứng minh độ đúng SQL/đáp án.
