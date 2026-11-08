# ĐÚC KẾT SAU CHẠY PUBLIC TEST: TẠI SAO ĐIỂM BỊ ÂM & CÁCH SỬA CHO TEAM

> **Người ghi chú:** Minh (phụ trách Executor B0.4/B1.4)  
> **Dữ liệu phân tích:** Đối chiếu trực tiếp 1,000 câu giữa 2 lần chạy (`public_test_full` vs `public_test_full_v0`).  
> **Mục đích:** Nhìn thẳng vào sự thật để team sửa đúng chỗ, kéo điểm từ âm sang dương cho các vòng sau.

---

## 1. TÌNH HÌNH THỰC TẾ & LUẬT CHƠI CỦA BTC

Hai lần nộp bài của nhóm mình:
* Bản cũ (Kiệt chạy): **`-0.20800`**
* Bản mới (Minh chạy sau khi sửa tầng thực thi B1.4): **`-0.25000`**

### Luật tính điểm của Zalo AI (rất gắt):
$$\text{Score} = \frac{\text{Số câu Đúng (+1)} - \text{Số câu Sai (-1)}}{1,000}$$
* **Đúng:** `+1 điểm`
* **Sai:** `Bị phạt -1 điểm` (cực nặng)
* **Bỏ qua (Abstain):** `0 điểm` (an toàn, không bị trừ)

👉 **Điểm đang bị âm nghĩa là:** Số câu trả lời **Sai** của nhóm mình đang nhiều hơn số câu **Đúng**.

---

## 2. TẠI SAO SỬA B1.4 CHẠY NGON HƠN MÀ ĐIỂM VẪN ÂM?

Tầng B1.4 (DuckDB Executor) của mình đã làm tròn vai: chạy mượt cả 1,000 câu trên GPU A100, không bị lỗi Docker Read-Only, có Schema Hint nhắc cột khi retry.

**Nhưng điểm bị tụt nhẹ là vì một nghịch lý:**
* Ở bản cũ, có **114 câu** bị lỗi ngớ ngẩn (lỗi cú pháp, quét nhầm từ cấm) $\rightarrow$ Hệ thống tự vứt sang `abstain` $\rightarrow$ **Được 0 điểm**.
* Sang bản mới B1.4, mình sửa hết các lỗi nghẽn đó nên câu lệnh SQL chạy thành công ra số $\rightarrow$ Nhưng vì **câu SQL do LLM viết bị sai logic kế toán**, nên số nộp lên bị BTC chấm **SAI (-1 điểm)**.
* **Nói nôm na:** Tầng thực thi như cái xe máy. Xe của mình chạy êm, phanh nhạy, nhưng người lái (LLM phía trước) chỉ sai đường thì xe càng chạy nhanh lại càng đi xa đích.

---

## 3. PHÂN TÍCH LỖI Ở CÁC BƯỚC KHÁC (SOI TỪ LOG THỰC TẾ)

### Lỗi 1: Module B0.3 (Text-to-SQL) — Lỗi nặng nhất (~60% điểm trừ)
1. **Nhầm lẫn các khái niệm tiền bạc:**
   * Soi câu `q_014cdcc1da6e`:
     - Bản Kiệt: SQL lấy `thanh_tien - tien_giam` $\rightarrow$ ra `9,341,000`
     - Bản Minh: SQL lấy `SUM(thanh_tien)` $\rightarrow$ ra `28,763,000`
   * Model Qwen 9B hiện tại không biết lúc nào cần trừ chiết khấu, lúc nào cần trừ tiền trả hàng.
2. **Lọc ngày tháng tiếng Việt bị trượt:**
   * Shop Việt Nam lưu ngày dạng `dd/mm/yyyy` (chuỗi text). Khi hỏi "doanh thu tháng 5", LLM hay phang hàm `WHERE strftime('%m', ngay) = '05'` $\rightarrow$ Không ra dòng nào hoặc lọc sai sạch.
