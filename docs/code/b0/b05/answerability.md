# Giải Thích Mã Nguồn: `answerability.py`
**Đường dẫn file:** `src/datamate/b05/answerability.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `answerability.py` là **Động cơ thẩm định khả năng trả lời dựa trên bằng chứng (Evidence-Based Answerability Engine)**.

Trong cuộc thi Zalo AI Challenge 2026 (Track 2), có những câu hỏi mà dữ liệu bảng được phát hành **thực sự không chứa đủ thông tin để tính toán** (ví dụ: bảng đơn hàng chỉ có giá bán, không có giá vốn nên không thể tính lợi nhuận gộp). Đề bài quy định một loại đáp án là `unanswerable`.

Tuy nhiên, cơ chế tính điểm của cuộc thi rất khắt khe:
$$\text{PA} = \frac{\text{Correct} - \text{Wrong}}{N}$$
- Nếu đoán `unanswerable` mà thực tế dữ liệu có thể tính được: **Bị trừ 1 điểm (-1)**.
- Nếu chọn `abstain` (bỏ phiếu trắng): **Được 0 điểm (không bị trừ điểm)**.

File `answerability.py` sinh ra với một sứ mệnh duy nhất: **Bảo vệ đội thi không bị trừ điểm oan do False Unanswerable**.

---

## 2. Chi Tiết Hàm `evaluate_answerability`

```python
def evaluate_answerability(request: GateRequest) -> Tuple[bool, Optional[str]]:
```
Hàm trả về bộ đôi: `(is_unanswerable: bool, reason: Optional[str])`.

### 4 Tiêu Chí Bắt Buộc Để Được Xác Nhận Là `unanswerable`:

1. **Nguồn bằng chứng phải được kiểm chứng độc lập (`catalog_verified`)**:
   ```python
   if evidence.source_kind != "catalog_verified":
       return False, None
   ```
   * *Ý nghĩa*: Tuyệt đối **không tin** vào lời tự khai của LLM (`llm_self_claim`). Khi LLM không biết viết câu SQL thế nào, nó thường "lười biếng" và tự bảo rằng câu hỏi này không trả lời được. B0.5 lập tức bác bỏ tuyên bố này.
2. **Xác nhận tính năng không được hỗ trợ**:
   ```python
   if evidence.capability_status != "unsupported":
       return False, None
   ```
   * Phải có catalog xác nhận trường dữ liệu hoặc metric này hoàn toàn không có trong schema.
3. **Đã kiểm tra toàn bộ các nguồn thay thế (`checked_all_sources == True`)**:
   * Đảm bảo hệ thống đã tìm kiếm khắp các bảng liên quan (bảng phụ, catalog giá, danh mục sản phẩm) mà vẫn không thấy.
4. **Có danh sách trường dữ liệu bị thiếu cụ thể (`missing_fields` hoặc `proof`)**:
   * Phải chỉ ra rõ ràng thiếu cột nào (ví dụ: thiếu cột `cost_at_sale`).

Nếu thỏa mãn cả 4 điều kiện trên:
* Trả về `True` kèm lý do cụ thể: `"Dữ liệu được kiểm chứng thiếu các trường thông tin: cost_at_sale"`.
Nếu vi phạm bất kỳ điều kiện nào:
* Trả về `False, None` (báo hiệu cho Gate chuyển câu hỏi sang `abstain` để nhận 0 điểm an toàn thay vì mạo hiểm bị -1 điểm).

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Chiến lược tối ưu hóa điểm số kỳ vọng (PA Optimization)**:
   * Nếu không chắc chắn 100% là dữ liệu bị thiếu, việc đoán `unanswerable` có giá trị kỳ vọng âm:
     $$\mathbb{E}[\text{score}] = p \cdot (+1) + (1-p) \cdot (-1) = 2p - 1$$
     Chỉ khi xác suất chắc chắn $p > 50\%$ mới nên đoán. Bằng cách khóa chặt điều kiện `catalog_verified`, chúng ta đưa xác suất đúng lên gần 100%.
2. **Tách biệt giữa "Model không biết làm" và "Dữ liệu thực sự thiếu"**:
   * Khi câu lệnh SQL bị lỗi `BinderException` (ví dụ gõ nhầm tên cột), đó là lỗi của model B0.3, chứ không phải dữ liệu thiếu. `answerability.py` ngăn chặn việc biến lỗi SQL thành `unanswerable`.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* **Được gọi đầu tiên trong `gate.py`**: Trước khi kiểm tra kết quả SQL, `gate.py` gọi hàm này để xem câu hỏi có thuộc diện được miễn thi hành SQL do thiếu dữ liệu hay không.
* **Quyết định cấu trúc `FinalAnswer`**: Khi hàm trả về `True`, `gate.py` sẽ tạo `FinalAnswer(type="unanswerable", reason=...)` với lý do được trích xuất từ chính bằng chứng này.

---

## 5. Nếu Không Có File Này Thì Sao?

* Đội thi sẽ phụ thuộc hoàn toàn vào output của LLM. Mỗi khi LLM lười suy luận hoặc không hiểu câu hỏi tiếng Việt, nó sẽ trả về `unanswerable`, khiến đội thi bị **trừ hàng chục điểm PA** trên bảng xếp hạng (Leaderboard) của Zalo AI Challenge.

