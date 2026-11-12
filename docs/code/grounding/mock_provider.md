# Giải Thích Mã Nguồn: `mock_provider.py`

**Đường dẫn file:** [`src/datamate/grounding/mock_provider.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/mock_provider.py)  
**Thuộc module:** Component C — Question Grounding (Mock Business Context Provider)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `mock_provider.py` cung cấp lớp thực thi trong bộ nhớ `InMemoryBusinessContext` và nhà máy dữ liệu mẫu `MockBusinessContextProvider`. 

Nhiệm vụ cốt lõi của file này là:
1. **Giải phóng sự phụ thuộc vào I/O đĩa cứng và dữ liệu thật**: Cung cấp môi trường dữ liệu chuẩn ngữ nghĩa trong RAM, cho phép kiểm thử toàn bộ 5 module con (C1..C5) với tốc độ microsecond.
2. **Tái hiện chính xác các bài toán và bẫy nghiệp vụ thực tế của Zalo AI Challenge 2026**:
   * Phân biệt giữa **doanh thu đặt hàng (`revenue`)** và **tiền mặt thực thu theo ca (`cash_collected`)** (tương tự bài toán `dev_003`).
   * Phân biệt giữa sản phẩm **"được ưa chuộng nhất" (`distinct_product_orders` - COUNT DISTINCT)** và **"bán chạy nhất" (`sold_qty` - SUM quantity)**.
   * Xử lý tên sản phẩm bán cấu trúc có gộp size/topping như `"Cà phê sữa (L)"`, `"Trà sữa trân châu (L) + Kem cheese"` (tương tự bài toán `dev_002`).
   * Kiểm thử kịch bản thiếu bằng chứng khách hàng/giá vốn để xác minh tính năng chống phạt điểm PA của C5 Answerability Precheck.

---

## 2. Chi Tiết Các Class & Phương Thức

### 2.1. `InMemoryBusinessContext(BusinessContextProtocol)`
Là lớp triển khai cụ thể của `BusinessContextProtocol` lưu trữ hoàn toàn trên RAM:
* Thuộc tính:
  * `business_id: str`: Mã định danh doanh nghiệp.
  * `tables: tuple[TableSpec, ...]`: Danh sách bảng và cột.
  * `join_edges: tuple[JoinSpec, ...]`: Danh sách cạnh đồ thị join.
  * `metrics: tuple[MetricSpec, ...]`: Danh mục chỉ số nghiệp vụ.
  * `capabilities: dict[str, str]`: Bảng tra cứu trạng thái năng lực (`"supported"`, `"unsupported"`, `"unknown"`).
  * `calendar_events: tuple[CalendarEventSpec, ...]`: Danh sách sự kiện lịch/ngày lễ.
  * `rules: tuple[str, ...]`: Danh sách quy tắc nghiệp vụ dạng văn bản.
  * `value_aliases: dict[str, tuple[str, str, Any]]`: Từ điển ánh xạ cụm từ viết tắt.
* Triển khai đầy đủ 8 phương thức của `BusinessContextProtocol` với độ phức tạp truy xuất $O(1)$ hoặc $O(N)$ nhỏ.

---

### 2.2. `MockBusinessContextProvider` (Nhà Máy Dữ Liệu Ngữ Cảnh)

#### `create_fnb_context(business_id: str = "mock_fnb_003") -> InMemoryBusinessContext`
Mô phỏng toàn diện chuỗi cửa hàng đồ uống/F&B:
* **4 Bảng Dữ Liệu**:
  1. `orders` (grain = `order`): Chứa `order_id`, `order_date`, `customer_id`, `status` (`"Hoàn thành"`, `"Đã hủy"`), `total_amount`.
  2. `order_items` (grain = `order_item`): Chứa `order_id`, `product_id`, `product_name` (chứa các giá trị mẫu thực tế như `"Cà phê sữa (L)"`, `"Trà sữa trân châu (L) + Kem cheese"`), `quantity`, `line_revenue`, `order_date`.
  3. `shift_payments` (grain = `payment_event`): Chứa `payment_id`, `order_id`, `payment_date`, `shift_name` (`"Ca sáng"`, `"Ca tối"`), `payment_method` (`"Tiền mặt"`, `"Chuyển khoản"`, `"Ví MoMo"`), `collected_amount`.
  4. `customers` (grain = `customer`): Chứa `customer_id`, `customer_name` (`"Nguyễn Văn An"`, `"Trần Thị Bình"`).
* **Đồ Thị Nối Bảng (Join Graph)**:
  * `order_items -> orders` (many_to_one, an toàn).
  * `orders -> order_items` (one_to_many, có cờ `fanout_warning=True` để kiểm tra khả năng cảnh báo nhân dòng của C3).
  * `orders -> customers` (many_to_one, an toàn).
  * `shift_payments -> orders` (many_to_one, an toàn).
* **Semantic Metric Registry**:
  * `revenue`: Ưu tiên bảng `order_items`, cột `line_revenue`, theo `order_date`.
  * `cash_collected`: Bắt buộc bảng `shift_payments`, cột `collected_amount`, theo `payment_date`.
  * `order_count`: Đếm `COUNT(DISTINCT orders.order_id)`.
  * `distinct_product_orders`: Đếm `COUNT(DISTINCT order_items.order_id)` gom nhóm theo `product_name`.
  * `sold_qty`: Tính `SUM(order_items.quantity)` gom nhóm theo `product_name`.
* **Capability Matrix**:
  * `supported`: `sales_by_product`, `customers`, `payments`, `shifts`.
  * `unsupported`: `cost`, `historical_stock`, `expiry`, `warranties`.
* **Calendar Events**:
  * `tet_2026`: từ `2026-02-14` đến `2026-02-22`.
  * `tet_2025`: từ `2025-01-25` đến `2025-02-02`.
* **Value Aliases**:
  * Ánh xạ các từ lóng/viết tắt: `"ck"` $\rightarrow$ `"Chuyển khoản"`, `"momo"` $\rightarrow$ `"Ví MoMo"`, `"ca tối"` $\rightarrow$ `("shift_payments", "shift_name", "Ca tối")`.

#### `create_anonymous_retail_context(business_id: str = "mock_retail_anon") -> InMemoryBusinessContext`
Mô phỏng cửa hàng bán lẻ nhỏ chỉ có máy POS xuất phiếu thu tại quầy:
* Chỉ có bảng `pos_receipts` với các cột `receipt_id`, `order_date`, `amount`.
* Hoàn toàn không có bảng `customers` hay cột định danh khách hàng.
* `CapabilityMatrix` đánh dấu rõ: `customers: "unsupported"`, `cost: "unsupported"`.
* **Mục đích**: Cung cấp môi trường kiểm thử để chứng minh C5 Answerability Precheck phát hiện chính xác câu hỏi *"Khách hàng nào mua nhiều tiền nhất..."* là `UNSUPPORTED` và xuất ra `MissingEvidenceProof` chuẩn xác.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Thiết kế theo nguyên tắc "Real-world Domain Modeling"**:
   * Dữ liệu mẫu không phải là các chuỗi vô nghĩa (`"table_a"`, `"col_1"`), mà mô tả đúng các trường dữ liệu và nghiệp vụ thực tế trong đề thi của Zalo AI Challenge. Điều này giúp các bài kiểm thử unit test có tính đại diện cao.
2. **Đảm bảo tính bao đóng độc lập**:
   * Nhà máy này không đọc file `.csv`, không kết nối DuckDB, không phụ thuộc vào thư mục `data/` của máy tính. Bộ test chạy trên máy nào cũng pass 100%, không lo thiếu file hay sai đường dẫn.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Nền tảng kiểm thử cho toàn bộ `tests/grounding/`**: Tất cả các file test `test_contracts.py`, `test_temporal.py`, `test_parser.py`, `test_schema_value_grounder.py`, `test_answerability.py`, `test_grounding_e2e.py` đều sử dụng trực tiếp các context từ file này.
* **Hình mẫu cho `B02ContextAdapter`**: Bất kỳ adapter nào viết cho B0.2 thật sau này cũng chỉ cần xuất ra các cấu trúc dữ liệu tương tự như `InMemoryBusinessContext`.

---

## 5. Nếu Không Có File Này Thì Sao?

* Nếu không có mock provider, mỗi khi muốn test một tính năng nhỏ của Grounding (ví dụ kiểm tra xem C2 có phân giải đúng ngày Tết hay không), bạn sẽ phải chạy toàn bộ pipeline B0.1 để đọc hàng trăm nghìn dòng từ file Excel/CSV thật vào DuckDB, khiến thời gian chạy test bị chậm đi hàng trăm lần và bị nghẽn (blocked) hoàn toàn mỗi khi bạn của bạn sửa code B0.1/B0.2.
