# TỔNG HỢP CÁC ĐIỂM CẦN CẢI THIỆN THEO TỪNG BƯỚC PIPELINE

> **Nguyên tắc cốt lõi của đề thi Zalo AI:**
> * Đúng: `+1 điểm`
> * Sai: `Bị trừ -1 điểm` (phạt nặng)
> * Bỏ qua (Abstain): `0 điểm`
> 
> 👉 **Chiến lược:** Không chắc chắn thì chọn **Abstain (0 điểm)**, chỉ nộp khi tự tin đúng logic để lấy `+1 điểm`.

---

### 1. Bước B0.1: Tiền xử lý & Nối bảng (Data Ingestion & Schema Linker)
* **Kiểm soát phép JOIN tránh nhân đôi dòng (Cartesian product):**
  * Các bảng dữ liệu thường nối qua chuỗi text (như `Tên sản phẩm`, `Tên khách`), không có khóa chính chuẩn. Cần cảnh báo hoặc xử lý tiền lọc để câu truy vấn không bị nhân đôi số dòng, làm thổi phồng doanh thu.
* **Chuẩn hóa ngày tháng:**
  * Định dạng ngày lưu dạng chuỗi tiếng Việt `dd/mm/yyyy`, cần chú thích rõ kiểu dữ liệu trong schema để các bước sau không xử lý nhầm.

---

### 2. Bước B0.2: Trích xuất quy tắc nghiệp vụ (Rule Compiler)
* **Lọc cô đọng nội dung file `README.md` của từng shop:**
  * Hiện tại ném toàn bộ văn bản dài vào prompt làm mô hình bị loãng chú ý (attention loss).
  * Chỉ trích xuất các điều kiện quan trọng: quy tắc tính doanh thu, điều kiện loại trừ đơn hủy/đơn trả, hàng khuyến mãi giá 0đ.
* **Đóng gói quy tắc thành gạch đầu dòng ngắn gọn:**
  * Đặt các quy tắc nghiệp vụ sát câu hỏi để mô hình bắt buộc phải áp dụng vào điều kiện `WHERE`.

---

### 3. Bước B0.3: Sinh câu truy vấn (Text-to-SQL - Trọng tâm chính)
* **Chuẩn hóa công thức kế toán trong Prompt:**
  * Đưa định nghĩa rõ ràng: `Doanh thu = SUM(thành tiền - chiết khấu/giảm giá)`.
  * Luôn nhắc kiểm tra điều kiện lọc đơn hợp lệ: `WHERE trang_thai NOT IN ('Đã hủy', 'Trả hàng')`.
* **Xử lý ngày tháng tiếng Việt (`dd/mm/yyyy`):**
  * Hướng dẫn mô hình dùng hàm DuckDB chuẩn: `TRY_STRPTIME(ngay, '%d/%m/%Y')` thay vì dùng hàm cắt chuỗi hoặc `strftime` sai định dạng.
* **Thêm ví dụ mẫu (Few-shot learning):**
  * Bổ sung 3–5 ví dụ SQL mẫu cho các dạng câu hỏi phổ biến: Top N, tính tỷ lệ %, tăng trưởng theo tháng/quý.
* **Ép định dạng phản hồi:**
  * Chỉ trả về block SQL chuẩn, hạn chế tối đa việc mô hình giải thích văn xuôi gây lỗi trích xuất câu lệnh.

---

### 4. Bước B0.4: Thực thi truy vấn (DuckDB Execution)
* **Cơ chế thực thi & sửa lỗi:**
  * Giữ nguyên bộ phân tích AST và cơ chế Schema Hint (bổ sung danh sách cột/bảng khi câu lệnh bị lỗi để retry).
* **Cảnh báo kết quả rỗng bất thường:**
  * Khi câu SQL thực thi thành công nhưng trả về toàn `NULL` hoặc 0 dòng với các câu hỏi tính tổng/doanh thu, cần phát cờ nghi ngờ để kích hoạt retry hoặc chuyển sang abstain.

---

### 5. Bước B0.5: Bộ lọc quyết định nộp bài (Output Gate - Tăng điểm nhanh nhất)
* **Siết chặt tiêu chuẩn nộp (Aggressive Abstain):**
  * Áp dụng nguyên tắc: **Nộp sai bị trừ 1 điểm, thà bỏ qua (Abstain) vẫn an toàn lấy 0 điểm.**
  * Nếu câu SQL thiếu điều kiện lọc trạng thái đơn hàng, hoặc kết quả tính ra số âm vô lý $\rightarrow$ Ép `abstain` ngay.
  * Chỉ nộp những câu có độ tự tin cao. Việc chuyển bớt các câu đoán mò sang `abstain` sẽ giúp kéo điểm tổng từ âm sang dương ngay lập tức.
