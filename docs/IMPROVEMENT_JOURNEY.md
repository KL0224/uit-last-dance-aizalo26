 

# HÀNH TRÌNH CẢI TIẾN TOÀN DIỆN PIPELINE DATAMATE (B0.1 - B0.5)

**Dự án:** DataMate 2026 / Zalo AI Challenge 2024
**Nhánh công việc:** `improvement-b01-b02`
**Tác giả:** Người dùng & Trợ lý Antigravity
**Ngày cập nhật:** 10/11/2026

---

## 1. TỔNG QUAN HÀNH TRÌNH (EXECUTIVE SUMMARY)

Tài liệu này ghi lại toàn bộ quá trình hợp tác phân tích, sửa lỗi và tối ưu hóa pipeline Text-to-SQL qua từng cột mốc thực chiến: từ điểm xuất phát âm nặng (**`-0.227`**), vươn lên **`-0.03100`** sau đợt cải tiến Vòng 1, phát hiện các điểm nghẽn qua Ground Truth, xử lý bài học cấu hình Reasoning Token trên Modal GPU (V3), và áp dụng cơ chế tổng quát **B0.5 Auto-unwrap** giúp điểm thi chính thức bứt phá ngoạn mục lên **`-0.01700`**.

```mermaid
flowchart LR
    A["Khởi điểm (V1)<br/>Score: -0.227<br/>(Lỗi dữ liệu & Retry crash)"] -->|Vòng 1: Ingestion & Bounded Retry| B["Nộp Test V2<br/>Score: -0.03100<br/>(Tăng +19.6%)"]
    B -->|Đối chiếu GT & Vòng 2| C["Thử nghiệm V3 trên Modal<br/>(Phát hiện bẫy 2048 CoT tokens -> Revert 32k/8k)"]
    C -->|Áp dụng B0.5 Auto-unwrap lên V2| D["Nộp Test V2 Unwrapped<br/>Score: -0.01700<br/>(Cắt giảm gần một nửa điểm phạt!)"]
```

---

## 2. HIỆN TRẠNG BAN ĐẦU (INITIAL STATE)

### 2.1. Cấu trúc Pipeline 5 Module

Pipeline hoạt động theo mô hình Module hoá từ B0.1 đến B0.5:

1. **B0.1 Ingestion & Discovery:** Đọc dữ liệu từ Excel/CSV, trích xuất cấu trúc bảng, kiểu dữ liệu và mối quan hệ JOIN ban đầu.
2. **B0.2 Semantic Layer & Rule Compilation:** Biên dịch business context, metadata ngành và luật nghiệp vụ (Rulebook) từ tài liệu markdown/PDF.
3. **B0.3 Text-to-SQL & Prompt Engineering:** Sinh câu truy vấn DuckDB SQL thông qua mô hình ngôn ngữ lớn (`Qwen/Qwen3.5-9B`) kết hợp cơ chế Bounded Retry.
4. **B0.4 SQL Execution Engine:** Thực thi câu lệnh SQL trên DuckDB trong môi trường an toàn và thu thập kết quả thô.
5. **B0.5 Output Formatter & Gate Validator:** Chuẩn hoá kết quả về đúng định dạng bài thi (`number`, `date`, `percent`, `string`, `list`, `table`, `unanswerable`) và kiểm tra tính hợp lệ.

### 2.2. Điểm nghẽn và nguyên nhân điểm số âm (`-0.227`)

Trong lần chạy thử nghiệm ban đầu, điểm số đạt mức **`-0.227`** (PA Points = `-227/1000`, đúng 257 câu, sai 484 câu, abstain 259 câu) do:

