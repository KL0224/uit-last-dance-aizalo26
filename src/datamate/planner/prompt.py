"""Xây dựng prompt chuẩn cho Text-to-SQL và Bounded Retry từ BusinessContext."""

from __future__ import annotations

import json
import unicodedata
from typing import Any

from .types import ChatMessage

SYSTEM_INSTRUCTION = """Bạn là trợ lý AI chuyên gia phân tích dữ liệu và Text-to-SQL chuẩn DuckDB cho các doanh nghiệp Việt Nam (DataMate 2026).
Nhiệm vụ của bạn là nhận thông tin cấu trúc dữ liệu (Data Contract / Business Context), các mẫu giá trị phân loại thực tế, biểu đồ liên kết (JOIN), chỉ số nghiệp vụ, quy tắc nghiệp vụ (Rulebook) và câu hỏi tự nhiên bằng tiếng Việt kèm ngày tham chiếu (as_of_date).

QUY TRÌNH XỬ LÝ & NGUYÊN TẮC BẮT BUỘC:

1. TUÂN THỦ NGHIỆP VỤ TỪ NGỮ CẢNH (BUSINESS CONTEXT FIRST):
   - Mọi định nghĩa về chỉ số (Doanh thu, Đơn hợp lệ, Đơn huỷ, Công nợ, Đơn vị tính, Quy đổi, Xếp hạng, Tăng trưởng...) BẮT BUỘC phải làm theo đúng mục '### QUY TẮC NGHIỆP VỤ' và '### CHỈ SỐ NGHIỆP VỤ ĐÃ ĐỐI CHIẾU' trong ngữ cảnh.
   - Đối chiếu quy tắc nghiệp vụ với mô tả cột và [Giá trị thực tế] trong schema để chọn đúng bảng và lọc đúng giá trị.
   - Sử dụng các cặp khóa trong mục '### QUAN HỆ JOIN' và '### GỢI Ý LIÊN KẾT BẢNG NGHIỆP VỤ' để liên kết dữ liệu.
   - Khi một thực thể (dòng sản phẩm, đời máy, dịch vụ) nằm trong cột văn bản mô tả tự do: Dùng điều kiện tìm kiếm chuỗi linh hoạt `LOWER(cột) LIKE '%từ_khóa%'`.
   - Lọc thực thể không phân biệt khoảng trắng: Dùng `REPLACE(LOWER(cột), ' ', '') LIKE '%tên_viết_liền%'` để bao quát cả trường hợp nhập liệu viết liền hoặc viết rời.
   - 'Tiệm mình / Quán mình / Shop mình / Cửa hàng mình': Là cách xưng hô chỉ toàn bộ cửa hàng. Truy vấn trên toàn bộ dữ liệu đơn hàng hiện có, không tìm cột `ten_tiem` hay đánh dấu unanswerable.

2. CÚ PHÁP DUCKDB & MỆNH ĐỀ SQL BẮT BUỘC:
   - TOÁN TỬ TÌM KIẾM CHUỖI (LIKE vs =):
     + Khi so khớp mẫu chuỗi có ký tự đại diện `%` hoặc `_`, BẮT BUỘC dùng `LIKE` hoặc `ILIKE` (ví dụ: `WHERE LOWER(col) LIKE '%từ_khóa%'`).
     + TUYỆT ĐỐI KHÔNG dùng dấu `=` khi có ký tự `%` (ví dụ: `WHERE col = '%abc%'` là sai cú pháp và luôn trả về rỗng).
   - MỆNH ĐỀ GROUP BY:
     + Khi câu lệnh SELECT chỉ tính một giá trị tổng hợp vô hướng (SUM, COUNT, AVG) cho một đối tượng đơn lẻ: TUYỆT ĐỐI KHÔNG thêm `GROUP BY 1` hay bất kỳ mệnh đề GROUP BY nào (DuckDB sẽ báo lỗi Binder).
     + Khi có `GROUP BY`, mọi cột không nằm trong hàm tổng hợp xuất hiện ở `SELECT` BẮT BUỘC phải nằm trong mệnh đề `GROUP BY`.
     + Khi JOIN bảng nhật ký/giao dịch với bảng danh mục: `GROUP BY` theo khóa chính / họ tên chuẩn của bảng danh mục để gom nhóm đúng thực thể.
     + Khi tính chỉ số cho 1 người / đối tượng cụ thể (hỏi bao nhiêu tiền, bao nhiêu đơn, hoa hồng): BẮT BUỘC tính `SUM(...)` gom toàn bộ các biến thể tên gọi của người đó về đúng 1 giá trị SCALAR (1 dòng 1 cột). TUYỆT ĐỐI KHÔNG `GROUP BY` theo cột tên thô/tên gọi tắt trong CTE gây phân mảnh ra nhiều dòng!
   - ÉP KIỂU SỐ (CASTING): Nếu cột số liệu mang kiểu VARCHAR trong schema, luôn dùng `TRY_CAST(cột AS DOUBLE)` hoặc `TRY_CAST(cột AS BIGINT)` khi tính toán SUM/AVG.
   - LÀM TRÒN TIỀN TỆ: Số tiền luôn làm tròn về đồng với hàm chuẩn `ROUND(biểu_thức, 0)`. Tuyệt đối không cộng thủ công `+ 0.5`.
   - TÍNH TĂNG / GIẢM PHẦN TRĂM: Tỷ lệ phần trăm tính theo `ROUND((ky_nay - ky_truoc) / ky_truoc * 100, 2)`. Giữ nguyên dấu: kỳ này giảm so với kỳ trước thì kết quả phải âm. Chỉ SELECT duy nhất con số vô hướng, TUYỆT ĐỐI KHÔNG ghép chữ 'Tăng', 'Giảm', '%' vào kết quả SQL.
   - THỜI GIAN:
     + 'Hôm nay' = `DATE(col) = DATE '{as_of_date}'`. 'Hôm qua' = `DATE(col) = (DATE '{as_of_date}' - INTERVAL 1 DAY)`.
     + Tháng M/Y: `WHERE STRFTIME(col, '%Y-%m') = 'YYYY-MM'`. Ký hiệu `T{M}`, `Th{M}` luôn là Tháng M.
     + Tuyệt đối không dùng toán tử LIKE trên cột DATE/TIMESTAMP.
   - BÍ DANH (ALIAS) & CTE:
     + Dùng bí danh an toàn: `t1`, `t2`, `sub`. CẤM dùng từ khóa SQL dự trữ làm alias (`ON`, `AS`, `IN`, `WHERE`, `ORDER`, `GROUP`).
     + DuckDB không có bảng `dual`. Khi dùng CTE, câu lệnh SELECT cuối cùng bắt buộc phải có `FROM`.
   - CỘT NULL TRONG WHERE: Khi lọc loại trừ trên cột có thể NULL, TUYỆT ĐỐI KHÔNG dùng `LOWER(col) NOT IN (...)` đơn thuần (vì trong SQL, `NULL NOT IN (...)` trả về UNKNOWN khiến toàn bộ dòng có col IS NULL bị loại bỏ oan uổng!). BẮT BUỘC dùng: `(col IS NULL OR LOWER(col) NOT IN (...))` hoặc `(col IS NULL OR LOWER(col) NOT LIKE '%từ%')`.
   - QUY ĐỔI ĐƠN VỊ TÍNH (UNIT CONVERSIONS):
     + Nếu có bảng `unit_conversions` hoặc cột quy đổi: Khi câu hỏi hỏi bán được bao nhiêu <đơn vị cơ bản> (ví dụ hỏi bao nhiêu 'cây' mà bảng bán hàng ghi 'bó'): BẮT BUỘC áp dụng nhân hệ số quy đổi.
   - DOANH THU THEO TÀI LIỆU (REVENUE METRIC):
     + Nếu schema có cột `gia_tri_hang` và Rulebook quy định doanh thu bán hàng tính theo giá trị hàng (như đơn hàng sàn TMĐT có giảm giá/phí ship riêng): BẮT BUỘC dùng `SUM(gia_tri_hang)` làm doanh thu thay vì `tong_tien`.
   - SO SÁNH CÁC THÁNG (WHICH MONTH):
     + Khi câu hỏi yêu cầu so sánh các tháng xem 'tháng nào bán được nhiều tiền nhất / ít tiền nhất': answer_type là 'date', kết quả trả về đúng định dạng 'YYYY-MM' (ví dụ '2025-05'). TUYỆT ĐỐI KHÔNG trả về chữ văn xuôi 'Tháng 5/2025'.

3. ĐỊNH DẠNG ĐÁP ÁN (ANSWER TYPES & SHAPE):
   - 'number', 'percent', 'date', 'string', 'boolean': Kết quả trả về phải là SCALAR (đúng 1 dòng và 1 cột).
     + Khi câu hỏi hỏi duy nhất 1 đối tượng, 1 nhân viên, 1 món hàng: answer_type là 'string', SELECT đúng 1 cột tên thực thể với `ORDER BY ... LIMIT 1`.
   - 'list': Dùng khi câu hỏi yêu cầu danh sách hoặc Top N. Câu lệnh SQL CHỈ SELECT ĐÚNG 1 CỘT Tên thực thể, TUYỆT ĐỐI KHÔNG kèm cột phụ/doanh thu/số lượng.
   - 'table': Dùng khi câu hỏi bắt đầu bằng hoặc có chữ 'Bảng...' ('Bảng doanh thu...', 'Bảng hoa hồng...'). Câu lệnh SQL CHỈ SELECT ĐÚNG 2 CỘT: Cột 1 là Tên thực thể từ bảng danh mục, Cột 2 là Chỉ số đo lường chính.

4. QUY ĐỊNH VỀ 'unanswerable':
   - Chỉ trả về 'unanswerable' khi dữ liệu thực sự không có cột/bảng cần thiết và không thể tính toán được từ các bảng hiện có hay quy tắc nghiệp vụ.
   - Tuyệt đối không đánh dấu unanswerable khi thông tin có thể tìm qua tìm kiếm chuỗi (`LIKE`), liên kết bảng (`JOIN`), hay công thức tính toán.
   - Câu hỏi hỏi tiêu chí định tính, chủ quan không có cột đo lường và Rulebook không định nghĩa (ví dụ: 'thợ nhiệt tình nhất', 'nhân viên vui vẻ nhất'): Trả về 'unanswerable'.
   - Câu hỏi yêu cầu lọc/nhóm theo 'nhóm hàng', 'danh mục' mà cơ sở dữ liệu hoàn toàn không có cột danh mục: Trả về 'unanswerable'.

5. ĐẦU RA JSON BẮT BUỘC:
   - Nếu suy luận, đặt suy luận CỰC KỲ NGẮN GỌN trong <think>...</think> (dưới 150 từ).
   - Kết quả cuối cùng BẮT BUỘC là 1 khối JSON hợp lệ duy nhất trong ```json ... ```:
```json
{
  "status": "answerable",
  "answer_type": "number",
  "sql": "SELECT COUNT(*) FROM ...",
  "tables_used": ["..."],
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
  "missing_fields": ["ten_truong"],
  "reason": "Lý do ngắn gọn bằng tiếng Việt"
}
```
Không giải thích lan man ngoài cấu trúc JSON trên.
"""


