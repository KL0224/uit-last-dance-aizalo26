# Báo cáo đánh giá baseline đầu tiên trên Public Test — Zalo AI Challenge 2026 Track 2

**Ngày phân tích:** 2026-11-09

**Ground truth:** `temp/gt/public_test_GT.jsonl`

**Run được đánh giá:** `artifacts/runs/public_test_full`

**Submission:** `artifacts/runs/public_test_full/submission.jsonl`

**Quy mô:** 1.000 câu hỏi, 14 doanh nghiệp (`dev_001`–`dev_014`)

## 1. Kết luận điều hành

Baseline đạt **266 câu đúng, 481 câu sai và 253 câu bỏ qua (`abstain`)**. Theo luật `đúng = +1`, `sai = -1`, `abstain = 0`, điểm đối chiếu local là:

```text
(266 - 481) / 1.000 = -0,215
```

Kết quả này nhất quán với điểm leaderboard **-0,2** nếu leaderboard hiển thị một chữ số thập phân. So với mức tối đa `1,0`, hệ thống còn thiếu 1.215 điểm thô: sửa một câu sai thành đúng tăng 2 điểm, còn sửa một câu abstain thành đúng tăng 1 điểm.

Vấn đề chính không phải thiếu dòng submission: cả ground truth, submission, detailed log và gate trace đều có đủ 1.000 dòng. Vấn đề là hệ thống **trả lời quá nhiều khi độ chính xác chưa đủ**: 747 câu được trả lời nhưng chỉ 266 câu đúng, tức độ chính xác trên các câu đã trả lời chỉ **35,6%**. Với cơ chế `+1/-1`, mọi nhóm câu có độ chính xác dưới 50% đều có kỳ vọng điểm âm.

## 2. Findings theo mức ưu tiên

### [P1] Không phát hành câu trả lời chỉ vì SQL chạy thành công — `artifacts/runs/public_test_full/detailed_logs.jsonl`

Trong 606 câu có `reason_code=VALID_RESULT`, chỉ 208 câu đúng và 398 câu sai, tức precision chỉ **34,3%**. Gate hiện chứng minh được truy vấn chạy và output đúng shape, nhưng chưa chứng minh truy vấn trả lời đúng metric nghiệp vụ. Đây là nguồn mất điểm lớn nhất: **391/481 câu sai có đúng kiểu output nhưng sai giá trị**, còn 90 câu sai kiểu.

### [P1] Siết lại xác minh `unanswerable` để không coi tên trường do LLM tự đặt là bằng chứng — `src/datamate/b0/b03/evidence.py:107`

Submission phát ra 47 câu `unanswerable`; chỉ 21 câu đúng và 26 câu thực ra trả lời được. Hàm xác minh hiện coi một `missing_field` là bằng chứng đáng tin nếu token đó không trùng tên bất kỳ cột nào trong catalog, rồi trả `catalog_verified` tại `evidence.py:147`. Vì LLM có thể tự tạo các tên như `orders_in_T4_2026`, `data_week_7_2025`, `period_definition` hoặc `chi_phi`, điều kiện này dễ được vượt qua dù dữ liệu thật vẫn đủ.

Ví dụ:

- `q_4b2f4e1688fa`: hỏi số đơn huỷ tháng 4/2026, đáp án là `29`, nhưng hệ thống kết luận thiếu `orders_in_T4_2026`.
- `q_fe5788dae82e`: hỏi doanh thu tháng 12/2025, đáp án là `224943500`, nhưng hệ thống kết luận thiếu `quận`, `chi_nha_nuoc`, `dia_ban` dù câu hỏi không yêu cầu địa lý.
- `q_0389b0c41da6`: câu so sánh doanh thu dịp Tết có đáp án `-16.02%`, nhưng bị đánh dấu thiếu `calendar.csv`.

Ở chiều ngược lại, 5/31 câu ground-truth `unanswerable` bị trả lời sai và 5 câu bị abstain. Ví dụ `q_008fdebb6ec9` không có cột nhóm hàng nhưng SQL tự suy “nhóm trà” bằng `LOWER(ten_san_pham) LIKE '%trà%'`, tạo ra một đáp án có vẻ hợp lý nhưng sai luật dữ liệu.

### [P1] Sửa suy luận kiểu output cho truy vấn có CTE — `src/datamate/b0/b03/parser.py:118`

