# Giải Thích Mã Nguồn: `join_graph.py` (B0.1)

**Đường dẫn file:** `src/datamate/b0/b01/join_graph.py`  
**Thuộc module:** B0.1 Data Loader & Schema/Join Catalog  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `join_graph.py` đóng vai trò là **Công cụ Điều hướng Đồ thị Quan hệ và Biên dịch Biểu thức Join** giữa các bảng trong cơ sở dữ liệu.

Nó giải quyết 2 bài toán cốt lõi:
1. **Tìm đường nối ngắn nhất giữa 2 bảng** (`JoinGraphNavigator`): Khi cần lấy dữ liệu từ bảng A sang bảng C, tìm chuỗi các bảng trung gian cần JOIN thông qua các quan hệ đã được kiểm chứng (`validated`).
2. **Biên dịch điều kiện Join an toàn** (`JoinPredicateCompiler`): Chuyển đổi thông tin cạnh Join thành mệnh đề SQL `ON left.col = right.col` (hỗ trợ cả khóa đơn và khóa ghép).

---

## 2. Chi Tiết Các Lớp & Phương Thức Lõi

### 2.1. Lớp `JoinGraphNavigator`
* **Phương thức**: `find_path(catalog: SchemaCatalog, source: str, target: str) -> tuple[JoinEdge, ...] | None`.
* **Thuật toán**: 
  * Sử dụng thuật toán tìm kiếm theo chiều rộng (**Breadth-First Search - BFS**) trên hàng đợi `collections.deque`.
  * **Chỉ duyệt qua các cạnh có trạng thái `status == "validated"`**. Các cạnh chưa được kiểm chứng (`candidate` hoặc `uncertain`) sẽ bị bỏ qua để tránh tạo ra các phép join vô căn cứ.
  * Sắp xếp danh sách cạnh theo thứ tự bảng có tính tất định (deterministic sorting) để đảm bảo cùng input luôn cho ra cùng một đường đi duy nhất.
  * Trả về tuple các cạnh `JoinEdge` nối từ `source` đến `target`, hoặc `None` nếu không có đường đi hợp lệ.

### 2.2. Lớp `JoinPredicateCompiler`
* **Phương thức**: `compile(edge: JoinEdge, catalog: SchemaCatalog) -> str`.
* **Cơ chế**:
  * Kiểm tra tính tồn tại của bảng và cột trong `catalog`.
  * Duyệt qua toàn bộ danh sách `edge.key_pairs` (bao gồm cặp khóa chính đầu tiên và các cặp bổ sung trong `additional_key_pairs`).
  * Bao bọc tên cột và tên bảng trong dấu nháy kép `"` (identifier quoting) để chống lỗi cú pháp khi tên bảng/cột trùng với từ khóa SQL (ví dụ `"order"`, `"group"`).
  * Nối các điều kiện bằng từ khóa `AND`.
  * **Ví dụ kết quả sinh ra**:
    ```sql
    "order_items"."order_id" = "orders"."id" AND "order_items"."shop_id" = "orders"."shop_id"
    ```

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Chỉ tin cậy các cạnh `validated`**:
   Trong Text-to-SQL, việc tự ý JOIN 2 bảng qua một cột đoán mò sẽ dẫn đến tích Descartes (Cartesian product) hoặc ra dữ liệu rỗng. Việc chỉ duyệt các cạnh `validated` đảm bảo tính toàn vẹn 100%.
2. **Hỗ trợ đầy đủ Khóa ghép (All Composite Key Pairs)**:
   Nếu quan hệ yêu cầu 2 cột ghép `(order_id, shop_id)` mà câu lệnh JOIN chỉ viết `order_id = order_id` thì sẽ bị nhân đôi số dòng khi một đơn hàng xuất hiện ở nhiều shop. `JoinPredicateCompiler` bắt buộc phải bao gồm đầy đủ mọi cặp khóa.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Module B0.3 (Text-to-SQL)**: Sử dụng kết quả của `find_path()` và `compile()` để tự động bổ sung các mệnh đề `JOIN ... ON ...` vào prompt hoặc query SQL.
* **Module B0.5 (Output Gate)**: Giúp kiểm tra xem câu SQL do LLM sinh ra có dùng đúng đường join hợp lệ hay không.

---

## 5. Nếu Không Có File Này Thì Sao?

* LLM sẽ phải tự suy diễn cách nối giữa các bảng không có liên kết trực tiếp (ví dụ từ `customers` sang `products` phải qua `orders` và `order_items`), dẫn đến tỷ lệ lỗi join sai rất cao.
* Các biểu thức khóa ghép sẽ dễ bị thiếu cột thứ hai, gây ra lỗi nhân bản dòng (fanout bug).

