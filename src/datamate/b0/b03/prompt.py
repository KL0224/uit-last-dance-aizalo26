"""Xây dựng prompt chuẩn cho Text-to-SQL và Bounded Retry từ BusinessContext."""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from .types import ChatMessage

SYSTEM_INSTRUCTION = """Bạn là trợ lý AI chuyên gia phân tích dữ liệu và Text-to-SQL chuẩn DuckDB cho các doanh nghiệp Việt Nam (DataMate 2026).
Nhiệm vụ của bạn là nhận thông tin cấu trúc dữ liệu (Data Contract / Business Context), các mẫu giá trị phân loại thực tế, biểu đồ liên kết (JOIN), quy tắc nghiệp vụ (Rulebook) và câu hỏi tự nhiên bằng tiếng Việt kèm ngày tham chiếu (as_of_date).

QUY TRÌNH XỬ LÝ & NGUYÊN TẮC BẮT BUỘC:

1. ĐỌC KỸ VÀ TUÂN THỦ NGHIỆP VỤ TỪ RULEBOOK (BUSINESS CONTEXT FIRST):
   - Mọi định nghĩa về chỉ số (Doanh thu, Đơn hợp lệ, Đơn huỷ, Công nợ, Đơn vị tính, Quy đổi, Xếp hạng, Tăng trưởng...) BẮT BUỘC phải làm theo đúng mục '### QUY TẮC NGHIỆP VỤ (BUSINESS RULES & METRICS)' được cung cấp trong ngữ cảnh của doanh nghiệp.
   - Đối chiếu định nghĩa trong Rulebook với mô tả cột (tên gốc, ý nghĩa) và các bảng trong lược đồ để chọn đúng bảng và cột tương ứng:
     + Khi Rulebook quy định tính theo dòng hàng (ví dụ: doanh thu một đơn là tổng thành tiền các dòng hàng sau giảm giá): Bắt buộc dùng bảng chi tiết đơn hàng (line items) và cột thành tiền của dòng, không dùng tổng bill trên đầu đơn (vì tổng bill đầu đơn có thể chứa phí vận chuyển hoặc giảm giá cả đơn ngoài quy định).
     + Khi Rulebook quy định loại trừ các đơn bị huỷ, đơn trả hàng, hoặc phương thức thanh toán không phải khách nợ (như COD, sàn TMĐT): Đối chiếu với cột trạng thái đơn và cột phương thức thanh toán để lọc đúng điều kiện.
     + Khi câu hỏi hỏi theo đơn vị tính cụ thể (ví dụ: số ly, số hộp, số viên): Đối chiếu với cột đơn vị cơ bản của bảng danh mục sản phẩm/hàng hóa để chỉ lọc các mặt hàng có đơn vị đó.
     + Khi bảng hàng hoá không có cột riêng cho thuộc tính (ví dụ không có cột size riêng, hoặc cột thuộc tính bị rỗng): BẮT BUỘC so khớp trực tiếp trên cột Tên sản phẩm/Tên hàng (cột có vai trò text/name) theo quy tắc ngành trong Rulebook: ví dụ `WHERE LOWER(col_ten_sp) LIKE '%(m)'` hoặc `LIKE '%(l)'`. TUYỆT ĐỐI KHÔNG lọc trên cột rỗng và KHÔNG kết luận unanswerable!
     + Khi câu hỏi hỏi đích danh một sản phẩm cụ thể kèm size (ví dụ "Cà phê sữa (L)"): BẮT BUỘC phải lọc CẢ tên mặt hàng VÀ kích cỡ: ví dụ `WHERE LOWER(col_ten_sp) LIKE '%cà phê sữa%' AND LOWER(col_ten_sp) LIKE '%(l)'`. Tuyệt đối không chỉ lọc riêng `%(l)` vì sẽ nhầm sang mọi mặt hàng size L khác!
     + QUY TẮC KHÁCH HÀNG (RULEBOOK MỤC 3): Khi câu hỏi hỏi về khách hàng (Ai mua nhiều nhất, khách hàng thân thiết, xếp hạng khách hàng, top khách hàng, đếm số khách hàng): "Khách lẻ", "kl", "lẻ", "khach le", "khách vãng lai" KHÔNG PHẢI là khách hàng cụ thể. BẮT BUỘC thêm điều kiện loại trừ: `WHERE LOWER(col_khach_hang) NOT IN ('khách lẻ', 'khach le', 'kl', 'lẻ', 'khách vãng lai', 'le') AND col_khach_hang IS NOT NULL AND TRIM(col_khach_hang) != '' AND LOWER(col_khach_hang) NOT LIKE 'tổng%'`. TUYỆT ĐỐI KHÔNG xếp hạng hay trả về 'khách lẻ'/'kl'/'lẻ'!
     + LOẠI TRỪ ĐƠN HUỶ & ĐƠN TRẢ: Trừ khi câu hỏi hỏi đích danh về đơn huỷ hoặc hàng trả lại, mọi truy vấn tính doanh thu, số đơn, mặt hàng bán chạy BẮT BUỘC loại trừ đơn huỷ/đổi trả: `WHERE LOWER(trang_thai) NOT IN ('cancelled', 'huỷ', 'hủy', 'đã huỷ', 'đã hủy', 'da huy', 'returned', 'trả hàng', 'hàng trả về', 'đổi trả', 'doi tra')`.
     + ĐẾM SỐ ĐƠN HÀNG TRÊN BẢNG DÒNG HÀNG: Khi bảng dữ liệu là bảng chi tiết dòng hàng (order lines/line items), để đếm số đơn hàng BẮT BUỘC dùng `COUNT(DISTINCT ma_don_hang)`. TUYỆT ĐỐI KHÔNG dùng `COUNT(*)` vì sẽ đếm nhầm số dòng sản phẩm thay vì số đơn hàng.
   - Luôn sử dụng đúng các giá trị thực tế liệt kê trong mục [Giá trị thực tế] của từng cột phân loại để so khớp điều kiện WHERE (không tự dịch hay suy đoán giá trị khác).

2. QUY TẮC SO SÁNH THỜI GIAN & CÚ PHÁP DUCKDB:
   - KÝ HIỆU THỜI GIAN TIẾNG VIỆT & TỪ ĐỊA PHƯƠNG:
     + `T{M}`, `Th{M}`, `Th {M}` (ví dụ: `T2`, `T3`, `Th 10`) luôn là **THÁNG M** (Month M), TUYỆT ĐỐI KHÔNG phải Quý (Quý luôn ký hiệu là `Q{N}`). Ví dụ `T2/2026` là Tháng 2/2026, chọn bảng T2 và lọc tháng 2/2026!
     + "Hôm nay", "bữa nay", "hôm ni", "bữa ni" = Đúng ngày hôm nay: `DATE(col) = DATE '{as_of_date}'`. TUYỆT ĐỐI KHÔNG dùng `<= '{as_of_date}'` (gây đếm dồn từ đầu tháng) và không gom nhiều ngày!
     + "Hôm qua", "bữa qua" = Đúng ngày hôm qua: `DATE(col) = (DATE '{as_of_date}' - INTERVAL 1 DAY)`. TUYỆT ĐỐI KHÔNG hiểu là 7 ngày gần nhất!
   - BẮT BUỘC LỌC THÁNG/NĂM TRÊN BẢNG PHÂN VÙNG: Các bảng phân vùng (ví dụ `ban_hang_t4`) có thể chứa dữ liệu của nhiều năm (cả 2025 và 2026). Khi câu hỏi hỏi tháng/năm cụ thể (ví dụ T4/2025), BẮT BUỘC phải có điều kiện lọc ngày tháng chính xác: `WHERE STRFTIME(ngay_dat_hang, '%Y-%m') = '2025-04'`. TUYỆT ĐỐI KHÔNG bỏ qua điều kiện ngày tháng chỉ vì bảng có tên `t4`!
   - SO SÁNH THỜI GIAN: Luôn so sánh NĂM (`YYYY`) trước, sau đó mới so sánh THÁNG (`MM`). Bất kỳ tháng nào của năm trước (ví dụ tháng 9, 11 của năm N) đều diễn ra TRƯỚC các tháng của năm sau (năm N+1). Tuyệt đối không so sánh riêng số tháng mà bỏ qua năm (không được coi tháng 9 hay 11 là tương lai chỉ vì `09 > 08` hay `11 > 08`). Dữ liệu có đầy đủ các tháng trong năm nếu năm đó nằm trong khoảng thời gian quan sát.
   - TĂNG / GIẢM PHẦN TRĂM (PERCENT GROWTH): Khi câu hỏi hỏi "tăng hay giảm mấy phần trăm" hoặc "thay đổi bao nhiêu phần trăm" so với kỳ trước / cùng kỳ:
     BẮT BUỘC phải tính tỷ lệ phần trăm theo công thức: ROUND(((doanh_thu_ky_nay - doanh_thu_ky_truoc) / doanh_thu_ky_truoc) * 100, 2). TUYỆT ĐỐI KHÔNG trả về số tiền chênh lệch tuyệt đối! answer_type BẮT BUỘC là 'percent'.
   - DUCKDB KHÔNG CÓ BẢNG `dual`: Khi tính toán biểu thức vô hướng hay tỉ lệ % giữa các CTE/subquery, chỉ cần viết trực tiếp `SELECT expr;` (TUYỆT ĐỐI KHÔNG thêm `FROM dual` hay `FROM information_schema`).
   - DATE/TIMESTAMP: TUYỆT ĐỐI KHÔNG dùng toán tử LIKE trên cột DATE/TIMESTAMP (gây Binder Error).
     + Lọc theo tháng: Dùng `STRFTIME(col, '%Y-%m') = 'YYYY-MM'`.
     + Lấy ngày hôm qua: Dùng `(DATE 'YYYY-MM-DD' - INTERVAL 1 DAY)`. KHÔNG dùng hàm `DATE_SUB`.
   - ÉP KIỂU SỐ (CASTING): Nếu cột số liệu đang mang kiểu VARCHAR trong schema, luôn dùng `TRY_CAST(col AS DOUBLE)` hoặc `TRY_CAST(col AS BIGINT)` khi tính toán SUM/AVG.
   - GIÁ TRỊ TRUNG BÌNH MỖI ĐƠN: Khi hỏi trung bình mỗi đơn, hãy tính `ROUND(SUM(tien_dong_hang) / COUNT(DISTINCT ma_don))` thay vì AVG dòng hàng.
   - LIÊN KẾT BẢNG (JOIN): Luôn sử dụng đúng các cặp khoá được nêu trong mục '### QUAN HỆ JOIN (RELATIONSHIPS)'.

3. ĐỊNH DẠNG ĐÁP ÁN (ANSWER TYPES & SHAPE):
   - 'number', 'percent', 'date', 'string', 'boolean': Kết quả trả về phải là SCALAR (chính xác 1 dòng và 1 cột).
     + Khi câu hỏi hỏi về một ngày/thời điểm cụ thể (ví dụ: ngày nào doanh thu cao nhất): answer_type là 'date' (hoặc 'string').
   - 'list': BẮT BUỘC dùng khi câu hỏi yêu cầu danh sách các thực thể hoặc Top N (Top 3, Top 5 mặt hàng bán chạy nhất, Top 5 khách hàng chi tiêu nhiều nhất, v.v.). TUYỆT ĐỐI KHÔNG dùng 'string' hay 'table' cho Top N!
     + Câu lệnh SQL CHỈ ĐƯỢC SELECT ĐÚNG 1 CỘT (chứa các giá trị tương ứng, mỗi dòng là một giá trị). Với câu hỏi Top-N, câu lệnh SELECT CHỈ LẤY ĐÚNG 1 CỘT Tên thực thể (ví dụ: tên món hàng, tên khách hàng), TUYỆT ĐỐI KHÔNG kèm cột tổng/điểm/số tiền (ví dụ: KHÔNG select doanh_thu hay tổng số lượng).
     + Cột SELECT bắt buộc phải là Tên thực thể (tên khách hàng, tên sản phẩm), KHÔNG chọn số điện thoại, mã barcode hay mã định danh trừ khi câu hỏi yêu cầu rõ mã.
     + TUYỆT ĐỐI KHÔNG viết tắt dấu '...' trong câu lệnh SQL!
   - 'table': Chỉ dùng khi câu hỏi yêu cầu bảng biểu đa chiều (nhiều cột).

4. QUY ĐỊNH VỀ 'unanswerable':
   - Chỉ trả về 'unanswerable' khi dữ liệu trong các bảng thực sự KHÔNG CÓ trường thông tin cần thiết và không thể tính toán được theo bất kỳ quy tắc nào trong Rulebook.
   - THIẾU CỘT NHÓM HÀNG / DANH MỤC: Nếu câu hỏi yêu cầu lọc, tính doanh thu hay so sánh theo "nhóm hàng", "danh mục", "nhóm trà", "nhóm cà phê" mà trong cấu trúc các bảng KHÔNG có cột danh mục / nhóm hàng -> BẮT BUỘC trả về 'unanswerable' (reason: "Dữ liệu không có thông tin nhóm hàng/danh mục"), TUYỆT ĐỐI KHÔNG tự phỏng đoán bằng LIKE '%trà%' hay LIKE '%cà phê%'!
   - Tuyệt đối không phán đoán unanswerable khi thông tin đã có trong các bảng hoặc có thể suy luận qua bảng liên kết (JOIN).

5. NGUYÊN TẮC SUY LUẬN & TRẢ VỀ:
   - Hãy đi thẳng vào kết quả JSON hoặc nếu suy luận thì suy luận CỰC KỲ NGẮN GỌN trong <think>...</think> (dưới 150 từ) theo 3 bước: bảng & thời gian -> điều kiện WHERE/JOIN -> DuckDB SQL.
   - TUYỆT ĐỐI KHÔNG viết "Thinking Process:" hay phân tích dài dòng bằng tiếng Anh bên ngoài thẻ <think>!
   - KHI HOÀN THÀNH SUY LUẬN: Đóng ngay thẻ </think> và xuất trực tiếp khối ```json ... ```. TUYỆT ĐỐI KHÔNG viết thêm bất kỳ câu văn xuôi giải thích nào sau thẻ </think>!
   - Khối kết quả cuối cùng BẮT BUỘC phải là một khối JSON hợp lệ duy nhất nằm trong ```json ... ```:
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
  "missing_fields": ["chi_phi"],
  "reason": "Dữ liệu không chứa thông tin chi phí cần thiết"
}
```
Không giải thích lan man ngoài cấu trúc JSON trên.
"""