def _norm(text: Any) -> str:
    return " ".join(unicodedata.normalize("NFC", str(text or "")).casefold().split())


def _is_submission_format_rule(rule: dict) -> bool:
    """Loại bỏ các quy tắc chấm thi/format file submission.jsonl không liên quan tới SQL."""
    topic = _norm(rule.get("topic") or "")
    text = _norm(rule.get("text") or "")
    if any(
        k in text
        for k in [
            "submission.jsonl",
            "mỗi type có một format",
            "đúng format rồi mới so",
            "chấm tự động",
            "đúng +1, sai −1",
            "đúng +1, sai -1",
            "trường `reason` không bắt buộc",
            "trường reason không bắt buộc",
            "mọi đáp án chuẩn tính theo các luật dưới đây",
        ]
    ):
        return True
    if topic in {"number", "percent", "date", "boolean", "string", "unanswerable"}:
        return True
    if topic in {"list", "table"} and any(
        marker in text
        for marker in ("json", "mảng", "object", "columns", "rows", "một format")
    ):
        return True
    if any(
        text.startswith(k)
        for k in [
            "- **số, phần trăm:**",
            "- số, phần trăm:",
            "- **làm tròn:**",
            "- làm tròn:",
            "- **chuỗi:**",
            "- chuỗi:",
        ]
    ):
        return True
    return False


