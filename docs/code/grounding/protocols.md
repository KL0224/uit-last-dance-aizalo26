# Giải Thích Mã Nguồn: `protocols.py`

**Đường dẫn file:** [`src/datamate/grounding/protocols.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/grounding/protocols.py)  
**Thuộc module:** Component C — Question Grounding (Structural Protocols & Abstractions)  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2: Vietnamese Tabular QA)

---

## 1. Tổng Quan & Vai Trò

File `protocols.py` là **Lớp trừu tượng hóa và tách biệt phụ thuộc (Decoupling & Protocol Layer)** của Component C. 

Theo nguyên lý Đảo ngược phụ thuộc (**Dependency Inversion Principle - DIP**), các module cấp cao (như Question Grounding) không nên phụ thuộc trực tiếp vào các chi tiết triển khai cụ thể của module cấp thấp (như cơ chế đọc file của B0.1 hay cấu trúc context của B0.2). Thay vào đó, cả hai bên cùng phụ thuộc vào một giao diện trừu tượng (**Protocol**).

File này thực hiện hai nhiệm vụ cốt lõi:
1. Định nghĩa các cấu trúc đặc tả siêu dữ liệu gọn nhẹ (`ColumnSpec`, `TableSpec`, `JoinSpec`, `MetricSpec`, `CalendarEventSpec`) phục vụ riêng cho các thuật toán phân tích ngữ nghĩa của Grounding, loại bỏ hoàn toàn các trường dữ liệu nặng không liên quan (như hàng trăm nghìn dòng dữ liệu thô hay cấu trúc DuckDB connection).
2. Thiết lập hai giao diện chuẩn `@runtime_checkable Protocol`:
   * `BusinessContextProtocol`: Hợp đồng quy định ngữ cảnh nghiệp vụ doanh nghiệp.
   * `LLMParserProtocol`: Hợp đồng cho mô hình ngôn ngữ 3B phục vụ việc trích xuất ý định (Intent Parsing).

---

## 2. Chi Tiết Các Class & Protocol

### 2.1. Các Descriptor Siêu Dữ Liệu Nhẹ (Lightweight Metadata Descriptors)

#### `ColumnSpec`
Biểu diễn siêu dữ liệu của một cột dưới góc nhìn giải tích ngữ nghĩa:
* `name: str`: Tên cột trong cơ sở dữ liệu.
* `data_type: str`: Kiểu dữ liệu vật lý (`"VARCHAR"`, `"DATE"`, `"DOUBLE"`, `"BIGINT"`).
* `description: str`: Mô tả ý nghĩa của cột (trích xuất từ README hoặc tên gốc tiếng Việt).
* `aliases: tuple[str, ...]`: Các tên gọi tương đương trong tiếng Việt (ví dụ: cột `line_revenue` có các alias `("doanh thu", "thành tiền", "tiền hàng")`).
* `sample_values: tuple[Any, ...]`: Danh sách tối đa 10–15 giá trị mẫu thực tế đã được chuẩn hóa (ví dụ: tên ca làm việc `("Ca sáng", "Ca tối")` hay tên món `("Cà phê sữa (L)")`), giúp C4 Value Grounder đối chiếu thực thể mà không phải query lại toàn bộ database.
* `role: str`: Vai trò ngữ nghĩa của cột (`"id"`, `"date"`, `"money"`, `"quantity"`, `"category"`, `"name"`, `"text"`).
* `null_ratio: float`: Tỷ lệ rỗng của cột (từ 0.0 đến 1.0) giúp C3 ưu tiên các cột có độ đầy đủ dữ liệu cao hơn.

#### `TableSpec`
Biểu diễn siêu dữ liệu của một bảng dữ liệu:
* `name: str`: Tên bảng trong DuckDB/SQLite.
* `columns: tuple[ColumnSpec, ...]`: Danh sách các cột đã được chuyển đổi sang `ColumnSpec`.
* `grain: str`: Cấp độ đơn vị của một dòng trong bảng (`"order"`, `"order_item"`, `"payment_event"`, `"customer"`). Đây là thông tin sống còn để phát hiện nguy cơ nhân dòng khi JOIN.
* `description: str`: Mô tả tổng quan về bảng.
* `aliases: tuple[str, ...]`: Tên gọi tương đương của bảng (ví dụ: `("hóa đơn", "đơn hàng", "bill")`).
* `row_count: int`: Số lượng dòng của bảng.
* `date_coverage_start: str | None` & `date_coverage_end: str | None`: Khoảng thời gian mà bảng bao phủ (chuẩn ISO `YYYY-MM-DD`). Giúp C5 phát hiện trường hợp câu hỏi hỏi về năm 2026 nhưng bảng chỉ có dữ liệu năm 2025.

#### `JoinSpec`
Mô tả một cạnh liên kết giữa hai bảng trong `JoinGraph`:
* `left_table: str` & `left_column: str`: Bảng và cột phía trái.
* `right_table: str` & `right_column: str`: Bảng và cột phía phải.
* `cardinality: str`: Lực lượng quan hệ (`"many_to_one"`, `"one_to_many"`, `"one_to_one"`).
* `fanout_warning: bool`: Đánh dấu cảnh báo nếu phép JOIN có nguy cơ nhân bản số dòng (đặc biệt khi nối từ bảng 1 dòng sang bảng nhiều dòng).
* `confidence: float`: Độ tin cậy của quan hệ (từ 0.0 đến 1.0).

#### `MetricSpec`
Đặc tả chỉ số nghiệp vụ chuẩn từ Semantic Metric Registry (Component B3):
* `metric_id: str`: Định danh chuẩn của metric (`"revenue"`, `"cash_collected"`, `"sold_qty"`, `"distinct_product_orders"`).
* `aliases: tuple[str, ...]`: Các cách diễn đạt chỉ số bằng tiếng Việt.
* `preferred_table: str`: Bảng Fact Table chuẩn nhất chứa chỉ số này (ví dụ: `revenue` ưu tiên `order_items`; `cash_collected` ưu tiên `shift_payments`).
* `required_columns: tuple[str, ...]`: Các cột bắt buộc phải có để tính được metric.
* `date_role: str`: Cột thời gian chuẩn cần áp dụng (`"order_date"` hay `"payment_date"`).
* `formula_hint: str`: Công thức gợi ý cho Planner (ví dụ: `"SUM(order_items.line_revenue)"`).
* `unit: str`: Đơn vị kết quả (`"money_vnd"`, `"count"`, `"quantity"`, `"percent"`).

#### `CalendarEventSpec`
Đặc tả kỳ sự kiện hoặc ngày lễ lịch âm/dương từ `calendar.csv`:
* `event_key: str`: Mã sự kiện (ví dụ: `"tet_2026"`, `"tet_2025"`).
* `aliases: tuple[str, ...]`: Các cụm từ người dùng hay gọi (ví dụ: `("tết", "tết âm lịch", "tết nguyên đán")`).
* `year: int`: Năm diễn ra sự kiện.
* `start_date: str` & `end_date: str`: Khoảng ngày bắt đầu và kết thúc chuẩn ISO.

---

### 2.2. Các Giao Diện Trừu Tượng Chuẩn (`Protocols`)

#### `BusinessContextProtocol`
Giao diện trung tâm mà mọi nguồn cung cấp ngữ cảnh (Mock Provider hay Adapter B0.2) bắt buộc phải cài đặt:
1. `business_id: str`: Thuộc tính định danh doanh nghiệp.
2. `get_tables() -> Sequence[TableSpec]`: Trả về danh sách tất cả các bảng và cột.
3. `get_join_edges() -> Sequence[JoinSpec]`: Trả về toàn bộ các cạnh trong đồ thị liên kết bảng.
4. `get_metrics() -> Sequence[MetricSpec]`: Trả về danh mục các chỉ số nghiệp vụ đã đăng ký.
5. `get_capability_status(capability_key: str) -> str`: Trả về trạng thái năng lực (`"supported"`, `"unsupported"`, `"unknown"`).
6. `get_calendar_events() -> Sequence[CalendarEventSpec]`: Trả về danh sách các sự kiện lịch và ngày lễ.
7. `get_active_rules(topic: str | None = None) -> Sequence[str]`: Trả về các quy tắc nghiệp vụ đang hiệu lực, đã được sắp xếp theo mức độ ưu tiên (`precedence`).
8. `get_value_aliases() -> dict[str, tuple[str, str, Any]]`: Trả về từ điển ánh xạ cụm từ tiếng Việt sang `(tên_bảng, tên_cột, giá_trị_db)`.

#### `LLMParserProtocol`
Giao diện trừu tượng cho bộ trích xuất ý định bằng mô hình 3B:
* Phương thức:
  ```python
  def extract_intent(
      self,
      question: str,
      as_of_date: str,
      available_metrics: Sequence[str],
      available_tables: Sequence[str],
  ) -> QuestionIntent:
      ...
  ```
* Cho phép cắm bất kỳ backend nào (vLLM client, HuggingFace pipeline, hoặc Fake Client phục vụ Unit Test) mà không làm thay đổi code của C1.

---

## 3. Tại Sao Lại Thiết Kế & Code Như Vậy?

1. **Sử dụng `@runtime_checkable` của thư viện chuẩn `typing`**:
   * Cho phép kiểm tra tính hợp lệ bằng hàm `isinstance(ctx, BusinessContextProtocol)` ngay trong thời gian chạy. Nếu một module mới của đồng đội không cung cấp đủ 8 phương thức trên, hệ thống sẽ phát hiện ngay tại tầng Adapter thay vì gây lỗi tiềm ẩn bên trong Engine.
2. **Loại bỏ sự phụ thuộc vòng (Circular Dependencies)**:
   * Giúp `grounding` không cần `import` bất kỳ file nào từ `datamate.b0.b01` hay `b02`. Nó chỉ quan tâm đến các Spec nhẹ. Việc chuyển đổi từ B0.1/B0.2 sang Spec này được giao toàn quyền cho file `adapters.py`.
3. **Tối ưu hóa bộ nhớ và tốc độ**:
   * `TableSpec` và `ColumnSpec` chỉ giữ các chuỗi văn bản và danh sách mẫu nhỏ (tuple), không giữ file handle hay database cursor, giúp việc truyền context giữa các tiến trình diễn ra cực nhanh mà không bị rò rỉ bộ nhớ.

---

## 4. Ý Nghĩa & Ảnh Hưởng Liên Đới Đến Các Module Khác

* **Đối với B0.1 & B0.2**: Đóng vai trò là bản đặc tả kỹ thuật (Contract Specification) quy định rõ: *Muốn Grounding chạy tốt, B0.1 và B0.2 cần trích xuất được những thông tin gì từ file thô*.
* **Đối với bộ kiểm thử (`tests/grounding/`)**: Cho phép tạo ra các đối tượng giả lập hoàn hảo (`InMemoryBusinessContext`) trong `mock_provider.py` để kiểm thử độc lập mà không cần đọc bất kỳ file dữ liệu thật nào từ thư mục `data/train` hay `data/public_test`.

---

## 5. Nếu Không Có File Này Thì Sao?

* Nếu không có `protocols.py`, Component C sẽ phải `import` trực tiếp `BusinessContext` từ `datamate.b0.b02.contracts`. Khi đồng đội của bạn tái cấu trúc B0.2 (đổi tên trường, đổi kiểu dữ liệu), toàn bộ module Grounding sẽ bị crash và không thể chạy test được.
* Không thể áp dụng kiến trúc kiểm thử nhanh với Fake Client cho mô hình 3B, buộc mỗi lần chạy test C1 đều phải khởi động một model LLM thật trên GPU, làm tăng thời gian chạy test từ **0.7 giây lên hàng chục giây**.