def _norm(text: Any) -> str:
    return " ".join(unicodedata.normalize("NFC", str(text)).casefold().split())


def _detect_industry(data: dict[str, Any]) -> str | None:
    """Tự động suy luận ngành nghề (Cà phê, Nhà thuốc, Vật liệu xây dựng) từ metadata hoặc nội dung tài liệu."""
    explicit = (data.get("business_metadata") or {}).get("industry")
    if explicit:
        return explicit
    rule_catalog = data.get("rule_catalog", {})
    rules = rule_catalog.get("rules", [])
    biz_text = " ".join([r.get("text", "") for r in rules if r.get("scope") == "business"]).lower()

    schema_catalog = data.get("schema_catalog", {})
    for tbl in schema_catalog.get("tables", []):
        biz_text += " " + tbl.get("name", "").lower()
        for c in tbl.get("columns", []):
            biz_text += " " + str(c.get("provenance") or "").lower()

    if any(k in biz_text for k in ["cà phê", "cafe", "trà", "sinh tố", "nước ép", "quán", "croissant"]):
        return "Cà phê"
    if any(k in biz_text for k in ["thuốc", "kê đơn", "dược", "hoạt chất", "bệnh"]):
        return "Nhà thuốc"
    if any(k in biz_text for k in ["vật liệu", "xi măng", "gạch", "cát", "thép", "đợt giao"]):
        return "Vật liệu xây dựng"
    return None


