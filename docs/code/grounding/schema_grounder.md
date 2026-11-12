# Giải Thích Mã Nguồn: `schema_grounder.py`

**Đường dẫn file:** [`src/datamate/grounding/schema_grounder.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/schema_grounder.py)  
**Thuộc module:** Component C — Question Grounding (C3 Schema Grounder)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `schema_grounder.py` triển khai lớp `SchemaGrounder` (module con **C3**).

Trong các hệ thống Text-to-SQL truyền thống, việc nhồi nhét toàn bộ lược đồ (toàn bộ các bảng, các cột và quan hệ) vào prompt của LLM gây ra 3 vấn đề lớn:
1. **Quá tải ngữ cảnh (Context Bloat)**: Tốn hàng nghìn token không cần thiết, làm tăng chi phí và thời gian suy luận.
2. **Ảo giác lược đồ (Schema Hallucination)**: LLM dễ chọn nhầm các cột có tên tương tự nhau ở các bảng khác nhau (ví dụ: cột `tong_tien` ở bảng đơn hàng vs bảng chi tiết dòng hàng vs bảng thu tiền).
3. **Lỗi nhân dòng doanh thu (Join Fanout Risk)**: Khi kết nối bảng 1 dòng với bảng nhiều dòng (ví dụ `orders` nối sang `order_items`), nếu không cẩn thận phép `JOIN` trực tiếp sẽ nhân bản số tiền của bill lên nhiều lần.

Module C3 đóng vai trò là **Bộ chọn lọc lược đồ thông minh (Schema Linker & Join Path Finder)**:
* Phân tích câu hỏi và ý định (C1) để xếp hạng và chọn ra duy nhất **1 bảng Fact Table trọng tâm** cùng 1–3 bảng phụ cần thiết.
* Lọc bỏ các cột rác, chỉ giữ lại các cột thực sự liên quan.
* Tìm kiếm đường nối ngắn nhất trên đồ thị `JoinGraph` bằng thuật toán BFS và cảnh báo nguy cơ nhân dòng.

---

## 2. Chi Tiết Các Thuật Toán & Phương Thức

### 2.1. Thuật Toán Tìm Đường Nối Ngắn Nhất Bằng BFS (`_find_shortest_join_path`)

```python
def _find_shortest_join_path(
    self,
    start_table: str,
    target_table: str,
    edges: list[JoinSpec],
) -> list[JoinSpec]:
```
* **Mục đích**: Tìm chuỗi các bước JOIN tối ưu kết nối từ bảng chính (`primary_table`) đến bảng phụ mục tiêu (`target_table`).
* **Thuật toán**:
  * Sử dụng **Tìm kiếm theo chiều rộng (Breadth-First Search - BFS)** với hàng đợi `deque` và tập `visited` chống lặp vô tận.
  * Hỗ trợ duyệt cạnh theo cả hai chiều:
    * Chiều thuận (`left -> right`): Giữ nguyên thông tin cạnh `JoinSpec`.
    * Chiều nghịch (`right -> left`): Tự động đảo vị trí `left_table/column` và `right_table/column`, đồng thời **đảo ngược từng cặp khóa trong `additional_key_pairs`** `(right_col, left_col)`, và **đảo ngược lực lượng quan hệ**: nếu chiều thuận là `many_to_one` (an toàn) thì chiều nghịch là `one_to_many` (có nguy cơ nhân dòng $\rightarrow$ bật `fanout_warning=True`).
  * Trả về danh sách các cạnh `JoinSpec` tạo thành đường đi ngắn nhất giữa hai bảng.

---

### 2.2. Thuật Toán Chọn Lọc Cột Liên Quan (`_select_relevant_columns`)

```python
def _select_relevant_columns(
    self,
    table: TableSpec,
    q_norm: str,
    intent: QuestionIntent,
    required_metric_cols: set[str],
    join_cols: set[str],
) -> tuple[str, ...]:
```
* **Mục đích**: Loại bỏ các cột thừa trong bảng (ví dụ các cột ghi chú, cột hệ thống không liên quan), chỉ giữ lại các cột thiết yếu.
* **Quy tắc chọn cột**:
  1. Các cột bắt buộc của metric trong `MetricRegistry` (ví dụ `line_revenue`, `quantity`).
  2. Các cột là khóa JOIN trên đường nối (`join_cols`).
  3. Các cột mang vai trò quan trọng (`role` thuộc `id`, `date`, `money`, `quantity`, `name`, `category`).
  4. Các cột có tên hoặc alias xuất hiện trong câu hỏi.
  5. Các cột có chứa giá trị mẫu (`sample_values`) trùng khớp với thực thể được hỏi (được C4 đối chiếu).

---

### 2.3. Phương Thức Điều Phối `ground(...)`

```python
def ground(
    self,
    question: str,
    intent: QuestionIntent,
    context: BusinessContextProtocol,
) -> SelectedSchema:
```

#### Quy Trình Chấm Điểm & Xếp Hạng Bảng (Scoring Strategy):
Hệ thống chấm điểm đa tiêu chí cho từng bảng trong doanh nghiệp:
1. **Tiêu chí Metric Registry (Trọng số cao nhất: +0.85 điểm)**:
   * Nếu bảng là `preferred_table` của chỉ số mục tiêu trong `intent.target_metrics` (ví dụ câu hỏi hỏi `revenue` $\rightarrow$ bảng `order_items`; câu hỏi hỏi `cash_collected` $\rightarrow$ bảng `shift_payments`), bảng đó được cộng điểm áp đảo.
   * **Nguyên tắc thiết kế**: Bảng sự kiện (Fact Table) luôn phải là bảng chính để thực hiện phép tính tổng hợp (`SUM`, `AVG`), không được chọn nhầm sang bảng danh mục.
2. **Tiêu chí Gom Nhóm (`group_by`: +0.35 đến +0.45 điểm)**:
   * Nếu câu hỏi gom nhóm theo khách hàng (`intent.group_by == ("customer",)`), bảng `customers` được cộng điểm.
   * Nếu gom nhóm theo sản phẩm, bảng chứa tên sản phẩm được cộng điểm.
3. **Tiêu chí Điều Kiện Lọc Thực Thể (+0.30 điểm)**:
   * Nếu bảng chứa cột lưu trữ giá trị alias (ví dụ bảng `shift_payments` chứa cột `shift_name`), bảng đó được cộng điểm.
4. **Tiêu chí Khớp Từ Vựng & Giá Trị Mẫu (+0.15 đến +0.35 điểm)**:
   * Tên bảng hoặc alias của bảng xuất hiện trực tiếp trong câu hỏi (+0.25).
   * Giá trị mẫu (`sample_values`) của cột trong bảng xuất hiện trong câu hỏi (+0.35 điểm) giúp định vị ngay bảng dữ liệu nghiệp vụ thực tế.

#### Lựa Chọn Bảng & Kết Nối Đồ Thị:
1. Chọn bảng có điểm cao nhất làm `primary_table`.
2. Chọn các bảng phụ có `score >= 0.35` (tối đa `top_k_tables = 4` bảng).
3. Chạy thuật toán BFS kết nối `primary_table` với từng bảng phụ. Mọi bảng trung gian trên đường đi (nếu chưa có) sẽ được tự động bổ sung vào `SelectedSchema`, và toàn bộ các cột thuộc `key_pairs` đều được nạp vào `relevant_columns`.
4. Nếu bất kỳ cạnh nào trên đường nối có cờ `fanout_warning=True` hoặc `null_key_warning=True`, hệ thống bổ sung cảnh báo rõ ràng vào `warnings` (cảnh báo nhân dòng và cảnh báo mất dòng do NULL key).

---

## 3. Tại Sao Lại Thiết Kế & Code Như Vậy?

1. **Khắc phục triệt để lỗi Fanout 1-N**:
   * Khi nối `orders` (1 dòng/đơn) sang `order_items` (nhiều dòng/đơn), nếu câu lệnh SQL viết `SELECT SUM(orders.total_amount) FROM orders JOIN order_items...` thì doanh thu sẽ bị nhân lên gấp nhiều lần số món hàng trong đơn. C3 phát hiện cạnh này và cảnh báo thẳng cho Planner biết để thực hiện aggregate trước khi join.
2. **Ưu tiên Fact Table tuyệt đối (+0.85 điểm)**:
   * Trong bài toán *"Khách hàng nào mua nhiều tiền nhất"*, cả bảng `order_items` (chứa tiền) và bảng `customers` (chứa tên khách) đều liên quan. Nếu cho điểm ngang nhau, thuật toán có thể chọn nhầm `customers` làm bảng chính và cố tính tổng tiền trên bảng khách hàng $\rightarrow$ lỗi. Điểm ưu tiên +0.85 đảm bảo `order_items` luôn là bảng chính.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Cung cấp dữ liệu cho C4 Value Grounder**: C4 ưu tiên tìm kiếm giá trị thực tế trong các bảng đã được C3 chọn lọc trước, giúp tăng tốc độ so khớp.
* **Cung cấp dữ liệu cho Agent Planner (B0.3)**: Thay vì prompt chứa 10–20 bảng, prompt gửi cho LLM 9B chỉ chứa đúng các bảng và cột được liệt kê trong `SelectedSchema`, kèm gợi ý rõ ràng: `orders.order_id = order_items.order_id`.

---

## 5. Nếu Không Có File Này Thì Sao?

* LLM 9B sẽ phải tự đọc toàn bộ danh sách bảng trong database. Với các doanh nghiệp có nhiều bảng tương đồng (ví dụ `HoaDon`, `ChiTietHoaDon`, `HoaDonTamTinh`, `BaoCaoDoanhThuNgay`), LLM sẽ thường xuyên chọn nhầm bảng hoặc join thiếu bảng trung gian dẫn đến lỗi `Binder Error` hoặc kết quả sai hoàn toàn.
