# Thư Mục Tài Liệu Kỹ Thuật Module B0.2 (Context Extractor & Business Rules)

**Dự án:** DataMate — Zalo AI Challenge 2026 (Track 2)  
**Nhóm thực hiện:** UIT Last Dance  
**Vị trí:** `docs/code/b0/b02/`

---

## 1. Mục Đích & Phạm Vi

Thư mục này chứa toàn bộ các bài giải thích chi tiết chuyên sâu cho **từng file mã nguồn** bên trong package `src/datamate/b0/b02/`.

Module B0.2 chịu trách nhiệm:
* Đọc và số hóa các quy tắc kế toán / bán lẻ từ tài liệu văn bản Markdown (Rulebook & README).
* Quản lý phân cấp mức độ ưu tiên và giải quyết xung đột quy tắc (Precedence & Conflict Resolution).
* Gắn kết công thức miền (Domain Formula Binding: doanh thu, lãi gộp, bán chạy).
* Đóng gói toàn bộ thông tin Schema (từ B0.1) và Quy tắc (từ B0.2) thành bản hợp đồng **`BusinessContext`**.

---

## 2. Danh Mục Các Tệp Mã Nguồn

| Tệp Mã Nguồn | Tệp Tài Liệu Tương Ứng | Tóm Tắt Nhiệm Vụ |
|---|---|---|
| `__init__.py` | [`init.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b02/init.md) | Điểm công khai (Public Interface) đóng gói xuất khẩu các API lõi của B0.2. |
| `contracts.py` | [`contracts.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b02/contracts.md) | Định nghĩa hợp đồng: `BusinessRule`, `RuleCatalog`, `BusinessContext`, và `ContractBuilder`. |
| `context_service.py` | [`context_service.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b02/context_service.md) | Dịch vụ điều phối (Orchestrator) kết hợp B0.1 và B0.2 thành `BusinessContext`. |
| `cli.py` | [`cli.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b02/cli.md) | Giao diện dòng lệnh (CLI) chạy pipeline trích xuất Business Context ra JSON. |
| `rule_compiler.py` | [`rule_compiler.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b02/rule_compiler.md) | Trình phân tích văn bản Markdown, sinh hash ID và biên dịch DSL quy tắc sang SQL fragment. |
| `rule_resolver.py` | [`rule_resolver.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b02/rule_resolver.md) | Lọc quy tắc theo phạm vi (Scope) và thang điểm ưu tiên (Precedence 100-400). |
| `rule_templates.py` | [`rule_templates.md`](file:///home/kiet97/uit-last-dance-aizalo26/docs/code/b0/b02/rule_templates.md) | Đối chiếu điều khoản nguyên văn cho 3 công thức: Doanh thu, Lãi gộp, Số lượng bán cơ bản. |

---

## 3. Sơ Đồ Phụ Thuộc Giữa Các File Trong B0.2

```text
               ┌─────────────────────────────┐
               │        contracts.py         │
               │ (BusinessRule, Context, CB) │
               └──────────────┬──────────────┘
                              │
       ┌──────────────────────┼──────────────────────┐
       ▼                      ▼                      ▼
rule_resolver.py       rule_compiler.py      rule_templates.py
(Precedence 100-400)   (DSL & Markdown Ingest)(Formula Templates)
       │                      │                      │
       └──────────────────────┼──────────────────────┘
                              ▼
                      context_service.py
                  (BusinessContextService Orchestrator)
                              ▼
                         __init__.py
                   (Public Package Exports)
```