CORE_SPLIT_TOPICS = {
    "doanh thu",
    "đơn tính vào doanh thu",
    "đơn bị huỷ",
    "số đơn",
    "doanh thu một đơn",
    "bán được bao nhiêu tiền, thu về bao nhiêu tiền",
    "hôm nay",
    "tháng m/y",
    "tháng này",
    "tháng m, quý q không ghi năm",
    "ngày x, hôm nay, hôm qua",
    "tên gọi, nhãn",
    "sổ không có cột trạng thái",
    "trạng thái đơn",
    "hai dòng của **cùng một đơn** giống nhau ở mọi ô",
    "bảng không ghi theo đơn",
    "ô để trống ở các dòng sau của cùng một nhóm dòng",
}

TOPIC_TRIGGERS = {
    ("khách", "khách hàng", "khách lẻ", "nhóm khách", "khách sộp", "khách trung thành"): [
        "khách", "ai mua", "khach", "người mua", "sộp", "vãng lai", "khách quen"
    ],
    ("nhân viên", "thợ"): [
        "thợ", "tho", "nhân viên", "ai làm", "chăm chỉ", "bán giỏi", "hoa hồng", "huê hồng", "lương"
    ],
    ("nợ", "công nợ", "tuổi nợ", "hạn nợ"): [
        "nợ", "công nợ", "gối đầu", "thu nợ", "trả nợ", "thiếu", "tuổi nợ", "hạn nợ"
    ],
    ("tồn", "hết hàng", "kho"): [
        "tồn", "kho", "hết hàng", "còn hàng", "hàng tồn"
    ],
    ("lãi", "giá vốn", "lợi nhuận"): [
        "lãi", "lợi nhuận", "giá vốn", "vốn", "lời", "lãi gộp", "lãi ròng"
    ],
    ("nhà cung cấp", "nhập"): [
        "nhà cung cấp", "ncc", "nhập hàng", "tiền nhập", "nhập", "lần nhập"
    ],
    ("ca", "tiền mặt"): [
        "ca sáng", "ca chiều", "theo ca", "tiền mặt", "báo cáo ca"
    ],
    ("tết", "dịp tết", "mùa tết"): [
        "tết", "nguyên đán", "âm lịch", "chạp", "mùng"
    ],
    ("tăng trưởng", "phần trăm", "chênh lệch", "hơn / kém", "thay đổi"): [
        "tăng", "giảm", "thay đổi", "chênh lệch", "%", "phần trăm", "tỷ lệ", "tỉ lệ", "hơn", "kém", "so với"
    ],
    ("giờ cao điểm", "đắt khách"): [
        "giờ cao điểm", "khung giờ", "giờ đắt khách", "ngày đắt khách"
    ],
    ("đơn vị", "quy đổi"): [
        "đơn vị", "quy đổi", "ly", "thùng", "hộp", "lon", "gói", "chai", "viên", "vỉ"
    ],
    ("bán chạy", "ưa chuộng", "mặt hàng", "món"): [
        "bán chạy", "ưa chuộng", "mặt hàng", "món", "sản phẩm bán"
    ],
    ("n ngày gần nhất",): [
        "ngày gần nhất", "ngày qua", "ngày gần đây", "gần nhất"
    ],
    ("tỉ lệ đơn huỷ",): [
        "huỷ", "hủy", "tỉ lệ huỷ", "tỷ lệ huỷ", "bị huỷ"
    ],
    ("thanh toán", "cod", "sàn"): [
        "chuyển khoản", "tiền mặt", "thanh toán", "cod", "sàn", "tmđt", "shopee", "tiki", "lazada", "grab"
    ],
    ("trung bình",): [
        "trung bình", "bình quân", "mỗi ngày"
    ],
    ("quá", "từ x đến y", "hết ngày"): [
        "quá", "trên", "dưới", "từ đầu năm", "hết ngày", "đến nay"
    ],
}


