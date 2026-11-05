# Giải Thích Mã Nguồn: `__init__.py`
**Đường dẫn file:** `src/datamate/b05/__init__.py`  
**Thuộc module:** B0.5 Basic Output Gate  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

File `__init__.py` biến thư mục `src/datamate/b05/` thành một **Python Package chính thức** và đóng vai trò là **Giao diện công khai (Public Facade / Export API)** của module B0.5.

Thay vì bắt người dùng hoặc các module khác phải nhớ tên từng file con và import sâu:
```python
# Cách import dài dòng và lộ chi tiết nội bộ:
from datamate.b05.contracts import GateRequest, GateOutcome
from datamate.b05.gate import evaluate_gate
from datamate.b05.writer import SubmissionWriter
```
File `__init__.py` cho phép import cực kỳ gọn gàng và chuyên nghiệp:
```python
# Cách import chuẩn mực và sạch sẽ:
from datamate.b05 import evaluate_gate, GateRequest, GateOutcome, SubmissionWriter
```

---

## 2. Chi Tiết Các Thành Phần Được Export

Biến `__all__` công bố rõ danh sách các đối tượng được phép sử dụng từ bên ngoài package:

```python
__all__ = [
    "AnswerType",
    "ExecutionStatus",
    "FinalAnswer",
    "GateAction",
    "GateOutcome",
    "GateRequest",
    "RepairRequest",
    "ValidationResult",
    "evaluate_gate",
    "SubmissionWriter",
]
```

* **Các Dataclasses & Enums**: `GateRequest`, `GateOutcome`, `FinalAnswer`, `RepairRequest`, `ValidationResult`, `AnswerType`, `ExecutionStatus`, `GateAction`.
* **Hàm điều phối trung tâm**: `evaluate_gate` (từ `gate.py`).
* **Lớp ghi tệp tin**: `SubmissionWriter` (từ `writer.py`).

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Nguyên tắc đóng gói (Encapsulation) & Ẩn chi tiết nội bộ**:
   * Các hàm phụ trợ như `_to_decimal()`, `_validate_iso_date()`, `AuditLogger` hay các lớp nội bộ không được đưa vào `__all__`. Người dùng bên ngoài chỉ nhìn thấy những gì thực sự cần thiết, tránh việc gọi nhầm các hàm private.
2. **Hỗ trợ `from datamate.b05 import *` an toàn**:
   * Khai báo danh sách tường minh trong `__all__` đảm bảo nếu ai đó gõ `import *`, Python chỉ nạp đúng các class này, không làm tràn namespace (polluting namespace) bằng các biến tạm thời.
3. **Dễ dàng tái cấu trúc (Refactoring)**:
   * Nếu sau này chúng ta tách nhỏ file `gate.py` thành nhiều file khác, mã nguồn bên ngoài gọi `from datamate.b05 import evaluate_gate` vẫn giữ nguyên 100%, không bị ảnh hưởng.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các File Khác

* Là "cửa chính" để toàn bộ project tương tác với module B0.5.
* Được sử dụng trực tiếp trong `tests/test_writer.py`, `tests/test_determinism.py` và các pipeline sau này của B1/B2.

---

## 5. Nếu Không Có File Này Thì Sao?

* Python sẽ không coi `b05` là một package hoàn chỉnh.
* Mọi file khác muốn gọi B0.5 đều phải biết chính xác cấu trúc thư mục con bên trong, khiến mã nguồn bị phụ thuộc chặt (tight coupling) và rất khó bảo trì khi dự án mở rộng quy mô.