- **Nhiễu dòng tổng cộng (Excel Subtotals):** Các file Excel kế toán Việt Nam chứa các dòng "Tổng cộng", "Cộng", "Cộng tiền" ở giữa hoặc cuối bảng. Khi nạp vào DuckDB, các dòng này bị tính trùng vào phép `SUM()`, làm sai lệch 100% kết quả doanh thu.
- **Cơ chế Bounded Retry bị crash:** Khi mô hình LLM sinh ra JSON bị lỗi cú pháp hoặc lẫn Markdown văn xuôi, hàm fallback gọi Bounded Retry bị văng Exception do truyền thiếu các tham số bắt buộc (`question_id`, `attempt`, `error_code`). Thay vì được sửa sai, câu hỏi bị đánh rớt trực tiếp.
- **Thiếu quy tắc thời gian tiếng Việt:** Ký hiệu `T2`, `T3` trong ngôn ngữ kế toán Việt Nam là **Tháng 2, Tháng 3**, nhưng mô hình hiểu nhầm thành **Quý (Quarter)**; "Hôm nay", "Bữa nay" bị lọc thành dồn tích luỹ `<= as_of_date` thay vì đúng ngày.
- **Ràng buộc âm (Negative Constraints) bị bỏ lửng:** Khi dữ liệu thực sự không có cột nhóm hàng / danh mục, mô hình vẫn cố tình viết SQL phỏng đoán bằng `LIKE '%trà%'`, dẫn tới câu trả lời sai thay vì nhận diện `unanswerable`.

---

## 3. QUÁ TRÌNH CẢI TIẾN VÒNG 1 (ROUND 1 IMPROVEMENTS)

Trong giai đoạn này, bạn và tôi đã rà soát mã nguồn, vá các lỗi kiến trúc và thiết lập hạ tầng chạy song song trên **Modal Cloud GPU (NVIDIA A100 40GB)**.

### 3.1. Các thay đổi kỹ thuật chính (Commits: `29ef1d0`, `b8c778e`, `e682d6b`, `ff586ae`)

1. **B0.1: Làm sạch dữ liệu bảng & Chuẩn hoá văn bản**
   - Lọc bỏ triệt để các dòng subtotal/tổng kết cuối bảng (dòng có chữ "tổng", "tổng cộng", "cộng", giá trị trống chiếm đa số).
   - Chuẩn hoá Unicode NFC và xoá khoảng trắng thừa đầu/cuối cho toàn bộ chuỗi văn bản (`text_cleaner`).
2. **B0.2: Tinh chỉnh phân loại trường & Ngữ nghĩa**
   - Tự động nhận diện kiểu số học (`numeric kind`) cho các trường tiền tệ, doanh số trung bình.
   - Nạp đúng tệp quan hệ ngoại sinh `relationships.json` vào Data Foundation.
3. **B0.3: Khôi phục Bounded Retry & Tối ưu hoá System Prompt**
   - **Vá lỗi Bounded Retry:** Bổ sung `question_id`, `attempt`, `error_code` vào `RepairRequest` và `GateOutcome`, đảm bảo 100% câu hỏi bị lỗi SQL/JSON được đưa vào vòng sửa sai tự động (tối đa 2 lần).
   - **Quy tắc thời gian tiếng Việt:** `T{M}` luôn là Tháng M; `DATE(col) = DATE '{as_of_date}'` cho "hôm nay".
   - **Quy tắc tính tăng trưởng:** Ép buộc công thức `ROUND(((ky_nay - ky_truoc) / ky_truoc) * 100, 2)` với `answer_type = 'percent'`.
   - **Quy tắc khách hàng:** Bắt buộc loại trừ "khách lẻ", "kl", "khách vãng lai" khỏi danh sách Top khách hàng.
   - **Quy tắc đếm đơn hàng:** Bắt buộc dùng `COUNT(DISTINCT ma_don_hang)` trên bảng chi tiết dòng hàng.
   - **Ràng buộc âm:** Bắt buộc trả về `unanswerable` khi thiếu cột nhóm hàng / danh mục sản phẩm.