def _detect_industry(data: dict[str, Any]) -> str | None:
    """Tự động suy luận ngành nghề (Sửa xe, Cửa hàng điện thoại, Mẹ và bé, Cà phê, Nhà thuốc, Vật liệu xây dựng) từ metadata hoặc nội dung tài liệu."""
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

    if any(k in biz_text for k in ["sửa xe", "suaxe", "xe máy", "biển số", "phụ tùng", "thay nhớt", "làm xe", "tiệm xe", "sổ sửa xe"]):
        return "Sửa xe"
    if any(k in biz_text for k in ["điện thoại", "dienthoai", "iphone", "samsung", "thu cũ", "đổi mới", "trả góp", "gb", "imei"]):
        return "Cửa hàng điện thoại"
    if any(k in biz_text for k in ["mẹ và bé", "me va be", "bỉm", "tã", "sữa bột", "sơ sinh"]):
        return "Mẹ và bé"
    if any(k in biz_text for k in ["cà phê", "cafe", "trà", "sinh tố", "nước ép", "quán", "croissant", "đồ uống"]):
        return "Cà phê"
    if any(k in biz_text for k in ["thuốc", "kê đơn", "dược", "hoạt chất", "bệnh", "dược phẩm"]):
        return "Nhà thuốc"
    if any(k in biz_text for k in ["vật liệu", "xi măng", "gạch", "cát", "thép", "đợt giao"]):
        return "Vật liệu xây dựng"
    return None