Hệ thống phát ra 38 câu kiểu `table` trong khi ground truth chỉ có 11 câu `table`; **cả 38 output `table` đều sai**. Trong đó có 10 câu chuẩn là `number`, 5 `percent`, 11 `list`, 9 `date`, 2 `string` và 1 `table` sai nội dung.

Nguyên nhân code-level có thể tái hiện: `_extract_projection()` cắt tại từ khoá `FROM` đầu tiên. Với SQL bắt đầu bằng `WITH`, nó đọc projection của CTE thay vì projection của `SELECT` ngoài cùng. Nếu CTE có nhiều cột, `normalize_answer_type()` có thể giữ hoặc suy thành `table` dù truy vấn cuối chỉ trả một scalar/list/date. Cần dùng AST `sqlglot` để lấy projection của statement ngoài cùng thay cho regex.

### [P1] Giảm `GENERATION_INVALID` và lưu raw response đầy đủ để chẩn đoán — `configs/qwen3_5_9b.toml:11`

Có 166 câu abstain trực tiếp vì `GENERATION_INVALID`; ngoài ra lỗi này xuất hiện ở lượt repair của nhiều câu `RETRY_EXHAUSTED`. Cấu hình đang bật `enable_thinking=true`, `max_new_tokens=8192`, không có stop sequence. Các lỗi được lưu đều bắt đầu bằng reasoning tiếng Anh như `Thinking Process...` hoặc `The user is asking...` thay vì JSON/SQL có thể parse.

Log lỗi chỉ giữ `raw_text[:300]` tại `parser.py:473`, nên artifact hiện tại không đủ để phân biệt chắc chắn giữa: model không sinh final JSON, output bị cắt giữa reasoning, hay parser bỏ sót final JSON ở cuối. Dù vậy, bằng chứng đủ để kết luận structured-output contract chưa ổn định. Cần lưu raw response đầy đủ (hoặc hash + finish reason + token counts) và benchmark `enable_thinking=false` cho nhiệm vụ Text-to-SQL.

### [P1] Bắt buộc kiểm tra tính nhất quán của submission trước khi nộp — `artifacts/runs/public_test_full/submission.jsonl:973`

`submission.jsonl` lệch với cả `detailed_logs.jsonl`, `gate_trace.jsonl` và log từng câu ở đúng 2 ID:

- `q_fa1084dc1d3f`: gate chuẩn là `unanswerable` và khớp ground truth, nhưng submission chứa kiểu không hợp lệ `ubstain`.
- `q_fb290d8944ec`: gate chuẩn là `abstain`, nhưng submission chứa kiểu không hợp lệ `ananswerable` và mang nhầm reason về “cảnh báo bà bầu” từ câu trước.

Mtime của submission muộn hơn detailed/gate logs khoảng 17 phút, vì vậy bằng chứng phù hợp hơn với một bước hậu xử lý/ghi đè sau run thay vì lỗi trong gate. Hai dòng này làm mất 3 điểm thô so với output canonical của gate: điểm sẽ là `-0,212` thay vì `-0,215`. Mức ảnh hưởng nhỏ ở run này nhưng đây là lỗi integrity nghiêm trọng vì có thể phá hỏng submission tốt hơn.

### [P1] Khóa đúng grain dữ liệu: đơn hàng, dòng hàng, khách hàng và lô tồn — SQL trong detailed logs

Nhiều truy vấn đúng cú pháp nhưng tính sai thực thể:

- `q_585664a97754`: hỏi số đơn hôm qua, SQL dùng `COUNT(*)` trên bảng chi tiết; dự đoán `223`, đáp án `135`. Phải đếm distinct mã đơn.
- `q_10831a6f3a2b`: join sổ hạn nợ với mọi dòng bán hàng rồi `COUNT(*)`; dự đoán `2276`, đáp án `152`. Join đã nhân bản mỗi đơn theo số dòng hàng.
- `q_522627a83f38`: cộng `thanh_tien` trực tiếp trên chi tiết hoá đơn; ba tháng đều cao gần ba lần đáp án vì giá trị cấp đơn bị lặp theo dòng.
- `q_0ca19cd317cb`: dùng `slnhap_quy_doi > 0` để suy “còn tồn”, trả 75 sản phẩm thay vì 10; lượng nhập dương không đồng nghĩa tồn hiện tại dương sau xuất/bán.

Giải pháp phải bắt đầu từ semantic contract theo từng bảng: primary key, grain, cột tiền ở cấp dòng hay cấp đơn, và quy tắc deduplicate trước khi aggregate.