4. **Hạ tầng Modal GPU:**
   - Xây dựng script [`modal_run_b0.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/scripts/modal_run_b0.py) chạy vLLM trên A100 cho toàn bộ 1.000 câu hỏi.

---

## 4. KẾT QUẢ VÒNG 1 & ĐỐI CHIẾU GROUND TRUTH (DIAGNOSTIC INSIGHTS)

### 4.1. Điểm số nộp bài thực tế (V2)

- Điểm chính thức ghi nhận trên bảng xếp hạng: **`-0.03100`** (tăng vọt từ `-0.227`, cải thiện gần **+20% điểm số**).
- Điểm đối chiếu cục bộ với Ground Truth ([`public_test_GT.jsonl`](file:///home/trongkhoi/Downloads/public_test_GT.jsonl)): **`-0.037`** (đúng 409, sai 446, abstain 145).

### 4.2. Bóc tách 4 nguyên nhân gốc rễ gây mất điểm

```mermaid
pie title Phân bố các nguyên nhân gây mất điểm ở V2
    "Bẫy định dạng Table (Top-N & 1x1)" : 48
    "Thiếu nạp bảng calendar.csv" : 24
    "Hiểu nhầm 'tiệm mình' -> unanswerable" : 18
    "Định tính chủ quan (thợ nhiệt tình)" : 10
```

1. **Bẫy định dạng Table (Format Trap - Mất ~76 điểm):**
   - Có **38 câu hỏi** bị mô hình gán nhãn `answer_type="table"`.
   - Trong đó có **15 câu hỏi Top-N / Danh sách** (mô hình trích xuất đúng 100% danh sách nhưng do SELECT 2 cột nên B05 đóng gói thành `table` $\rightarrow$ bị phạt -1 điểm thay vì +1 điểm) và **14 câu hỏi Scalar $1 \times 1$**.
2. **Thiếu nạp bảng `calendar.csv` vào DuckDB:**
   - B0.1 chỉ hash file kiểm tra toàn vẹn chứ chưa tạo bảng vật lý `calendar` trong DuckDB, khiến các câu hỏi về Tết Nguyên Đán / ngày âm lịch bị đánh thành false `unanswerable`.
3. **Hiểu nhầm ngôn ngữ giao tiếp "Tiệm mình / Quán mình":**
   - Mô hình ngộ nhận phải có cột tên cửa hàng (`ten_tiem`, `ma_tiem`) để lọc nên kết luận `unanswerable`.
4. **Câu hỏi định tính không có trong Rulebook ("Thợ nhiệt tình nhất"):**
   - Dữ liệu không có thước đo độ nhiệt tình, nhưng mô hình lại tự tiện chọn thợ nhiều đơn nhất thay vì báo `unanswerable`.

---

## 5. ĐỢT CẢI TIẾN VÒNG 2 (ROUND 2 IMPROVEMENTS - TỔNG QUÁT HOÁ TOÀN DIỆN)

Tất cả các giải pháp trong Vòng 2 đều được thiết kế theo **nguyên lý tổng quát hoá (Zero Hardcoding)** để áp dụng cho mọi bộ dữ liệu mới (bao gồm Private Test):

1. **B0.5: Cơ chế Auto-unwrap Table & Dung sai cột ([`validators.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b05/validators.py))**
   - Tự động unwrap bảng $1 \times 1$ về đúng kiểu Scalar (`date`, `percent`, `number`, `string`) dựa trên regex và ngữ cảnh câu hỏi.
   - Tự động unwrap bảng 2 cột của câu hỏi Top-N / danh sách về `list` (trích xuất cột thực thể đầu tiên).
   - Chấp nhận kết quả $\ge 1$ cột cho scalar/list để tránh lỗi `SCALAR_SHAPE_MISMATCH`.
2. **B0.1: Nạp hoàn chỉnh bảng `calendar` vào DuckDB ([`preparation.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py))**
   - Tạo bảng `calendar` kèm trường `__dm_row_id` và đăng ký đầy đủ cột (`date`, `weekday`, `lunar_day`, `lunar_month`, `lunar_year`, `lunar_leap`, `holiday`) vào schema catalog.
3. **B0.3: Bổ sung chỉ dẫn nghiệp vụ vào Prompt ([`prompt.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py))**
   - Giải thích ngữ nghĩa "tiệm mình / quán mình / shop mình" = toàn bộ dữ liệu cửa hàng.
   - Hướng dẫn JOIN bảng `calendar` qua cột ngày cho các câu hỏi ngày lễ/Tết.
   - Quy tắc `unanswerable` cho các tiêu chí định tính cảm tính ("thợ nhiệt tình nhất").
   - Kiểm thử tự động đạt **249/249 unit & integration tests pass**. (Commit: `e8ba5e2`).

---

## 6. THỬ NGHIỆM MODAL V3 & BÀI HỌC VỀ REASONING TOKENS

