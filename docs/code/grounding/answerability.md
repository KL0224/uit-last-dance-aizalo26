# Giải Thích Mã Nguồn: `answerability.py`

**Đường dẫn file:** [`src/datamate/grounding/answerability.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/answerability.py)  
**Thuộc module:** Component C — Question Grounding (C5 Answerability Precheck)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `answerability.py` triển khai lớp `AnswerabilityPrechecker` (module con **C5**).

Trong cơ chế tính điểm của cuộc thi **Zalo AI Challenge 2026**:
$$\text{Penalized Accuracy (PA)} = \frac{\text{Số câu đúng} - \text{Số câu sai}}{\text{Tổng số câu}}$$
* **Trả lời đúng**: Được cộng **+1 điểm**.
* **Bỏ qua (Abstain)**: Được **0 điểm**.
* **Trả lời sai**: Bị trừ **-1 điểm**.

Một cái bẫy rất lớn trong đề thi là **những câu hỏi không thể trả lời được do thiếu dữ liệu (Unanswerable Questions)** — chiếm khoảng 2.33% tập train và xuất hiện xuyên suốt trong public test:
* Ví dụ: Doanh nghiệp chỉ có máy POS bán lẻ tại quầy, không lưu danh tính khách hàng, nhưng câu hỏi lại hỏi: *"Khách hàng nào mua nhiều tiền nhất trong tháng?"*.
* Nếu không có bộ kiểm tra khả năng trả lời sớm, LLM 9B sẽ cố gắng "bịa" ra câu lệnh SQL để truy vấn trên một bảng không phù hợp, dẫn đến câu trả lời bị sai và **bị phạt -1 điểm**.
* Ngược lại, nếu hệ thống kết luận thiếu dữ liệu quá vội vàng khi thông tin thực ra có thể suy luận qua bảng khác (ví dụ: món ăn có size được gộp trong cột tên món), hệ thống sẽ dính lỗi **False Positive Unanswerable** và mất đi điểm số của câu đúng (+1 điểm).

Module C5 đóng vai trò là **Lá chắn rủi ro PA ở đầu nguồn (Early Answerability Risk Gate)**: Kiểm tra đối chiếu yêu cầu bằng chứng với ma trận năng lực `CapabilityMatrix` và toàn bộ cơ sở dữ liệu để đưa ra quyết định chuẩn xác.

---

## 2. Chi Tiết Các Hằng Số & Phương Thức

### 2.1. `_CAPABILITY_CONCEPT_KEYWORDS`
Từ điển tra cứu từ khóa phục vụ cơ chế kiểm tra cột thay thế (Fallback Column Search):
```python
{
    "customers": ("customer_id", "customer_name", "khách hàng", "người mua", "mã khách"),
    "cost": ("cost", "gia_von", "giá vốn", "chi phí", "chi_phi"),
    "historical_stock": ("ton_kho_lich_su", "historical_stock", "tồn đầu kỳ", "tồn cuối kỳ"),
    "payments": ("payment", "collected_amount", "payment_method", "thực thu", "thanh toán"),
    "sales_by_product": ("product_id", "product_name", "tên món", "sản phẩm", "mặt hàng"),
    "expiry": ("expiry_date", "han_su_dung", "hạn sử dụng", "ngày hết hạn"),
    "warranties": ("warranty", "bao_hanh", "bảo hành"),
}
```

---

### 2.2. Phương Thức `build_requirements(...)`

```python
def build_requirements(
    self,
    question: str,
    intent: QuestionIntent,
) -> tuple[EvidenceRequirement, ...]:
```
* **Mục đích**: Suy luận danh sách các năng lực dữ liệu bắt buộc (`EvidenceRequirement`) dựa trên ý định câu hỏi:
  * Gom nhóm theo khách hàng (`intent.group_by == ("customer",)`) hoặc hỏi *"khách hàng nào"* $\rightarrow$ Bắt buộc cần năng lực `"customers"`.
  * Tính giá vốn, chi phí, hoặc lợi nhuận gộp (`gross_profit = revenue - cost`) $\rightarrow$ Bắt buộc cần năng lực `"cost"`.
  * Hỏi về tồn kho lịch sử tại ngày cụ thể $\rightarrow$ Bắt buộc cần năng lực `"historical_stock"`.
  * Hỏi về tiền mặt thực thu theo ca $\rightarrow$ Bắt buộc cần năng lực `"payments"`.
  * Gom nhóm theo sản phẩm hoặc hỏi món bán chạy $\rightarrow$ Bắt buộc cần năng lực `"sales_by_product"`.
  * Hỏi về hạn dùng / bảo hành $\rightarrow$ Bắt buộc cần năng lực `"expiry"` / `"warranties"`.

---

### 2.3. Phương Thức Phòng Thủ `_has_fallback_column_in_catalog(...)`

```python
def _has_fallback_column_in_catalog(
    self,
    capability_key: str,
    context: BusinessContextProtocol,
) -> bool:
```
* **Cơ chế chống bắt nhầm unanswerable (Anti-False-UA Defense)**:
  * Đôi khi `CapabilityMatrix` của doanh nghiệp đánh dấu `"customers": "unsupported"` (vì không có bảng khách hàng riêng), nhưng trong bảng đơn hàng lại có cột `ten_nguoi_mua`.
  * Hàm này quét qua toàn bộ các bảng trong `context.get_tables()`, duyệt qua tên cột, mô tả cột và alias của từng cột để xem có chứa từ khóa liên quan đến năng lực đang xét hay không.
  * Nếu tìm thấy cột thay thế, hàm trả về `True` $\rightarrow$ Ngăn chặn việc vội vã kết luận `UNSUPPORTED`.

---

### 2.4. Phương Thức `evaluate(...)`

```python
def evaluate(
    self,
    question: str,
    intent: QuestionIntent,
    resolved_time_ranges: Sequence[ResolvedTimeRange],
    selected_schema: SelectedSchema,
    context: BusinessContextProtocol,
) -> tuple[
    tuple[EvidenceRequirement, ...],
    CoverageStatus,
    MissingEvidenceProof | None,
    tuple[str, ...],
]:
```

#### Quy Trình Đánh Giá 3 Bước:
1. **Bước 1: Kiểm tra rỗng (Empty Schema Check)**:
   * Nếu doanh nghiệp không có bất kỳ bảng dữ liệu nào, lập tức trả về `CoverageStatus.UNSUPPORTED` với lý do *"Doanh nghiệp không có bảng dữ liệu nào trong catalog"*.
2. **Bước 2: Đối chiếu ma trận năng lực (`CapabilityMatrix`)**:
   * Duyệt qua từng yêu cầu `EvidenceRequirement`:
     * Lấy trạng thái năng lực từ `context.get_capability_status(req.capability_key)`.
     * **Trường hợp UNSUPPORTED thực sự**: Nếu năng lực là `"unsupported"` VÀ là bắt buộc (`is_mandatory=True`) VÀ `_has_fallback_column_in_catalog()` xác nhận không có bất kỳ cột thay thế nào trên toàn bộ doanh nghiệp:
       * Tạo đối tượng `MissingEvidenceProof` ghi rõ danh sách trường thiếu và danh sách 100% các bảng đã rà soát (`checked_all_sources=True`).
       * Trả về ngay lập tức: `CoverageStatus.UNSUPPORTED`.
     * **Trường hợp UNKNOWN**: Nếu năng lực là `"unknown"` và không tìm thấy cột thay thế trực tiếp, hệ thống đánh dấu trạng thái nghi ngờ (`has_unknown = True`) và gắn cờ `risk_flags.append(f"UNCERTAIN_CAPABILITY:{req.capability_key}")`.
3. **Bước 3: Kiểm tra độ phủ thời gian (Temporal Coverage Check)**:
   * Nếu bảng chính `primary_table` có thông tin khoảng ngày bắt đầu và kết thúc (`date_coverage_start`, `date_coverage_end`):
   * So sánh với khoảng ngày được hỏi (`resolved_time_ranges`).
   * Nếu câu hỏi hỏi ngoài khoảng thời gian bảng bao phủ, gắn cờ `TEMPORAL_OUT_OF_RANGE` và chuyển `CoverageStatus.UNKNOWN` để cảnh báo rủi ro cho tầng quyết định.
4. **Kết quả**: Trả về `CoverageStatus.SUPPORTED` nếu mọi điều kiện đều an toàn.

---

## 3. Tại Sao Lại Thiết Kế & Code Như Vậy?

1. **Tuân thủ quy chuẩn bằng chứng độc lập của Output Gate (B0.5)**:
   * Output Gate B0.5 quy định: Một câu hỏi chỉ được xuất ra `unanswerable` khi có bằng chứng độc lập `EvidenceProof(source_kind="catalog_verified", checked_all_sources=True)`. C5 được thiết kế để xuất ra đúng cấu trúc bằng chứng này, giúp B0.5 không bị hạ cấp nhầm sang `abstain`.
2. **Tiết kiệm 100% chi phí tính toán cho các câu hỏi thiếu dữ liệu**:
   * Khi C5 phát hiện `UNSUPPORTED`, toàn bộ khâu sinh SQL của LLM 9B (Planner) và khâu chạy truy vấn của DuckDB (Executor) được bỏ qua hoàn toàn. Pipeline nhảy thẳng tới B0.5 để đóng gói kết quả, giúp tiết kiệm thời gian chạy đáng kể.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Tích hợp với `engine.py`**: Engine đọc `coverage_status` từ C5. Nếu là `UNSUPPORTED`, nó tự động đổi `answer_type_hint` thành `AnswerTypeHint.UNANSWERABLE`.
* **Tích hợp với `adapters.py`**: Adapter sử dụng `MissingEvidenceProof` từ C5 để tạo đối tượng `EvidenceProof` tương thích 100% với B0.5 Gatekeeper.

---

## 5. Nếu Không Có File Này Thì Sao?

* Hệ thống sẽ liên tục bị **trừ 1 điểm (Penalized Accuracy)** ở các câu hỏi thiếu dữ liệu do LLM 9B tự ý suy diễn hoặc sinh ra câu lệnh SQL sai.
* Hoặc nếu dựa vào suy luận cảm tính của LLM để báo `unanswerable`, hệ thống sẽ bị dính bẫy False Unanswerable ở các câu hỏi về size/topping bán cấu trúc, làm mất điểm oan uổng ở những câu hoàn toàn có thể tính được.