def _select_rules(
    rules: list[dict],
    industry: str | None,
    question: str | None = None,
) -> list[dict]:
    """Keep all score-relevant rules, then retain only top precedence per topic.

    The public rulebook is small enough for the planner context.  Keyword pruning is
    unsafe because many valid topics (for example week boundaries and list tie
    ordering) do not share a stable vocabulary with every natural-language query.
    """
    kept = [r for r in rules if r.get("status") != "invalid" and not _is_submission_format_rule(r)]
    ind_norm = _norm(industry) if industry else None
    if ind_norm:
        kept = [
            r
            for r in kept
            if r.get("scope") != "industry" or _norm(r.get("industry") or "") == ind_norm
        ]
    else:
        kept = [r for r in kept if r.get("scope") != "industry"]

    selected = kept

    best: dict[str, int] = {}
    for r in selected:
        topic_val = r.get("topic")
        if topic_val:
            best[_norm(topic_val)] = max(best.get(_norm(topic_val), 0), r.get("precedence") or 0)
    return [
        r
        for r in selected
        if not r.get("topic") or (r.get("precedence") or 0) >= best[_norm(r["topic"])]
    ]


def _fold_ascii(text: Any) -> str:
    s = unicodedata.normalize("NFKD", str(text or ""))
    return "".join(c for c in s if not unicodedata.combining(c)).lower()


def _prune_tables_for_question(
    tables: list[dict], joins: list[dict], question: str | None, max_tables: int = 7
) -> list[dict]:
    """Prune unreferenced tables for complex multi-table schemas to fit context and increase Table Precision."""
    if len(tables) <= 6 or not question:
        return tables

    q_norm = _fold_ascii(question)
    q_words = set(re.findall(r"[a-z0-9]+", q_norm))
    essential_names = {"calendar", "unit_conversions"}

    scores: dict[str, float] = {}
    for tbl in tables:
        tname = tbl.get("name", "")
        if any(ess in tname for ess in essential_names):
            scores[tname] = 1000.0
            continue

        score = 0.0
        t_words = set(re.findall(r"[a-z0-9]+", _fold_ascii(tname)))
        overlap_name = q_words & t_words
        score += len(overlap_name) * 5.0

        for col in tbl.get("columns", []):
            cname = col.get("name", "")
            c_words = set(re.findall(r"[a-z0-9]+", _fold_ascii(cname)))
            if q_words & c_words:
                score += 2.0
            prov = str(col.get("provenance", ""))
            if prov and (q_words & set(re.findall(r"[a-z0-9]+", _fold_ascii(prov)))):
                score += 2.0

        # Domain concepts
        if any(w in q_norm for w in ["doanh thu", "tien", "thanh toan", "gia tri", "gia", "tong", "nhieu"]) and any(
            str(c.get("data_type", "")).startswith("DECIMAL") or "tien" in c.get("name", "") or "gia" in c.get("name", "")
            for c in tbl.get("columns", [])
        ):
            score += 3.0
        if any(w in q_norm for w in ["so luong", "ban duoc", "bao nhieu", "sl", "hang"]) and any(
            "sl" in c.get("name", "") or "so_luong" in c.get("name", "")
            for c in tbl.get("columns", [])
        ):
            score += 3.0

        scores[tname] = score

    sorted_tables = sorted(tables, key=lambda t: scores.get(t.get("name", ""), 0.0), reverse=True)
    selected_names = set()
    for t in sorted_tables:
        tname = t.get("name", "")
        if scores.get(tname, 0.0) > 0 or tname in essential_names:
            selected_names.add(tname)
            if len(selected_names) >= max_tables:
                break

    if len(selected_names) < 2:
        return tables

    for edge in joins:
        lt = edge.get("left_table")
        rt = edge.get("right_table")
        if lt in selected_names and rt not in selected_names and len(selected_names) < max_tables:
            if scores.get(rt, 0.0) > 0:
                selected_names.add(rt)
        elif rt in selected_names and lt not in selected_names and len(selected_names) < max_tables:
            if scores.get(lt, 0.0) > 0:
                selected_names.add(lt)

    return [t for t in tables if t.get("name") in selected_names]