### [P1] Phân biệt metric được hỏi trước khi sinh SQL — SQL trong detailed logs

Có các lỗi đổi hẳn metric nhưng vẫn vượt gate:

- `q_37a4aca072a6`: hỏi số đơn quý 4, SQL lại `SUM(tong_tien)`; dự đoán `1.548.111.500`, đáp án `3.316` đơn.
- `q_c76ae61c6092`: hỏi tổng số đơn 30 ngày, SQL lại tính doanh thu; dự đoán `3.229.305.600`, đáp án `2.002` đơn.
- `q_c0d31d97c743`: hỏi tỉ trọng doanh thu nhóm ho/cảm cúm, SQL chỉ trả tổng doanh thu toàn tháng; output gắn nhãn `percent` nhưng giá trị là `276.978.800`, đáp án `8,99`.

Gate cần đối chiếu intent với SQL AST: câu hỏi “bao nhiêu đơn” phải có count distinct order key; “bao nhiêu phần trăm/tỉ trọng” phải có tử số, mẫu số và phép chia; “trung bình” phải có mẫu đếm đúng grain.

### [P2] Kiểm soát thời gian, trạng thái, quy đổi đơn vị và dấu của phép so sánh

Trong 352 câu `number/percent` sai giá trị cùng kiểu, median sai số tương đối là **44,97%**; 129 câu sai từ 100% trở lên. Có 10 câu sai cả dấu tăng/giảm. Chỉ 33 câu nằm trong sai số 1%, nhưng luật chấm so số gần như exact (`1e-6`), nên gần đúng vẫn nhận `-1`.

Nhóm lỗi thường gặp qua SQL và reasoning:

- tính sai biên `hôm nay`, `hôm qua`, `tuần này`, `tuần trước`, cùng kỳ và khoảng “N ngày kể từ”;
- chọn sai năm/bảng tháng khi một bảng chứa nhiều năm;
- lọc trạng thái không nhất quán (`completed` so với `delivering`, huỷ, trả hàng, không giao được);
- không quy đổi hộp/vỉ/viên, thùng/bịch, bó/cây theo rulebook;
- đảo tử số/mẫu số hoặc thứ tự kỳ hiện tại/kỳ trước;
- cộng dòng trả hàng thay vì loại cả đơn theo luật tương ứng.

## 3. Kết quả tổng thể

| Chỉ số | Số lượng | Tỷ lệ trên 1.000 câu | Điểm thô |
|---|---:|---:|---:|
| Đúng | 266 | 26,6% | +266 |
| Sai | 481 | 48,1% | -481 |
| Abstain | 253 | 25,3% | 0 |
| **Tổng** | **1.000** | **100%** | **-215** |

Các chỉ số dẫn xuất:

- Điểm PA local: **-0,215** (`-21,5%`).
- Accuracy thô: **26,6%**.
- Coverage trả lời: **74,7%**.
- Accuracy trên câu đã trả lời: **35,6%** (`266/747`).
- Nếu oracle chỉ đổi toàn bộ 481 câu sai thành abstain, không sửa thêm câu nào, điểm đã tăng thành **+0,266**. Điều này cho thấy risk gate có giá trị lớn trong giai đoạn baseline.
- Để đạt điểm dương mà chưa tăng số câu đúng, cần chặn ít nhất 216/481 câu sai hiện tại.

## 4. Kết quả theo loại đáp án ground truth

| Loại chuẩn | Tổng | Đúng | Sai | Abstain | Điểm thô |
|---|---:|---:|---:|---:|---:|
| `number` | 597 | 167 (28,0%) | 292 (48,9%) | 138 (23,1%) | -125 |
| `percent` | 189 | 42 (22,2%) | 104 (55,0%) | 43 (22,8%) | -62 |
| `list` | 64 | 8 (12,5%) | 30 (46,9%) | 26 (40,6%) | -22 |
| `string` | 57 | 13 (22,8%) | 27 (47,4%) | 17 (29,8%) | -14 |
| `date` | 40 | 9 (22,5%) | 20 (50,0%) | 11 (27,5%) | -11 |
| `unanswerable` | 31 | 21 (67,7%) | 5 (16,1%) | 5 (16,1%) | +16 |
| `boolean` | 11 | 6 (54,5%) | 1 (9,1%) | 4 (36,4%) | +5 |
| `table` | 11 | 0 (0,0%) | 2 (18,2%) | 9 (81,8%) | -2 |

