# Giải Thích Mã Nguồn: `context_service.py` (B0.2)

**Đường dẫn file:** `src/datamate/b0/b02/context_service.py`  
**Thuộc module:** B0.2 Context Extractor & Business Rules  
**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)

---

## 1. Tổng Quan & Vai Trò

Tệp `context_service.py` đóng vai trò là **Dịch vụ Điều phối Trung tâm (Central Orchestrator Service)** của module chuẩn bị ngữ cảnh kinh doanh.

Lớp `BusinessContextService` là nơi lắp ghép tất cả các mắt xích của B0.1 và B0.2:
* Nhận dữ liệu thô từ `BaseMetadataProvider` (B0.1).
* Xây dựng cấu trúc cơ sở dữ liệu qua `SchemaCatalogBuilder` (B0.1).
* Đọc và số hóa quy tắc qua `BusinessRuleCompiler` (B0.2).
* Thẩm định và đóng gói thành phẩm qua `ContractBuilder` (B0.2).

---

## 2. Chi Tiết Lớp & Logic Thực Thi

### 2.1. Cấu Trúc Khởi Tạo (Dependency Injection)
```python
class BusinessContextService:
    def __init__(
        self,
        provider: BaseMetadataProvider,
        schema_builder: SchemaCatalogBuilder,
        rule_compiler: BusinessRuleCompiler,
        contract_builder: ContractBuilder,
    ) -> None:
        self.provider = provider
        self.schema_builder = schema_builder
        self.rule_compiler = rule_compiler
        self.contract_builder = contract_builder
```
Tất cả các thành phần phụ thuộc đều được tiêm vào (injected) qua hàm khởi tạo `__init__`. Điều này giúp việc viết unit test với các mock object cực kỳ thuận tiện và loại bỏ hoàn toàn sự phụ thuộc cứng vào tệp đĩa cụ thể.

### 2.2. Phương thức `prepare(business_id: str, documents: list[str | Path]) -> BusinessContext`
* **Bước 1**: Gọi `self.provider.load(business_id)` để lấy metadata từ Data Foundation. Kiểm tra đúng `business_id`.
* **Bước 2**: Gọi `self.schema_builder.build(...)` để phân tích khóa chính, khóa ghép và các quan hệ join giữa các bảng.
* **Bước 3**: Gọi `self.rule_compiler.ingest_documents(...)` để đọc danh sách các tệp Rulebook / README và sinh danh mục quy tắc `RuleCatalog`.
* **Bước 4**: Gọi `self.contract_builder.build(...)` để kiểm tra chéo tính hợp lệ giữa trường quy tắc và cột bảng, sau đó trả về đối tượng `BusinessContext` hoàn chỉnh.

---

## 3. Tại Sao Lại Code Như Vậy?

1. **Hoàn toàn độc lập với LLM & Không phụ thuộc Mạng (Deterministic & Offline)**:
   Toàn bộ quá trình chuẩn bị context chạy thuần túy bằng thuật toán Python chuẩn, không tốn bất kỳ một token API nào và không cần kết nối internet. Thời gian thực thi cực nhanh (dưới 10ms).
2. **Xử lý tài liệu linh hoạt (Document Warning Resilience)**:
   Nếu danh sách `documents` bị thiếu một tài liệu nào đó, hệ thống không làm sập tiến trình (crash) mà ghi nhận cảnh báo rõ ràng trong `RuleCatalog.warnings`, cho phép pipeline tiếp tục vận hành an toàn.

---

## 4. Ý Nghĩa & Ảnh Hưởng Đến Các Module Khác

* **CLI Runner (`src/datamate/__main__.py`)**: Sử dụng trực tiếp `BusinessContextService` để cung cấp giao diện dòng lệnh `python3 -m datamate --metadata ... --business-id ...`.
* **Module B0.3 (Text-to-SQL)**: Gọi `service.prepare()` trước mỗi phiên làm việc để lấy toàn bộ context truyền vào mô hình AI.

---

## 5. Nếu Không Có File Này Thì Sao?

* Caller phía ngoài (B0.3 hoặc CLI) sẽ phải tự tay gọi từng bước: đọc metadata, gọi schema builder, gọi rule compiler, rồi gọi contract builder. Điều này làm tăng mã nguồn lặp lại (boilerplate code) và dễ dẫn đến sai sót thứ tự thực thi giữa các module.

