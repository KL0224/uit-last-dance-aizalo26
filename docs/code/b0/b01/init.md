# Giải Thích Mã Nguồn: `__init__.py` (B0.1)

**Đường dẫn file:** `src/datamate/b0/b01/__init__.py`  
**Thuộc module:** B0.1 Data Loader & Schema/Join Catalog  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `__init__.py` là điểm truy cập công khai (Public API Entrypoint) của package `b01`. Nó tập trung nhập và xuất khẩu (`__all__`) toàn bộ các lớp dữ liệu và lớp dịch vụ quan trọng nhất mà các module bên ngoài (như B0.2, B0.3, test suites) cần sử dụng.

---

## 2. Chi Tiết Các Thực Thể Được Xuất Bản

```python
from .contracts import (
    ColumnMetadata,
    JoinEdge,
    KeyCandidate,
    SchemaCatalog,
    TableMetadata,
)
from .join_graph import JoinGraphNavigator, JoinPredicateCompiler
from .metadata_adapter import (
    BaseMetadataProvider,
    FoundationMetadata,
    JSONMetadataProvider,
)
from .schema_catalog import SchemaCatalogBuilder

__all__ = [
    "ColumnMetadata",
    "TableMetadata",
    "KeyCandidate",
    "JoinEdge",
    "SchemaCatalog",
    "JoinGraphNavigator",
    "JoinPredicateCompiler",
    "BaseMetadataProvider",
    "FoundationMetadata",
    "JSONMetadataProvider",
    "SchemaCatalogBuilder",
]
```

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Đóng gói thông tin (Encapsulation)**: Thay vì các module khác phải gọi đường dẫn sâu như `from datamate.b0.b01.schema_catalog import SchemaCatalogBuilder`, caller chỉ cần viết ngắn gọn:
   ```python
   from datamate.b0.b01 import SchemaCatalogBuilder, JSONMetadataProvider
   ```
2. **Khai báo `__all__` minh bạch**: Giúp IDE tự động gợi ý code (IntelliSense) chuẩn xác, ngăn ngừa việc import nhầm các biến nội bộ (private helpers).

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **Module B0.2 Context Service**: Import trực tiếp `BaseMetadataProvider` và `SchemaCatalogBuilder` từ `b01` để phối hợp dựng Business Context.
* **Module B0.5 Output Gate**: Sử dụng `SchemaCatalog` để xác thực `unanswerable` proof.
* **Hệ thống Test**: Cho phép viết test case ngắn gọn và rõ ràng.

---

## 5. Nếu Không Có File Này Thì Sao?

* Python sẽ không coi thư mục `b01` là một package hoàn chỉnh, dẫn đến lỗi import.
* Mọi tệp bên ngoài buộc phải biết chính xác từng tên file con bên trong `b01`, làm tăng độ kết dính (tight coupling), nếu sau này refactor đổi tên file thì toàn bộ mã nguồn bên ngoài sẽ bị gãy.