Ưu tiên theo tác động điểm là `number` rồi `percent`: hai nhóm này chiếm 786/1.000 câu và đóng góp **-187/-215 điểm thô**. `list` có accuracy thấp nhất trong các loại phổ biến. `table` chưa có một câu đúng nào.

## 5. Phân rã 481 câu sai

| Nhóm sai | Số câu | Tỷ lệ trong số câu sai | Diễn giải |
|---|---:|---:|---|
| Đúng kiểu, sai giá trị/nội dung | 391 | 81,3% | SQL chạy và output đúng shape nhưng sai metric, grain, filter, join, thời gian hoặc nghiệp vụ |
| Sai kiểu output | 90 | 18,7% | Điển hình là `table` thay `number/list/date`, `string` thay `unanswerable`, hoặc `unanswerable` giả |

Riêng các câu số:

- 352 câu `number/percent` sai giá trị dù đúng type.
- Median sai số tương đối: **44,97%**.
- 33 câu lệch không quá 1%; 104 câu lệch không quá 5%; 123 câu lệch không quá 10%.
- 129 câu lệch ít nhất 100%.
- 10 câu sai dấu tăng/giảm.
- Chỉ 1 câu (`q_35c586d5d831`) có thể cứu đúng đơn thuần bằng làm tròn số tiền (`237009,22` → `237009`). Phần lớn không phải lỗi formatter mà là lỗi truy vấn/nghiệp vụ.

## 6. Phân rã 253 câu abstain

| Reason code | Số câu | Tỷ lệ abstain | Nhận định |
|---|---:|---:|---|
| `GENERATION_INVALID` | 166 | 65,6% | Không trích xuất được JSON hoặc SQL hợp lệ từ output model |
| `RETRY_EXHAUSTED` | 43 | 17,0% | SQL đầu lỗi; lượt sửa tiếp tục lỗi hoặc generation invalid |
| `NULL_RESULT` | 32 | 12,6% | Query chạy nhưng trả scalar `NULL`, thường do sai khoảng ngày/filter |
| `EMPTY_RESULT` | 9 | 3,6% | Query chạy nhưng không có dòng, thường do join/filter quá chặt hoặc sai ngày |
| `MISSING_EVIDENCE` | 2 | 0,8% | Model nói unanswerable nhưng evidence gate không xác nhận |
| `EXECUTOR_FAILURE` | 1 | 0,4% | Lỗi executor không được repair |

`RETRY_EXHAUSTED` không chỉ là lỗi executor. Ví dụ `q_01ba91ff94c6` sinh SQL đúng bằng chuỗi `...` ở attempt 0, sau đó attempt 1 lại `GENERATION_INVALID`. Cần tách retry sửa SQL khỏi retry sửa contract output và dùng prompt ngắn, có schema lỗi cụ thể.

## 7. Kết quả theo doanh nghiệp

| Business | Tổng | Đúng | Sai | Abstain | Điểm thô |
|---|---:|---:|---:|---:|---:|
| dev_001 | 87 | 22 (25,3%) | 52 (59,8%) | 13 (14,9%) | -30 |
| dev_002 | 41 | 4 (9,8%) | 31 (75,6%) | 6 (14,6%) | -27 |
| dev_003 | 129 | 18 (14,0%) | 73 (56,6%) | 38 (29,5%) | -55 |
| dev_004 | 96 | 16 (16,7%) | 55 (57,3%) | 25 (26,0%) | -39 |
| dev_005 | 87 | 33 (37,9%) | 34 (39,1%) | 20 (23,0%) | -1 |
| dev_006 | 111 | 51 (45,9%) | 36 (32,4%) | 24 (21,6%) | +15 |
| dev_007 | 60 | 18 (30,0%) | 31 (51,7%) | 11 (18,3%) | -13 |
| dev_008 | 99 | 23 (23,2%) | 57 (57,6%) | 19 (19,2%) | -34 |
| dev_009 | 21 | 5 (23,8%) | 13 (61,9%) | 3 (14,3%) | -8 |
| dev_010 | 59 | 27 (45,8%) | 17 (28,8%) | 15 (25,4%) | +10 |
| dev_011 | 40 | 9 (22,5%) | 13 (32,5%) | 18 (45,0%) | -4 |
| dev_012 | 50 | 22 (44,0%) | 18 (36,0%) | 10 (20,0%) | +4 |
| dev_013 | 57 | 10 (17,5%) | 24 (42,1%) | 23 (40,4%) | -14 |
| dev_014 | 63 | 8 (12,7%) | 27 (42,9%) | 28 (44,4%) | -19 |