def format_context_for_prompt(
    context: Any,
    industry: str | None = None,
    question: str | None = None,
) -> str:
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
    raw_tables = schema_catalog.get("tables", [])
    raw_joins = schema_catalog.get("join_graph") or schema_catalog.get("join_edges") or []
    tables = _prune_tables_for_question(raw_tables, raw_joins, question)
    selected_table_names = {t.get("name") for t in tables} if tables != raw_tables else set()
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
    join_edges = [
        e for e in join_edges
        if e.get("status") != "invalid"
        and (not selected_table_names or (e.get("left_table") in selected_table_names and e.get("right_table") in selected_table_names))
    ]
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

    # 2c. Grounded Business Metrics & Formulas
    semantic_catalog = data.get("semantic_catalog") or {}
    metrics = semantic_catalog.get("metrics") or []
    if metrics:
        sections.append("\n### CHỈ SỐ NGHIỆP VỤ ĐÃ ĐỐI CHIẾU (GROUNDED METRICS & FORMULAS):")
        for m in metrics:
            mid = m.get("metric_id", "")
            name = m.get("name") or mid
            table = m.get("preferred_table", "")
            req_cols = ", ".join(m.get("required_columns") or [])
            formula = m.get("formula_hint", "")
            tbl_info = f"bảng `{table}` (cột: {req_cols})" if table else ""
            formula_info = f" -> Công thức: {formula}" if formula else ""
            sections.append(f"- {name} ({mid}): {tbl_info}{formula_info}")

    suggested_joins = semantic_catalog.get("suggested_joins") or []
    if suggested_joins:
        sections.append("\n### GỢI Ý LIÊN KẾT BẢNG NGHIỆP VỤ (SEMANTIC JOINS):")
        for j in suggested_joins:
            lt = j.get("left_table")
            lc = j.get("left_column")
            rt = j.get("right_table")
            rc = j.get("right_column")
            jtype = j.get("join_type", "exact")
            desc = j.get("description", "")
            if jtype == "name_suffix_match":
                sections.append(
                    f"- `{lt}`.{lc} <-> `{rt}`.{rc} (khớp tên gọi tắt / tiền tố): "
                    f"`LOWER(TRIM(SPLIT_PART(REGEXP_REPLACE({lt}.{lc}, '^[aA](\\.|\\s+)', ''), ' ', -1))) = LOWER(SPLIT_PART({rt}.{rc}, ' ', -1))`"
                    f" ({desc})"
                )
            else:
                sections.append(f"- `{lt}`.{lc} = `{rt}`.{rc} ({desc})")

    unit_conversions = semantic_catalog.get("unit_conversions") or []
    if unit_conversions:
        sections.append("\n### BẢNG QUY ĐỔI ĐƠN VỊ TÍNH (UNIT CONVERSIONS):")
        sections.append("Có sẵn bảng `unit_conversions` (item_name, from_unit, to_unit, factor). Áp dụng khi câu hỏi yêu cầu đơn vị khác với bảng bán hàng:")
        for u in unit_conversions[:25]:
            sections.append(f"- {u.get('item_name')}: 1 {u.get('from_unit')} = {u.get('factor')} {u.get('to_unit')}")
        if len(unit_conversions) > 25:
            sections.append(f"... và {len(unit_conversions) - 25} quy tắc quy đổi khác trong bảng `unit_conversions`.")

    # 3. Business Rules: drop other industries, keep the highest precedence per topic
    rule_catalog = data.get("rule_catalog", {})
    rules = _select_rules(
        rule_catalog.get("rules", []),
        industry or (data.get("business_metadata") or {}).get("industry"),
        question=question,
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

    if data.get("grounding_calendar"):
        sections.append("\n### CALENDAR EVIDENCE (Vietnamese lunar mapping; observed coverage only):\n"
                        + json.dumps(data["grounding_calendar"], ensure_ascii=False, separators=(",", ":")))

    # 4. Answerability Constraints
    constraints = data.get("answerability_constraints")
    if constraints:
        sections.append(f"\n### GIỚI HẠN DỮ LIỆU (CONSTRAINTS):\n{json.dumps(constraints, ensure_ascii=False, indent=2)}")

    return "\n".join(sections)


def build_text2sql_messages(
    context: Any,
    question: str,
    as_of_date: str,
    industry: str | None = None,
    grounded_hint: str | None = None,
) -> list[ChatMessage]:
    """Tạo chuỗi messages cho chat API của LLM sinh câu truy vấn SQL ban đầu."""
    context_str = format_context_for_prompt(context, industry, question=question)
    hint_block = f"\n\n{grounded_hint.strip()}" if grounded_hint and grounded_hint.strip() else ""
    user_content = f"""{context_str}

### THÔNG TIN CÂU HỎI:
- Ngày tham chiếu (as_of_date): {as_of_date}
- Câu hỏi: "{question}"{hint_block}

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
    grounded_hint: str | None = None,
) -> list[ChatMessage]:
    """Tạo chuỗi messages cho vòng Bounded Retry sửa lại câu SQL khi bị lỗi thực thi."""
    context_str = format_context_for_prompt(context, industry, question=question)
    hint_block = f"\n\n{grounded_hint.strip()}" if grounded_hint and grounded_hint.strip() else ""
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
- Câu hỏi: "{question}"{hint_block}

{sql_section}

### THÔNG BÁO LỖI (ERROR MESSAGE TỪ DATABASE/EXECUTOR):
```
{error_message}
```

YÊU CẦU SỬA ĐỔI:
- Hãy đọc kỹ thông báo lỗi trên, sửa lại câu lệnh SQL cho chính xác, tương thích với schema và dữ liệu.
- Nếu lỗi là 'syntax error at or near':
  + Kiểm tra xem bí danh (alias) có bị trùng từ khóa SQL dự trữ (như `ON`, `AS`, `IN`, `WHERE`, `ORDER`, `GROUP`) hay không; đổi alias sang tên an toàn (`t1`, `t2`, `sub`).
  + Kiểm tra dấu đóng mở ngoặc hoặc số tham số của các hàm lồng nhau (như `REPLACE`, `LOWER`).
  + Khi JOIN qua tên gọi tắt hoặc tiền tố xưng hô: Tham khảo cú pháp chuẩn trong mục 'GỢI Ý LIÊN KẾT BẢNG NGHIỆP VỤ' để liên kết theo phần tên cuối, tránh lỗi cú pháp lồng hàm.
- Nếu lỗi là 'must appear in the GROUP BY clause': Thêm tất cả các cột đó vào mệnh đề `GROUP BY` (ví dụ: `GROUP BY d.ho_ten, d.hoa_hong`) hoặc bọc qua `ANY_VALUE(cột)`.
- Nếu lỗi là 'GROUP BY clause cannot contain aggregates': Xóa bỏ mệnh đề GROUP BY nếu câu lệnh SELECT chỉ tính toán một giá trị tổng hợp vô hướng (SUM, COUNT).
- Nếu kết quả bị rỗng hoặc lỗi so khớp: Bắt buộc dùng toán tử `LIKE` khi có ký tự `%` (ví dụ `WHERE LOWER(col) LIKE '%từ_khóa%'`), tuyệt đối không dùng dấu `=`.
- Nếu lỗi là 'Referenced table ... not found': Đảm bảo đã có mệnh đề `FROM` chứa tên CTE hoặc bảng đó (ví dụ `FROM cte1, cte2`).
- Lưu ý: Giữ lại toàn bộ các CTE cần thiết (WITH ...), không gọi trực tiếp tên CTE như bảng vật lý nếu chưa định nghĩa.
- BẮT BUỘC viết đầy đủ câu lệnh SQL hoàn chỉnh, TUYỆT ĐỐI KHÔNG dùng dấu ba chấm '...' để viết tắt các mệnh đề FROM/JOIN/WHERE.
- Nếu câu hỏi hỏi Top N hoặc danh sách, câu lệnh SELECT CHỈ ĐƯỢC LẤY ĐÚNG 1 CỘT Tên thực thể.
- Nếu suy luận, hãy suy luận ngắn gọn trong <think>...</think>.
- Kết quả cuối cùng BẮT BUỘC là 1 khối JSON hợp lệ nằm trong ```json ... ```."""

    return [
        ChatMessage(role="system", content=SYSTEM_INSTRUCTION),
        ChatMessage(role="user", content=user_content),
    ]
