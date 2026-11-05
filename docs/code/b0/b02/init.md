# Giải Thích Mã Nguồn: `__init__.py` (B0.2)

**Đường dẫn file:** `src/datamate/b0/b02/__init__.py`  
**Thuộc module:** B0.2 Context Extractor & Business Rules  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `__init__.py` đóng gói và xuất khẩu toàn bộ giao diện công khai của module B0.2. Các module downstream (như B0.3 Text-to-SQL hay file tích hợp chung `__main__.py`) chỉ cần import từ package `datamate.b0.b02` mà không cần quan tâm đến cấu trúc tệp nội bộ.

---

## 2. Chi Tiết Các Thực Thể Được Xuất Bản

```python
from .context_service import BusinessContextService
from .contracts import (
    CONTRACT_VERSION,
    BusinessContext,
    BusinessRule,
    ContractBuilder,
    RuleCatalog,
)
from .rule_compiler import BusinessRuleCompiler
from .rule_resolver import PRECEDENCE, ResolvedRules, RuleResolver
from .rule_templates import RuleTemplateBinder

__all__ = [
    "CONTRACT_VERSION",
    "BusinessRule",
    "RuleCatalog",
    "BusinessContext",
    "ContractBuilder",
    "BusinessContextService",
    "BusinessRuleCompiler",
    "PRECEDENCE",
    "ResolvedRules",
    "RuleResolver",
    "RuleTemplateBinder",
]
```

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Gom nhóm API hoàn chỉnh**: Cung cấp đầy đủ cả các thực thể dữ liệu (`BusinessContext`, `BusinessRule`), các hằng số nghiệp vụ (`PRECEDENCE`), và các lớp dịch vụ (`BusinessContextService`, `RuleResolver`, `RuleTemplateBinder`).
2. **Khai báo `__all__` nghiêm ngặt**: Đảm bảo an toàn khi các module khác gọi `import *`, chỉ xuất các đối tượng được kiểm duyệt.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* Cho phép B0.3 và CLI `__main__.py` khởi tạo nhanh chóng `BusinessContextService` chỉ với một câu lệnh import duy nhất.
* Giúp code kiểm thử (test suite) dễ đọc và ngắn gọn.

---

## 5. Nếu Không Có File Này Thì Sao?

* Python sẽ không thể import package `datamate.b0.b02`.
* Mã nguồn bên ngoài bị phân mảnh, phụ thuộc vào tên từng file con.