Ba khu vực cần ưu tiên theo tổng thiệt hại là `dev_003` (-55), `dev_004` (-39) và `dev_008` (-34). `dev_002` có accuracy thấp nhất, chỉ 9,8%. Ngược lại `dev_006`, `dev_010`, `dev_012` đã có điểm thô dương; nên dùng chúng làm đối chứng để tìm xem schema/rule representation nào đang hoạt động tốt hơn.

## 8. Ví dụ lỗi đại diện

| ID | Câu hỏi rút gọn | Dự đoán | Ground truth | Nguyên nhân trực tiếp |
|---|---|---|---|---|
| `q_008fdebb6ec9` | Nhóm trà bán chạy nhất | `Trà đào cam sả (M)` | `unanswerable` | Suy nhóm từ tên sản phẩm dù dữ liệu không có nhóm hàng |
| `q_37a4aca072a6` | Số đơn quý 4/2025 | `1548111500` | `3316` | Dùng `SUM(tong_tien)` thay vì đếm đơn |
| `q_c76ae61c6092` | Số đơn 30 ngày gần nhất | `3229305600` | `2002` | Trả doanh thu thay vì số đơn |
| `q_585664a97754` | Số đơn hôm qua | `223` | `135` | `COUNT(*)` trên bảng chi tiết thay vì distinct order |
| `q_10831a6f3a2b` | Đơn bán chịu chưa tới hạn | `2276` | `152` | Join 1-n nhân bản đơn rồi đếm dòng |
| `q_c0d31d97c743` | Tỉ trọng nhóm ho/cảm cúm | `276978800%` | `8,99%` | SQL thiếu tử số/mẫu số, chỉ cộng doanh thu toàn tháng |
| `q_522627a83f38` | Doanh thu ba tháng | xấp xỉ 3 lần GT | ba số chuẩn | Cộng giá trị cấp đơn lặp lại trên từng dòng chi tiết |
| `q_0ca19cd317cb` | Lô còn tồn hết hạn 90 ngày | 75 sản phẩm | 10 sản phẩm | Dùng lượng nhập dương thay tồn hiện tại; không trừ xuất/bán |
| `q_013b4ff35811` | Doanh thu tuần này | `abstain` | `230034300` | Generation chỉ có reasoning, không parse được JSON/SQL |
| `q_fa1084dc1d3f` | Tư vấn thuốc cho bà bầu | `ubstain` | `unanswerable` | Submission bị sửa/corrupt sau gate; type không hợp lệ |

## 9. Hướng cải thiện theo thứ tự ROI

### Giai đoạn 0 — Chặn lỗi submission và thiết lập benchmark local

1. Tạo evaluator public-test chạy đúng `AnswersMatch()` hiện có và luôn sinh report trước khi zip/nộp.
2. Validate mỗi dòng bằng enum type chính thức; từ chối mọi type ngoài `number`, `percent`, `string`, `date`, `boolean`, `list`, `table`, `unanswerable`, `abstain`.
3. Đối chiếu `submission[id] == gate_trace[id].final_answer == detailed_logs[id].final_answer`; fail build nếu lệch dù chỉ một dòng.
4. Kiểm tra đủ đúng 1.000 ID, không trùng, không thiếu, không thừa.
5. Ghi checksum SHA-256 của submission ngay sau run và ngay trước upload.

**Tiêu chí đạt:** không còn `ubstain/ananswerable`; 0 mismatch giữa ba artifact; score local tái lập đúng tuyệt đối.

### Giai đoạn 1 — Sửa lỗi deterministic trước khi đổi model

1. Thay `_extract_projection()` bằng AST outer-select projection.
2. Thêm semantic SQL lint:
   - count order → bắt buộc distinct order key hoặc group order trước;
   - percent/share/growth → bắt buộc có phép chia và hai đại lượng;
   - average per order → tổng ở grain order rồi chia số order;
   - top-N/list → đúng một cột và đúng `LIMIT N`/thứ tự;
   - inventory → phải tính nhập − xuất/bán/trả theo rule, không dùng nhập dương làm tồn.
3. Tạo table-grain catalog cho từng business và đưa vào prompt dạng ngắn, máy đọc được.
4. Viết regression test bằng chính các ID đại diện ở mục 8.

**Tiêu chí đạt:** 38 lỗi `table` giảm về 0; không còn count-vs-sum; accuracy trên câu đã trả lời vượt 50%.

### Giai đoạn 2 — Sửa answerability gate