Khi chạy thử nghiệm lần 3 (`public_test_v3`) trên Modal GPU với phần credit còn lại, để cố gắng rút ngắn thời gian GPU, cấu hình đã được chỉnh sang `max_model_len = 16384` và `max_new_tokens = 2048` (`batch_size = 32`).

- **Kết quả V3 trên Modal:** Hoàn thành 1.000 câu, nhưng ghi nhận **606 câu `abstain`** (PA Score = `-0.076`).
- **Phân tích nguyên nhân kỹ thuật:**
  - Mô hình `Qwen3.5-9B` khi bật `enable_thinking = true` thường tốn từ 1.500 – 2.500 tokens cho quá trình suy luận CoT trước khi viết khối ```json.
  - Khi giới hạn `max_new_tokens = 2048`, **745 lượt sinh bị cắt ngang giữa chừng khi đang suy nghĩ**, không kịp xuất JSON hợp lệ. Đồng thời, các context dài hơn 16k tokens bị vLLM từ chối (**305 lượt**).
- **Khắc phục ngay lập tức:** Đã khôi phục [`configs/qwen3_5_9b.toml`](file:///home/trongkhoi/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml) về ngưỡng an toàn tuyệt đối **`max_model_len = 32768`** và **`max_new_tokens = 8192`** (Commit `bdf515d`).

---

## 7. ÁP DỤNG B0.5 AUTO-UNWRAP LÊN V2 & KỶ LỤC MỚI `-0.01700`

Do lần chạy **V2** trước đó đã chạy đủ với `max_model_len = 32768` và `max_new_tokens = 8192` (lưu giữ trọn vẹn SQL và dữ liệu thực thi thô của toàn bộ 1.000 câu hỏi), chúng tôi đã đưa trực tiếp kết quả thực thi của V2 qua **bộ lọc B0.5 Auto-unwrap mới**.

### 7.1. Kết quả đối chiếu & Đóng gói

- **Số bảng được tự động giải nén (Unwrapped):** **18 câu hỏi** (chuyển từ `table` sai định dạng về `number`, `date`, `list` chính xác).
- **Kiểm định Ground Truth cục bộ:**
  - Số câu đúng tăng từ 409 $\rightarrow$ **415 câu**.
  - Số câu sai giảm từ 446 $\rightarrow$ **440 câu**.
  - Điểm PA cục bộ nhảy vọt từ `-0.037` $\rightarrow$ **`-0.025`** (**+12 điểm ròng**).
- **File nộp bài tối ưu:** [`artifacts/runs/public_test_v2/submission_v2_unwrapped.zip`](file:///home/trongkhoi/uit-last-dance-aizalo26/artifacts/runs/public_test_v2/submission_v2_unwrapped.zip).

### 7.2. Kết quả nộp bài chính thức trên hệ thống thi

- **ĐIỂM CHÍNH THỨC TRÊN SÀN:** **`-0.01700`**!
- So với đợt trước (`-0.03100`), điểm số đã được cải thiện thêm **+1.4% tuyệt đối**, cắt giảm gần **một nửa** lượng điểm phạt còn lại và tiến sát ngưỡng dương!

---

## 8. BẢNG TỔNG KẾT CÁC CỘT MỐC ĐIỂM SỐ

| Giai đoạn                      | Thay đổi cốt lõi                                                     |    Điểm GT Cục Bộ    | Điểm Nộp Hệ Thống |             Bước nhảy             |
| :------------------------------- | :----------------------------------------------------------------------- | :----------------------: | :--------------------: | :----------------------------------: |
| **Baseline (V1)**          | Pipeline thô, lỗi subtotal & crash retry                               |        `-0.227`        |      ~ `-0.22`      |                  —                  |
| **Vòng 1 (V2)**           | Khử subtotal, vá Bounded Retry, Time & Client Rules                    |        `-0.037`        | **`-0.03100`** |           **+19.6%**           |
| **Vòng 2 (V3 Test)**      | Test tăng tốc Modal (`max_new_tokens=2048` $\rightarrow$ cắt CoT) | `-0.076` *(abstain)* |   *(Không nộp)*   |           Bài học config           |
| **Vòng 2 (V2 Unwrapped)** | Áp dụng B0.5 Auto-unwrap (bóc tách Table $1 \times 1$ & Top-N)     |   **`-0.025`**   | **`-0.01700`** | **+1.4%** *(Giảm 45% lỗi)* |

---

## 9. ĐÁNH GIÁ SÂU KẾT QUẢ `-0.01700` & 5 LỖ HỔNG VỪA PHÁT HIỆN

Qua phân tích sâu từng doanh nghiệp và từng loại câu hỏi trên kết quả tốt nhất (`-0.025` cục bộ / `-0.01700` trên sàn):

- **8/14 doanh nghiệp đạt điểm dương rất tốt (`+147 điểm ròng`)**, tiêu biểu: `dev_002` (`+0.756`), `dev_007` (`+0.533`), `dev_005` (`+0.276`), `dev_010` (`+0.254`), `dev_008` (`+0.202`), `dev_006` (`+0.189`).
- **5 doanh nghiệp kéo mất `-165 điểm`** (`dev_003`: `-63`, `dev_004`: `-33`, `dev_014`: `-26`, `dev_013`: `-23`, `dev_001`: `-20`, cộng `dev_009`: `-7`) do 5 nguyên nhân hệ thống tổng quát vừa tìm ra trong mã nguồn:
  1. **Lỗi nhận diện `order_lines` ở B0.1:** `is_order_key` và `is_product` bỏ sót `"Đơn số"`, `"HĐ"`, `"Hàng hóa"`, `"Hàng bán"` $\rightarrow$ tắt hoàn toàn khử trùng dòng (gây sai lệch 123 dòng trùng tháng 10/2025 ở `dev_003`) và tắt `forward_fill` (các dòng chi tiết đơn hàng thiếu ngày/trạng thái ở `dev_004`, `dev_013`).
  2. **Dòng Subtotal không chứa chữ `"Tổng"` bị `forward_fill` làm nhiễu (`dev_001`):** Dòng tổng kết ngày chỉ có tiền và trống toàn bộ cột định danh bị `forward_fill` chép đè đơn hàng cuối ngày lên, làm doanh thu `dev_001` tăng gấp đôi (`281.47M` $\rightarrow$ `574.05M`).
  3. **Thiếu ánh xạ `_STATUS` & bẫy `NULL NOT IN`:** Thiếu `"khach tra"`, `"khong giao duoc"` trong `_STATUS`; đồng thời `LOWER(ghi_chu) NOT IN (...)` làm mất các dòng hợp lệ có `ghi_chu IS NULL`.
  4. **Sai khác cột nghiệp vụ & quy đổi đơn vị:** Dùng `tong_tien` thay vì `gia_tri_hang` ở `dev_009`; chưa nhân `1 bó = 10 cây` ở `dev_004`; nhân giá vốn với `sl_dv_co_ban` thay vì `s_l` ở `dev_003`.
  5. **Bộ vá Vòng 2 (`calendar`, `"tiệm mình"`) chưa được chạy lại trên GPU chuẩn `32k/8k`.**

**Bước tiếp theo để bứt phá lên vùng điểm dương cao (`+0.25` đến `+0.40+`):**

1. Vá tổng quát 4 lỗ hổng B0.1 / B0.3 mới phát hiện (`is_order_key`, `is_product`, lọc dòng subtotal không nhãn, `_STATUS` + `IS NULL OR ... NOT IN`).
2. Chạy lại toàn bộ pipeline ở cấu hình chuẩn `32k/8k` (đã tích hợp cả `calendar`, prompt mới và B0.5 Auto-unwrap).

---

## 10. DANH MỤC CÁC FILE & Ý NGHĨA TRONG QUÁ TRÌNH CẢI TIẾN

Bảng dưới đây tổng hợp toàn bộ các tệp mã nguồn, cấu hình, script vận hành, kiểm thử, tài liệu và kết quả tạo ra trên nhánh `improvement-b01-b02`:

### 10.1. Tầng B0.1 — Data Ingestion, Làm sạch & Schema / Join Catalog

| Đường dẫn File                                                                                                                                 | Ý nghĩa & Vai trò trong cải tiến                                                                                                                                                                                                                                |
| :------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`src/datamate/b0/b01/ingestion/preparation.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/preparation.py)     | Điều phối nạp dữ liệu nguồn (Excel/CSV/SQLite) vào DuckDB; khử dòng tổng cộng/footer, `forward_fill` theo nhóm đơn, khử dòng trùng xuất file (Rulebook §8), và nạp bảng vật lý `calendar` kèm `__dm_row_id`.                         |
| [`src/datamate/b0/b01/ingestion/normalization.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/normalization.py) | Chuẩn hoá số (`50tr`, `125k`, `500,000.0000`), ngày tiếng Việt (`dd/mm`, Excel serial, `thg`), trạng thái đơn `_STATUS`, chuẩn hoá whitespace văn bản và hàm nhận diện cột đơn hàng/hàng hoá (`is_order_key`, `is_product`). |
| [`src/datamate/b0/b01/ingestion/profiling.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/profiling.py)         | Sinh thống kê dữ liệu chính xác từ DuckDB (`null_count`, `cardinality`, `observed_min`/`observed_max`, mẫu dòng) làm ngữ cảnh cho B0.2 và B0.3.                                                                                                 |
| [`src/datamate/b0/b01/ingestion/relationships.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b01/ingestion/relationships.py) | Đọc và ánh xạ file `relationships/<biz>.json` (reviewed relationships) từ tên bảng/cột vật lý sang tên bảng/cột chuẩn hoá trong SQL.                                                                                                               |
| [`src/datamate/b0/b01/schema_catalog.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b01/schema_catalog.py)                   | Xây dựng `SchemaCatalog`: phát hiện khoá chính/ứng viên (`key_candidates`) và suy luận cạnh liên kết (`join_graph`) dựa trên bằng chứng dữ liệu toàn bảng.                                                                                |
| [`src/datamate/b0/b01/join_graph.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b01/join_graph.py)                           | Tìm đường đi JOIN hợp lệ và biên dịch điều kiện equijoin nhiều cột an toàn (tránh fanout sai).                                                                                                                                                      |
| [`src/datamate/b0/b01/relationship_evidence.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b01/relationship_evidence.py)     | Chính sách kiểm chứng mức độ tin cậy của mối quan hệ JOIN tách biệt với thống kê SQL.                                                                                                                                                                |
| [`src/datamate/b0/b01/metadata_adapter.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b01/metadata_adapter.py)               | Bộ chuyển đổi ranh giới JSON (`JSONMetadataProvider`, `FoundationMetadata`) giúp B0.1/B0.2 tách rời khỏi nguồn vật lý.                                                                                                                               |
| [`src/datamate/b0/b01/contracts.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b01/contracts.py)                             | Định nghĩa data contracts cho B0.1 (`TableMetadata`, `ColumnMetadata`, `JoinEdge`, `KeyCandidate`, `SchemaCatalog`).                                                                                                                                    |

