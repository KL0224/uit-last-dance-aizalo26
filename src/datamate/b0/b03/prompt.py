"""Xây dựng prompt chuẩn cho Text-to-SQL và Bounded Retry từ BusinessContext."""

from __future__ import annotations

import json
from typing import Any

from .types import ChatMessage

SYSTEM_INSTRUCTION = """Bạn là trợ lý AI chuyên gia phân tích dữ liệu và Text-to-SQL cho các doanh nghiệp Việt Nam (DataMate 2026).
Nhiệm vụ của bạn là nhận thông tin cấu trúc dữ liệu (Data Contract / Business Context), câu hỏi ngôn ngữ tự nhiên bằng tiếng Việt và ngày tham chiếu (as_of_date).

Sau đó, bạn cần:
1. Xác định câu hỏi là 'answerable' (có thể trả lời từ dữ liệu) hay 'unanswerable' (thiếu cột, thiếu bảng, hoặc vi phạm answerability constraints).
2. Nếu answerable:
   - Xác định answer_type phù hợp: 'number', 'percent', 'string', 'date', 'boolean', 'list', 'table'.
   - Viết câu truy vấn SQL chuẩn DuckDB (chỉ dùng cú pháp SELECT an toàn, không DML/DDL).
   - Liệt kê các bảng được sử dụng (tables_used).
   - Liệt kê các giả định (assumptions) nếu có.
3. Nếu unanswerable:
   - Ghi rõ lý do (reason) tại sao dữ liệu hiện tại không thể trả lời.

BẮT BUỘC chỉ trả về định dạng JSON thuần túy như sau:
```json
{
  "status": "answerable",
  "answer_type": "number",
  "sql": "SELECT COUNT(*) FROM valid_orders",
  "tables_used": ["valid_orders"],
  "assumptions": [],
  "reason": null
}
```
hoặc:
```json
{
  "status": "unanswerable",
  "answer_type": null,
  "sql": null,
  "tables_used": [],
  "assumptions": [],
  "reason": "Dữ liệu không chứa thông tin chi phí cần thiết"
}
```
Không giải thích lan man ngoài cấu trúc JSON trên.
"""


def format_context_for_prompt(context: Any) -> str:
    """Format đối tượng BusinessContext hoặc dict thành chuỗi mô tả ngữ cảnh rõ ràng."""
    if hasattr(context, "to_dict"):
        data = context.to_dict()
    elif isinstance(context, dict):
        data = context
    else:
        return str(context)

    sections = []

    # 1. Schema Tables
    schema_catalog = data.get("schema_catalog", {})
    tables = schema_catalog.get("tables", [])
    if tables:
        sections.append("### LƯỢC ĐỒ DỮ LIỆU (TABLE SCHEMAS):")
        for tbl in tables:
            tbl_name = tbl.get("name", "unknown")
            grain = tbl.get("grain")
            grain_str = f" (Ý nghĩa dòng: {grain})" if grain else ""
            cols_info = []
            for col in tbl.get("columns", []):
                col_name = col.get("name")
                c_type = col.get("data_type", "UNKNOWN")
                nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
                cols_info.append(f"  - {col_name} ({c_type}, {nullable})")
            pks = tbl.get("primary_key_candidates", [])
            pk_str = f" [Khóa chính: {', '.join(pks)}]" if pks else ""
            sections.append(f"Bảng: `{tbl_name}`{grain_str}{pk_str}\n" + "\n".join(cols_info))

    # 2. Join Relationships
    join_edges = schema_catalog.get("join_edges", [])
    if join_edges:
        sections.append("\n### QUAN HỆ JOIN (RELATIONSHIPS):")
        for edge in join_edges:
            sections.append(
                f"- `{edge.get('left_table')}`.{edge.get('left_column')} = "
                f"`{edge.get('right_table')}`.{edge.get('right_column')} "
                f"({edge.get('cardinality', 'unknown')})"
            )

    # 3. Business Rules
    rule_catalog = data.get("rule_catalog", {})
    rules = rule_catalog.get("rules", [])
    if rules:
        sections.append("\n### QUY TẮC NGHIỆP VỤ (BUSINESS RULES & METRICS):")
        for r in rules:
            rid = r.get("rule_id", "")
            rtext = r.get("text", "")
            rexpr = r.get("expression")
            expr_str = f" -> Biểu thức: {json.dumps(rexpr, ensure_ascii=False)}" if rexpr else ""
            sections.append(f"- [{rid}] {rtext}{expr_str}")

    # 4. Answerability Constraints
    constraints = data.get("answerability_constraints")
    if constraints:
        sections.append(f"\n### GIỚI HẠN DỮ LIỆU (CONSTRAINTS):\n{json.dumps(constraints, ensure_ascii=False, indent=2)}")

    return "\n".join(sections)


def build_text2sql_messages(
    context: Any, question: str, as_of_date: str
) -> list[ChatMessage]:
    """Tạo chuỗi messages cho chat API của LLM sinh câu truy vấn SQL ban đầu."""
    context_str = format_context_for_prompt(context)
    user_content = f"""{context_str}

### THÔNG TIN CÂU HỎI:
- Ngày tham chiếu (as_of_date): {as_of_date}
- Câu hỏi: "{question}"

Hãy phân tích và trả về kết quả theo đúng định dạng JSON yêu cầu."""

    return [
        ChatMessage(role="system", content=SYSTEM_INSTRUCTION),
        ChatMessage(role="user", content=user_content),
    ]


def build_repair_messages(
    context: Any,
    question: str,
    as_of_date: str,
    previous_sql: str,
    error_message: str,
) -> list[ChatMessage]:
    """Tạo chuỗi messages cho vòng Bounded Retry sửa lại câu SQL khi bị lỗi thực thi."""
    context_str = format_context_for_prompt(context)
    user_content = f"""{context_str}

### THÔNG TIN CÂU HỎI:
- Ngày tham chiếu (as_of_date): {as_of_date}
- Câu hỏi: "{question}"

### CÂU TRUY VẤN TRƯỚC ĐÓ ĐÃ BỊ LỖI THỰC THI:
```sql
{previous_sql}
```

### THÔNG BÁO LỖI (ERROR MESSAGE TỪ DATABASE/EXECUTOR):
```
{error_message}
```

Hãy đọc kỹ thông báo lỗi trên, sửa lại câu lệnh SQL cho chính xác, tương thích với schema và dữ liệu, sau đó trả về định dạng JSON yêu cầu."""

    return [
        ChatMessage(role="system", content=SYSTEM_INSTRUCTION),
        ChatMessage(role="user", content=user_content),
    ]