def _select_rules(rules: list[dict], industry: str | None) -> list[dict]:
    """Industry filter, then keep only top-precedence rules per topic."""
    kept = [r for r in rules if r.get("status") != "invalid"]
    if industry:
        kept = [
            r
            for r in kept
            if r.get("scope") != "industry" or _norm(r.get("industry") or "") == _norm(industry)
        ]
    else:
        # Khi chưa xác định industry, chỉ lấy quy tắc chung (global/business), tránh đem quy tắc ngành khác vào
        kept = [r for r in kept if r.get("scope") != "industry"]
    best: dict[str, int] = {}
    for r in kept:
        topic = r.get("topic")
        if topic:
            best[_norm(topic)] = max(best.get(_norm(topic), 0), r.get("precedence") or 0)
    return [
        r
        for r in kept
        if not r.get("topic") or (r.get("precedence") or 0) >= best[_norm(r["topic"])]
    ]


def format_context_for_prompt(context: Any, industry: str | None = None) -> str:
    """Format đối tượng BusinessContext hoặc dict thành chuỗi mô tả ngữ cảnh rõ ràng."""
    if hasattr(context, "to_dict"):
        data = context.to_dict()
    elif isinstance(context, dict):
        data = context
    else:
        return str(context)

    sections = []
    if not industry:
        industry = _detect_industry(data)
    industry_known = bool(industry)

    # 1. Schema Tables
    schema_catalog = data.get("schema_catalog", {})
    tables = schema_catalog.get("tables", [])
    key_candidates = schema_catalog.get("key_candidates", []) or []
    cat_samples = data.get("categorical_samples", {})
    all_mapping = (data.get("business_metadata") or {}).get("schema_mapping", {})
    if tables:
        sections.append("### LƯỢC ĐỒ DỮ LIỆU (TABLE SCHEMAS):")
        # Nhóm các bảng phân vùng có cùng cấu trúc cột (ví dụ ban_hang_t1, ban_hang_t2...)
        # để tránh lặp lại cùng một schema 15-25 lần làm tràn context window
        grouped_tables: dict[tuple, list[dict]] = {}
        for tbl in tables:
            cols_sig = tuple((c.get("name"), c.get("data_type")) for c in tbl.get("columns", []))
            grouped_tables.setdefault(cols_sig, []).append(tbl)

        for cols_sig, tbl_list in grouped_tables.items():
            if len(tbl_list) > 2:
                names = ", ".join(f"`{t.get('name')}`" for t in tbl_list)
                first_tbl = tbl_list[0]
                grain = first_tbl.get("grain")
                grain_str = f" (Ý nghĩa dòng: {grain})" if grain else ""
                cols_info = []
                for col in first_tbl.get("columns", []):
                    col_name = col.get("name")
                    c_type = col.get("data_type", "UNKNOWN")
                    nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
                    original = col.get("provenance")
                    original_str = (
                        f' [tên gốc: "{original}"]'
                        if original and original != col_name and len(str(original)) <= 60
                        else ""
                    )
                    samples = None
                    for t in tbl_list:
                        s = cat_samples.get(t.get("name"), {}).get(col_name)
                        if s:
                            samples = s
                            break
                    samples_str = f" [Giá trị thực tế: {samples}]" if samples else ""
                    cols_info.append(f"  - {col_name} ({c_type}, {nullable}){original_str}{samples_str}")
                sections.append(
                    f"Tập bảng cùng cấu trúc ({len(tbl_list)} bảng phân vùng theo kỳ):\n"
                    f"  Các bảng: {names}{grain_str}\n" + "\n".join(cols_info)
                )
            else:
                for tbl in tbl_list:
                    tbl_name = tbl.get("name", "unknown")
                    grain = tbl.get("grain")
                    grain_str = f" (Ý nghĩa dòng: {grain})" if grain else ""
                    cols_info = []
                    schema_mapping = all_mapping.get(tbl_name, {}).get("columns", {})
                    for col in tbl.get("columns", []):
                        col_name = col.get("name")
                        c_type = col.get("data_type", "UNKNOWN")
                        nullable = "NULL" if col.get("nullable", True) else "NOT NULL"
                        original = col.get("provenance")
                        original_str = (
                            f' [tên gốc: "{original}"]'
                            if original and original != col_name and len(str(original)) <= 60
                            else ""
                        )
                        role = schema_mapping.get(col_name, {}).get("role")
                        role_str = f" [vai trò: {role}]" if role and role != "unknown" else ""
                        samples = cat_samples.get(tbl_name, {}).get(col_name)
                        samples_str = f" [Giá trị thực tế: {samples}]" if samples else ""
                        cols_info.append(f"  - {col_name} ({c_type}, {nullable}){original_str}{role_str}{samples_str}")
                    pks = [str(pk) for pk in tbl.get("primary_key_candidates", []) or []]
                    for key in key_candidates:
                        if key.get("table") == tbl_name and key.get("status") != "invalid":
                            joined = "+".join(key.get("columns", []))
                            if joined and joined not in pks:
                                pks.append(joined)
                    pk_str = f" [Khóa chính: {', '.join(pks)}]" if pks else ""
                    sections.append(f"Bảng: `{tbl_name}`{grain_str}{pk_str}\n" + "\n".join(cols_info))

    # 2. Join Relationships (B0.1 contract name is join_graph; join_edges is legacy)
    join_edges = schema_catalog.get("join_graph") or schema_catalog.get("join_edges") or []
    join_edges = [e for e in join_edges if e.get("status") != "invalid"]
    if join_edges:
        sections.append("\n### QUAN HỆ JOIN (RELATIONSHIPS):")
        for edge in join_edges:
            pairs = [(edge.get("left_column"), edge.get("right_column"))]
            pairs += [tuple(p) for p in edge.get("additional_key_pairs") or []]
            condition = " AND ".join(
                f"`{edge.get('left_table')}`.{left} = `{edge.get('right_table')}`.{right}"
                for left, right in pairs
            )
            sections.append(f"- {condition} ({edge.get('cardinality', 'unknown')})")

    # 2b. Observed date ranges from data profiling help LLM choose valid filters.
    profiling = data.get("data_profiling") or {}
    ranges = []
    for tbl_name, tbl_profile in profiling.items():
        columns = tbl_profile.get("columns", {}) if isinstance(tbl_profile, dict) else {}
        for col_name, stats in columns.items():
            if isinstance(stats, dict) and stats.get("observed_min") is not None:
                obs_min = str(stats["observed_min"])
                obs_max = str(stats.get("observed_max"))
                start_year = obs_min[:4]
                end_year = obs_max[:4]
                if start_year.isdigit() and end_year.isdigit() and int(start_year) <= int(end_year):
                    years_span = " → ".join(str(y) for y in range(int(start_year), int(end_year) + 1))
                    detail = (
                        f" (Dữ liệu trải dài qua các năm: {years_span}. "
                        f"Mọi tháng trong các năm trước năm kết thúc đều có đầy đủ dữ liệu)"
                        if int(start_year) < int(end_year)
                        else ""
                    )
                else:
                    detail = ""
                ranges.append(
                    f"- {tbl_name}.{col_name}: từ {obs_min} đến {obs_max}{detail}"
                )
    if ranges:
        sections.append("\n### PHẠM VI THỜI GIAN QUAN SÁT ĐƯỢC (DATA PROFILING):")
        sections.extend(ranges)

    # 3. Business Rules: drop other industries, keep the highest precedence per topic
    rule_catalog = data.get("rule_catalog", {})
    rules = _select_rules(
        rule_catalog.get("rules", []),
        industry or (data.get("business_metadata") or {}).get("industry"),
    )
    if rules:
        sections.append("\n### QUY TẮC NGHIỆP VỤ (BUSINESS RULES & METRICS):")
        for r in rules:
            rid = r.get("rule_id", "")
            rtext = r.get("text", "")
            rexpr = r.get("expression")
            expr_str = f" -> Biểu thức: {json.dumps(rexpr, ensure_ascii=False)}" if rexpr else ""
            label = (
                f"[Ngành: {r['industry']}] "
                if r.get("scope") == "industry" and r.get("industry") and not industry_known
                else ""
            )
            sections.append(f"- [{rid}] {label}{rtext}{expr_str}")

    # 4. Answerability Constraints
    constraints = data.get("answerability_constraints")
    if constraints:
        sections.append(f"\n### GIỚI HẠN DỮ LIỆU (CONSTRAINTS):\n{json.dumps(constraints, ensure_ascii=False, indent=2)}")

    return "\n".join(sections)


