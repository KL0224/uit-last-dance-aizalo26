# Giải Thích Mã Nguồn: `__init__.py` (B0.4)

**Đường dẫn file:** [`src/datamate/b0/b04/__init__.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/b04/__init__.py)  
**Thuộc module:** B0.4 DuckDB Read-Only Execution Engine  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `__init__.py` định nghĩa giao diện xuất khẩu công khai (Public Interface) của module B0.4. File này đóng gói toàn bộ các lớp cấu trúc dữ liệu, các ngoại lệ bảo mật, các hàm kiểm tra AST và hàm thực thi chính, cho phép các module khác trong hệ thống import trực tiếp mà không cần quan tâm đến cách phân chia tệp bên trong.

---

## 2. Danh Mục Các Biểu Tượng Xuất Khẩu (`__all__`)

```python
__all__ = [
    # 1. Schemas & Exceptions
    "ExecutionRequest",
    "ExecutionResponse",
    "EmptyQueryError",
    "SecurityViolation",
    "QueryTimeoutError",
    "normalize_value",
    # 2. Sanitizer
    "extract_clean_sql",
    "validate_read_only_sql",
    # 3. Error Handling
    "classify_error",
    "determine_route",
    "enrich_error_with_schema",
    "format_error_message",
    # 4. Engine
    "execute_query",
]
```

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Tuân thủ nguyên tắc Information Hiding:**
   Tất cả các caller (như pipeline chính hay các bài test) chỉ cần import từ `datamate.b0.b04`, ví dụ:
   ```python
   from datamate.b0.b04 import ExecutionRequest, execute_query
   ```
   Nếu cấu trúc bên trong của B0.4 có thay đổi (tách file, đổi tên hàm nội bộ), mã nguồn gọi bên ngoài không bị ảnh hưởng.
2. **Khai báo `__all__` tường minh:**
   Giúp ngăn ngừa ô nhiễm namespace khi người dùng sử dụng `from datamate.b0.b04 import *` và hỗ trợ các công cụ kiểm tra kiểu tĩnh (Mypy/Pyright) phân tích chính xác.

---

## 4. Tương Thích & Mối Liên Hệ

* Được export tập trung tại [`src/datamate/b0/__init__.py`](file:///home/kiet97/uit-last-dance-aizalo26/src/datamate/b0/__init__.py).
* Cung cấp API trực tiếp cho các kịch bản kiểm thử tại [`tests/test_b0_4_executor.py`](file:///home/kiet97/uit-last-dance-aizalo26/tests/test_b0_4_executor.py).

---

## 5. Nếu Không Có File Này Thì Sao?

* Python sẽ không thể import module dạng `from datamate.b0.b04 import ...`.
* Code bên ngoài buộc phải import sâu vào từng file (`from datamate.b0.b04.engine import execute_query`), làm giảm tính module hóa và tăng rủi ro khi tái cấu trúc.