### 10.2. Tầng B0.2 — Ngữ nghĩa Nghiệp vụ & Business Context

| Đường dẫn File                                                                                                                 | Ý nghĩa & Vai trò trong cải tiến                                                                                                            |
| :--------------------------------------------------------------------------------------------------------------------------------- | :----------------------------------------------------------------------------------------------------------------------------------------------- |
| [`src/datamate/b0/b02/context_service.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b02/context_service.py) | Dịch vụ `BusinessContextService` kết hợp B0.1 schema, profiling và luật từ Rulebook/README để tạo gói ngữ cảnh cho doanh nghiệp. |
| [`src/datamate/b0/b02/contracts.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b02/contracts.py)             | Định nghĩa hợp đồng `BusinessContext`, `RuleCatalog`, `BusinessRule` và kiểm tra tính nhất quán.                                |
| [`src/datamate/b0/b02/cli.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b02/cli.py)                         | Công cụ dòng lệnh dựng `business_context.json` từ metadata và tài liệu nghiệp vụ.                                                   |

### 10.3. Tầng B0.3 — Text-to-SQL, Prompt & Parser

| Đường dẫn File                                                                                               | Ý nghĩa & Vai trò trong cải tiến                                                                                                                                                                                                                                                  |
| :--------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`src/datamate/b0/b03/prompt.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b03/prompt.py) | Chứa `SYSTEM_INSTRUCTION` và hàm build prompt (`build_text2sql_messages`, `build_repair_messages`); bổ sung quy tắc thời gian tiếng Việt, `"tiệm mình"`, JOIN `calendar`, tiêu chí chủ quan `unanswerable`, và nhóm bảng phân vùng tránh tràn context. |
| [`src/datamate/b0/b03/parser.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b03/parser.py) | Giải mã output của LLM (`<think>`, khối JSON/SQL), kiểm tra cú pháp bằng `sqlglot`, hỗ trợ trích xuất fallback cho vòng retry.                                                                                                                                        |
| [`src/datamate/b0/b03/types.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b03/types.py)   | Khai báo các kiểu dữ liệu chuẩn của B0.3 (`ChatMessage`, `GenerationResult`, `ParsedSQL`...).                                                                                                                                                                             |