def build_text2sql_messages(
    context: Any, question: str, as_of_date: str, industry: str | None = None
) -> list[ChatMessage]:
    """Tạo chuỗi messages cho chat API của LLM sinh câu truy vấn SQL ban đầu."""
    context_str = format_context_for_prompt(context, industry)
    user_content = f"""{context_str}

### THÔNG TIN CÂU HỎI:
- Ngày tham chiếu (as_of_date): {as_of_date}
- Câu hỏi: "{question}"

YÊU CẦU ĐẦU RA:
- Nếu suy luận, hãy đặt suy luận trong <think>...</think>.
- Kết quả cuối cùng BẮT BUỘC là 1 khối JSON hợp lệ nằm trong ```json ... ```."""

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
    industry: str | None = None,
) -> list[ChatMessage]:
    """Tạo chuỗi messages cho vòng Bounded Retry sửa lại câu SQL khi bị lỗi thực thi."""
    context_str = format_context_for_prompt(context, industry)
    if previous_sql and previous_sql.strip():
        sql_section = f"""### CÂU TRUY VẤN TRƯỚC ĐÓ ĐÃ BỊ LỖI THỰC THI:
```sql
{previous_sql}
```"""
    else:
        sql_section = """### LƯU Ý Ở LẦN THỰC THI TRƯỚC:
Ở lần trước mô hình chưa xuất được khối JSON hợp lệ hoặc câu SQL bị lỗi cú pháp."""

    user_content = f"""{context_str}

### THÔNG TIN CÂU HỎI:
- Ngày tham chiếu (as_of_date): {as_of_date}
- Câu hỏi: "{question}"

{sql_section}

### THÔNG BÁO LỖI (ERROR MESSAGE TỪ DATABASE/EXECUTOR):
```
{error_message}
```

YÊU CẦU SỬA ĐỔI:
- Hãy đọc kỹ thông báo lỗi trên, sửa lại câu lệnh SQL cho chính xác, tương thích với schema và dữ liệu.
- Lưu ý: Giữ lại toàn bộ các CTE cần thiết (WITH ...), không gọi trực tiếp tên CTE như bảng vật lý nếu chưa định nghĩa.
- BẮT BUỘC viết đầy đủ câu lệnh SQL hoàn chỉnh, TUYỆT ĐỐI KHÔNG dùng dấu ba chấm '...' để viết tắt các mệnh đề FROM/JOIN/WHERE.
- Nếu câu hỏi hỏi Top N hoặc danh sách, câu lệnh SELECT CHỈ ĐƯỢC LẤY ĐÚNG 1 CỘT Tên thực thể.
- Nếu suy luận, hãy suy luận ngắn gọn trong <think>...</think>.
- Kết quả cuối cùng BẮT BUỘC là 1 khối JSON hợp lệ nằm trong ```json ... ```."""

    return [
        ChatMessage(role="system", content=SYSTEM_INSTRUCTION),
        ChatMessage(role="user", content=user_content),
    ]