3. **Chưa có ví dụ mẫu (Few-shot):**
   * Hiện tại prompt chỉ ném schema vào rồi bắt LLM tự chế SQL. Cần ít nhất 3-5 câu ví dụ mẫu chuẩn cho từng dạng (Top N, tăng trưởng %).

### Lỗi 2: Module B0.2 (Rule Compiler - Đọc `README.md` của Shop)
* Mỗi shop có 1 file `README.md` rất dài: *"đơn hủy không tính"*, *"hàng khuyến mãi giá 0đ"*.
* Hiện tại B0.2 ném nguyên cả đoạn văn dài vào prompt làm LLM bị "loãng", đọc trước quên sau.
* Hậu quả: LLM viết câu SQL quên béng mất điều kiện loại trừ (`WHERE trang_thai != 'Huy'`).

### Lỗi 3: Module B0.1 (Data Ingestion & Nối bảng JOIN)
* Các bảng của shop không có ID chuẩn, toàn nối qua `Tên sản phẩm` (dạng text).
* Nếu B0.1 suy luận sai quan hệ JOIN, câu lệnh SQL sẽ bị nhân đôi số dòng (Cartesian product), làm tiền doanh thu vọt lên gấp 2-3 lần đáp án thật.

### Lỗi 4: Module B0.5 (Output Gate - Sai lầm về mặt chiến thuật)
* **Lỗ hổng:** Cứ hễ DuckDB chạy ra một con số là B0.5 đem nộp ngay!
* Nhớ rằng: **Nộp sai bị -1 điểm, thà không nộp (Abstain) vẫn được 0 điểm!**
* Nhóm mình đang nộp tới 738 câu, trong đó có quá nhiều câu đoán mò $\rightarrow$ Bị phạt âm nặng nề.

---

## 4. GỢI Ý HÀNH ĐỘNG CỤ THỂ CHO TỪNG BẠN TRONG TEAM

| Người phụ trách | Cần làm gì ngay để tăng điểm? |
| :--- | :--- |
| **Phụ trách B0.5 (Cổng nộp bài)** | **Cài bộ lọc "Không chắc thì Không nộp":**<br>- Nếu câu SQL không có lọc trạng thái đơn hàng (`trang_thai`), hoặc số tiền ra âm vô lý $\rightarrow$ **Ép `abstain` ngay (lấy 0 điểm)**.<br>- Chỉ cần biến 100 câu đoán bừa từ `-1` thành `0`, điểm của team sẽ **nhảy ngay từ âm sang dương**! |
| **Phụ trách B0.3 (Prompt & LLM)** | **Chuẩn hóa công thức kế toán trong Prompt:**<br>- Ghi rõ: `Doanh thu = SUM(thành tiền - giảm giá)`.<br>- Hướng dẫn LLM cách ép kiểu ngày `dd/mm/yyyy` bằng `strptime`.<br>- Thêm 3-5 ví dụ Few-shot mẫu vào prompt. |
| **Phụ trách B0.2 (Đọc Rule)** | **Lọc cô đọng `README.md`:**<br>- Chỉ trích xuất đúng các dòng có từ khóa: "doanh thu", "hủy", "trả hàng", "giảm giá". Đừng ném cả file dài vào làm loãng LLM. |
| **Phụ trách B0.1 (Nối bảng)** | **Kiểm soát phép JOIN:**<br>- Cảnh báo trong prompt nếu bảng nối qua tên text để LLM dùng `GROUP BY` tránh bị nhân đôi doanh thu. |

---

## 5. LỜI KẾT
Tầng thực thi B1.4 hiện tại đã rất vững, môi trường Docker và Modal đã chạy trơn tru. Team mình chỉ cần tinh chỉnh lại B0.3 (cách viết SQL) và siết chặt B0.5 (dám chọn `abstain` khi không chắc) là điểm số ở lần nộp tới chắc chắn sẽ bứt phá mạnh!