1. Chỉ cho phép `unanswerable` khi missing concept được ánh xạ vào capability taxonomy đã định nghĩa trước; không nhận tên field tự do do LLM bịa.
2. Yêu cầu bằng chứng âm: đã kiểm tra bảng/cột/rule nào, tại sao không thể suy ra từ cột hiện có.
3. Tách `missing physical field` khỏi `missing derived metric`. Metric như `orders_in_T4_2026` phải được lập từ ngày + order ID, không được coi là cột bắt buộc.
4. Thêm counterfactual check: trước khi chấp nhận unanswerable, một planner độc lập phải thử lập kế hoạch SQL tối thiểu từ catalog/rulebook.

**Tiêu chí đạt:** precision `unanswerable` ≥ 90%, recall ≥ 80%; hiện tại precision 44,7%, recall 67,7% theo submission.

### Giai đoạn 3 — Ổn định generation và repair

1. A/B test `enable_thinking=false` với schema JSON bắt buộc hoặc constrained decoding.
2. Giảm prompt/context bằng retrieval chỉ lấy bảng, cột và rules liên quan câu hỏi.
3. Lưu `finish_reason`, input/output token counts và raw response đầy đủ cho lỗi; không chỉ 300 ký tự đầu.
4. Retry generation invalid bằng prompt contract-only; retry SQL lỗi bằng error message + schema liên quan, không gửi lại toàn bộ reasoning.
5. Không cho chuỗi placeholder `...` đi tới executor.

**Tiêu chí đạt:** `GENERATION_INVALID` < 2%, `RETRY_EXHAUSTED` < 2%; hiện tại lần lượt ít nhất 16,6% và 4,3% toàn bộ tập.

### Giai đoạn 4 — Chuẩn hoá nghiệp vụ theo họ câu hỏi

Xây các plan/template đã kiểm chứng cho:

- doanh thu, số đơn, doanh thu trung bình/đơn;
- tăng giảm %, tỉ trọng %, tỉ lệ huỷ;
- top-N sản phẩm/khách hàng;
- nhập–bán–tồn và hạn dùng theo lô;
- nợ phát sinh, thu nợ, hạn nợ, trả góp;
- quy đổi đơn vị;
- kỳ tương đối: hôm nay/hôm qua/tuần/tháng/quý/cùng kỳ/Tết.

Mỗi template phải khai báo grain, status policy, time window, numerator, denominator, unit conversion và tie-break. LLM chỉ chọn và điền tham số; validator tái kiểm tra plan trước khi chạy.

## 10. Mục tiêu cho lần nộp tiếp theo

Mục tiêu tối thiểu thực tế nên là **điểm dương trước khi tối đa coverage**:

| Mốc | Điều kiện gợi ý | Điểm kỳ vọng tối thiểu |
|---|---|---:|
| Safety baseline | Giữ 266 câu đúng, chặn ít nhất 216 câu sai thành abstain | > 0,000 |
| Baseline ổn định | 350 đúng, tối đa 200 sai, còn lại abstain | ≥ 0,150 |
| Baseline cạnh tranh hơn | 500 đúng, tối đa 150 sai | ≥ 0,350 |

Không nên nộp lại chỉ vì số abstain giảm. Với scoring `+1/-1`, chỉ trả lời thêm khi precision của nhóm mới vượt 50%; nên đặt ngưỡng cao hơn, khoảng 65–70%, để có biên an toàn trước distribution shift.

## 11. Phương pháp và giới hạn phân tích

Phân tích dùng đúng logic so khớp trong `scripts/run_b0_pipeline.py`: type phải giống; scalar số gần như exact với tolerance `1e-6`; chuỗi chuẩn hoá hoa/thường, khoảng trắng và dấu câu; list phải đúng độ dài và thứ tự; table không phụ thuộc thứ tự dòng nhưng phải đúng shape và giá trị.

Các số liệu được đối chiếu giữa bốn nguồn: ground truth, submission, detailed logs và gate trace. Không chạy lại model hoặc sửa source code. Root cause ở cấp SQL được kết luận khi có truy vấn cụ thể chứng minh; các nhận định về generation được giới hạn bởi việc log chỉ lưu 300 ký tự đầu của raw response. Vì vậy báo cáo không khẳng định mọi `GENERATION_INVALID` đều do chạm trần token, mà xác định chắc chắn rằng structured output không được parser thu nhận và telemetry hiện chưa đủ để phân biệt nguyên nhân sâu hơn.
