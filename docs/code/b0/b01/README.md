# Thư Mục Tài Liệu Kỹ Thuật Module B0.1 (Data Loader & Schema/Join Catalog)

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Vị trí:** `docs/code/b0/b01/`

---

## 1. Mục Đích & Phạm Vi

Thư mục này chứa toàn bộ các bài giải thích chi tiết chuyên sâu cho **từng file mã nguồn** bên trong package `src/datamate/b0/b01/`.

Mỗi tài liệu phân tích cặn kẽ:
* Vai trò của file trong tầng Data Ingestion & Schema Profiling.
* Chi tiết từng Class, Phương thức, Hàm và thuật toán bên trong.
* **Tại sao lại code như vậy?** (Những cân nhắc kỹ thuật, bảo vệ tính toàn vẹn dữ liệu cuộc thi).
* Ý nghĩa & ảnh hưởng liên đới đến B0.2 Context, B0.3 LLM và B0.5 Output Gate.
* **Nếu không có file này thì sao?** (Kịch bản rủi ro, lỗi crash, lệch kết quả join).

---

## 2. Danh Mục Các Tệp Mã Nguồn

| Tệp Mã Nguồn | Tệp Tài Liệu Tương Ứng | Tóm Tắt Nhiệm Vụ |
|---|---|---|
| `__init__.py` | [`init.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b01/init.md) | Điểm công khai (Public Interface) đóng gói xuất khẩu các API lõi của B0.1. |
| `contracts.py` | [`contracts.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b01/contracts.md) | Định nghĩa các lớp dữ liệu bất biến: `TableMetadata`, `ColumnMetadata`, `JoinEdge`, `SchemaCatalog`. |
| `metadata_adapter.py` | [`metadata_adapter.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b01/metadata_adapter.md) | Bộ chuyển đổi tiếp nhận metadata JSON từ Data Foundation (version 1.0). |
| `schema_catalog.py` | [`schema_catalog.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b01/schema_catalog.md) | Trình xây dựng Catalog, phân tích tính duy nhất của khóa chính và grain dòng. |
| `join_graph.py` | [`join_graph.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b01/join_graph.md) | Xây dựng đồ thị quan hệ bảng, tìm đường join BFS và sinh biểu thức SQL equijoin. |

---

## 3. Sơ Đồ Phụ Thuộc Giữa Các File Trong B0.1

```text
               ┌─────────────────────────────┐
               │        contracts.py         │
               │  (Data Schemas & Metadata)  │
               └──────────────┬──────────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
metadata_adapter.py    schema_catalog.py       join_graph.py
 (JSON v1.0 Ingest)    (Keys & Grain Engine)  (Join Paths & Predicates)
       │                      │                      │
       └──────────────────────┼──────────────────────┘
                              ▼
                         __init__.py
                   (Public Package Exports)
```