### 10.4. Tầng B0.5 & Điều phối Pipeline

| Đường dẫn File                                                                                                       | Ý nghĩa & Vai trò trong cải tiến                                                                                                                                                                                                                                               |
| :----------------------------------------------------------------------------------------------------------------------- | :---------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`src/datamate/b0/b05/validators.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/b05/validators.py) | Cổng thẩm định `validate_execution`: kiểm tra hình dạng kết quả (`scalar`, `list`, `table`), **Auto-unwrap bảng $1 \times 1$ về Scalar** và **bảng 2 cột Top-N về `list`**, giúp tăng điểm từ `-0.03100` lên **`-0.01700`**. |
| [`src/datamate/b0/pipeline.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/src/datamate/b0/pipeline.py)             | `B0Pipeline` điều phối end-to-end B0.1 $\rightarrow$ B0.5; sửa lỗi truyền `question_id`, `attempt`, `error_code` vào `RepairRequest`/`GateOutcome` để kích hoạt thành công Bounded Retry khi parse JSON lỗi.                                            |

### 10.5. Script Vận hành, Modal GPU & Cấu hình

| Đường dẫn File                                                                                                       | Ý nghĩa & Vai trò trong cải tiến                                                                                                                                                 |
| :----------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------ |
| [`scripts/modal_run_b0.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/scripts/modal_run_b0.py)                     | Runner chạy toàn pipeline trên Modal Serverless GPU (A100 40GB), cache weights Qwen3.5-9B và bundles trên Modal Volume, tự động nén và tải kết quả về máy local.       |
| [`scripts/run_b0_pipeline.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/scripts/run_b0_pipeline.py)               | CLI chạy inference B0.1–B0.5 (hỗ trợ lọc `business_id`, `limit`, `relationships`), ghi log chi tiết và tính điểm đánh giá Ground Truth (`evaluate_predictions`). |
| [`configs/qwen3_5_9b.toml`](file:///home/trongkhoi/uit-last-dance-aizalo26/configs/qwen3_5_9b.toml)                     | Cấu hình vLLM cho `Qwen3.5-9B` (`max_model_len=32768`, `max_new_tokens=8192`, `enable_thinking=true`, `temperature=0.0`).                                                 |
| [`scripts/audit_prepared_bundles.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/scripts/audit_prepared_bundles.py) | Script kiểm toán các bundle đã chuẩn hoá ở B0.1/B0.2 đối chiếu với `normalization_report` và `lineage`.                                                              |
| [`scripts/demo_join_graph.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/scripts/demo_join_graph.py)               | Script demo kiểm tra đường đi JOIN trên DuckDB từ contract JSON đã chuẩn hoá.                                                                                              |

### 10.6. Tài liệu, Ví dụ & Bộ Kiểm thử (`docs/`, `examples/`, `tests/`)

| Đường dẫn File                                                                                                                                                                                                                                                                                                                                                                             | Ý nghĩa & Vai trò trong cải tiến                                                                                           |
| :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :------------------------------------------------------------------------------------------------------------------------------ |
| [`docs/IMPROVEMENT_JOURNEY.md`](file:///home/trongkhoi/uit-last-dance-aizalo26/docs/IMPROVEMENT_JOURNEY.md)                                                                                                                                                                                                                                                                                   | Tài liệu chính ghi lại toàn bộ lịch sử cải tiến, kết quả từng vòng, đối chiếu Ground Truth và danh mục file. |
| [`docs/B01_JOIN_IMPROVEMENT_REPORT.md`](file:///home/trongkhoi/uit-last-dance-aizalo26/docs/B01_JOIN_IMPROVEMENT_REPORT.md)                                                                                                                                                                                                                                                                   | Báo cáo chi tiết Phase 0–5 cải tiến phát hiện khoá và JOIN graph ở B0.1/B0.2.                                        |
| [`docs/architecture/b0/B01_B02_HANDOFF.md`](file:///home/trongkhoi/uit-last-dance-aizalo26/docs/architecture/b0/B01_B02_HANDOFF.md) & [`DATA_CONTRACT.md`](file:///home/trongkhoi/uit-last-dance-aizalo26/docs/architecture/b0/DATA_CONTRACT.md)                                                                                                                                             | Đặc tả giao tiếp và Data Contract giữa B0.1, B0.2 và các module downstream.                                             |
| [`examples/relationships/biz_123.json`](file:///home/trongkhoi/uit-last-dance-aizalo26/examples/relationships/biz_123.json) & [`examples/foundation_metadata.json`](file:///home/trongkhoi/uit-last-dance-aizalo26/examples/foundation_metadata.json)                                                                                                                                        | Dữ liệu mẫu minh hoạ file khai báo quan hệ (`reviewed relationships`) và `FoundationMetadata`.                       |
| [`tests/test_validator.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/tests/test_validator.py)                                                                                                                                                                                                                                                                                           | Kiểm thử đơn vị cho B0.5 Gate Validator, bao gồm test mới cho Auto-unwrap bảng $1 \times 1$ và bảng 2 cột Top-N.   |
| [`tests/test_b03_text2sql.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/tests/test_b03_text2sql.py)                                                                                                                                                                                                                                                                                     | Bộ kiểm thử toàn diện cho B0.3 (prompt builder, parser, generator, retry).                                                 |
| [`tests/test_join_improvements.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/tests/test_join_improvements.py), [`tests/test_downstream_join_graph.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/tests/test_downstream_join_graph.py), [`tests/test_business_context_integration.py`](file:///home/trongkhoi/uit-last-dance-aizalo26/tests/test_business_context_integration.py) | Bộ kiểm thử hồi quy cho B0.1/B0.2 về discovery toàn bảng, suy luận JOIN graph trên DuckDB và tích hợp rule/formula. |

### 10.7. Kết quả Chạy & File Nộp bài (`artifacts/runs/`)

| Thư mục / Tệp Artifact                                                                                                                                                | Ý nghĩa & Kết quả ghi nhận                                                                                                                                                                                  |
| :----------------------------------------------------------------------------------------------------------------------------------------------------------------------- | :--------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------------- |
| [`artifacts/runs/public_test_submission/`](file:///home/trongkhoi/uit-last-dance-aizalo26/artifacts/runs/public_test_submission/)                                       | Kết quả chạy full Public Test V1 trên Modal GPU: **GT `-0.227`** (`submission.jsonl`, `detailed_logs.jsonl`, `eval_report_gt.json`).                                                           |
| [`artifacts/runs/public_test_v2/submission.zip`](file:///home/trongkhoi/uit-last-dance-aizalo26/artifacts/runs/public_test_v2/submission.zip)                           | Kết quả chạy full Public Test V2 sau vá Bounded Retry & Prompt V1: **GT `-0.037`** \| **Điểm nộp sàn: `-0.03100`**.                                                                      |
| [`artifacts/runs/public_test_v2/submission_v2_unwrapped.zip`](file:///home/trongkhoi/uit-last-dance-aizalo26/artifacts/runs/public_test_v2/submission_v2_unwrapped.zip) | Bản nộp áp dụng bộ lọc B0.5 Auto-unwrap lên dữ liệu V2: **GT `-0.025`** \| **Điểm nộp sàn kỷ lục: `-0.01700`**.                                                                   |
| [`artifacts/runs/public_test_v3/`](file:///home/trongkhoi/uit-last-dance-aizalo26/artifacts/runs/public_test_v3/)                                                       | Lần thử tối ưu tốc độ trên Modal (`max_new_tokens=2048`) ghi nhận **606 `abstain`** do cắt ngang quá trình CoT (`GT -0.076`), dẫn tới quyết định khôi phục cấu hình `32k/8k`. |
