# INPUT

**Data Contract (JSON)**  
Chứa thông tin về business, được tạo từ RULEBOOK, README và dữ liệu bảng.   
Bao gồm: 

- **Table Schema** (tên bảng, cột, kiểu dữ liệu, quan hệ),   
- **Data Profiling** (row count, null%, cardinality, date range,...),   
- **Semantic Rules** (định nghĩa metrics, business rules, điều kiện lọc, công thức tính toán),   
- **Business Metadata** (trạng thái đơn, tên sản phẩm, quy đổi đơn vị,...) và  
- **Answerability Constraints** (giới hạn dữ liệu có thể trả lời).

**Question**  
Câu hỏi ngôn ngữ tự nhiên bằng tiếng Việt, có thể chứa từ viết tắt, không dấu hoặc cách diễn đạt không chuẩn.

**as\_of\_date**  
Ngày tham chiếu dùng để xác định các biểu thức thời gian tương đối như "hôm nay", "hôm qua", "tháng trước",...

# OUTPUT

	JSON gồm SQL và quyết định answerability sơ bộ 

	

```
{
  "status": "answerable",
  "answer_type": "number",
  "sql": "SELECT COUNT(*) FROM valid_orders",
  "tables_used": ["valid_orders"],
  "assumptions": [],
  "reason": null
}
```

```
{
  "status": "unanswerable",
  "answer_type": null,
  "sql": null,
  "tables_used": [],
  "assumptions": [],
  "reason": "Required cost data is not available"
}
```