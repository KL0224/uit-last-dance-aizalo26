"""Dynamic Semantic Discovery and Rule-Schema Binding for DataMate Context."""

from __future__ import annotations

import logging
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Sequence

from datamate.context.contracts import BusinessRule, MetricDefinition, SemanticCatalog
from datamate.ingestion.contracts import ColumnMetadata, SchemaCatalog, TableMetadata

logger = logging.getLogger(__name__)


class RuleSchemaMatcher:
    """Deterministic matcher that binds 122+ rules to actual DuckDB schema tables and columns."""

    def extract_semantic_catalog(
        self,
        business_id: str,
        schema: SchemaCatalog,
        rules: Sequence[BusinessRule],
    ) -> SemanticCatalog:
        """Analyze business rules against database schema to discover grounded metrics and join paths."""
        col_to_tables: dict[str, list[str]] = {}
        table_money_cols: dict[str, list[str]] = {}
        table_date_cols: dict[str, list[str]] = {}
        table_qty_cols: dict[str, list[str]] = {}

        for tbl in schema.tables:
            t_name = tbl.name
            table_money_cols[t_name] = []
            table_date_cols[t_name] = []
            table_qty_cols[t_name] = []

            for col in tbl.columns:
                c_name = col.name
                col_to_tables.setdefault(c_name.lower(), []).append(t_name)
                
                # Phân loại vai trò cột
                r = (getattr(col, "role", None) or "").lower()
                dt = (getattr(col, "data_type", None) or "").upper()
                c_l = c_name.lower()
                if r == "money" or any(k in c_l for k in ("tien", "tong_tien", "thanh_tien", "doanh_thu", "gia_ban", "amount", "total", "price")):
                    table_money_cols[t_name].append(c_name)
                if r == "date" or "DATE" in dt or "TIME" in dt or any(k in c_l for k in ("ngay", "date", "created_at", "thoi_gian")):
                    table_date_cols[t_name].append(c_name)
                if r == "quantity" or any(k in c_l for k in ("so_luong", "soluong", "sl", "qty", "quantity")):
                    table_qty_cols[t_name].append(c_name)

        # Xác định bảng giao dịch chính (Fact / Transaction table)
        # Bảng giao dịch thường có cả cột ngày và cột tiền hoặc số lượng
        fact_candidates = [
            t_name for t_name in schema.tables
            if table_date_cols[t_name.name] and (table_money_cols[t_name.name] or table_qty_cols[t_name.name])
        ]
        primary_fact_table = fact_candidates[0].name if fact_candidates else (schema.tables[0].name if schema.tables else "")

        # Tránh chọn nhầm bảng nhân viên/thợ làm fact table cho order_count
        worker_tables = {
            t.name for t in schema.tables
            if any(k in t.name.lower() for k in ("tho", "nhan_vien", "employee", "worker", "danh_sach"))
        }

        order_fact_table = primary_fact_table
        if order_fact_table in worker_tables:
            other_facts = [f.name for f in fact_candidates if f.name not in worker_tables]
            if other_facts:
                order_fact_table = other_facts[0]
            else:
                non_workers = [t.name for t in schema.tables if t.name not in worker_tables and table_date_cols[t.name]]
                if non_workers:
                    order_fact_table = non_workers[0]

        discovered_metrics: dict[str, MetricDefinition] = {}

        # 1. Duyệt qua các quy tắc nghiệp vụ trong RuleCatalog (README.md & Rulebook.md)
        for rule in rules:
            txt_l = f"{rule.topic or ''} {rule.text}".lower()
            r_id = rule.rule_id
            
            # (A) Hoa hồng / Huê hồng / Chiết khấu thợ
            if any(k in txt_l for k in ("hoa hồng", "huê hồng", "chiết khấu")):
                # Kiểm tra DB có cột hoa_hong hoặc percent không
                comm_cols = [c for c in col_to_tables.keys() if "hoa_hong" in c or "chiet_khau" in c or "commission" in c]
                money_candidates = table_money_cols.get(order_fact_table, [])
                if comm_cols or money_candidates:
                    comm_col = comm_cols[0] if comm_cols else money_candidates[0]
                    pref_tbl = col_to_tables.get(comm_col, [order_fact_table])[0]
                    table_columns = {
                        column.name for table in schema.tables if table.name == pref_tbl
                        for column in table.columns
                    }
                    discovered_metrics["commission"] = MetricDefinition(
                        metric_id="commission",
                        name="Tiền hoa hồng thợ",
                        aliases=("hoa hồng", "huê hồng", "tiền hoa hồng", "lương hoa hồng", "commission"),
                        preferred_table=pref_tbl,
                        required_columns=tuple(
                            c
                            for c in (comm_col, "tien", "tho", "ho_ten")
                            if c in table_columns
                        ),
                        formula_hint=rule.text,
                        unit="VND",
                        applicable_rule_ids=(r_id,),
                    )

            # (B) Doanh thu / Tiền hàng
            if any(k in txt_l for k in ("doanh thu", "tiền hàng", "bán được bao nhiêu tiền", "thu về bao nhiêu tiền")):
                if table_money_cols.get(order_fact_table):
                    m_col = table_money_cols[order_fact_table][0]
                    discovered_metrics["revenue"] = MetricDefinition(
                        metric_id="revenue",
                        name="Doanh thu / Tổng tiền",
                        aliases=("doanh thu", "tổng tiền", "tiền bán", "tiền hàng", "doanh số", "dthu"),
                        preferred_table=order_fact_table,
                        required_columns=(m_col,),
                        formula_hint=rule.text,
                        unit="VND",
                        applicable_rule_ids=(r_id,),
                    )

            # (C) Lượt xe / Số đơn / Số phiếu
            if any(k in txt_l for k in ("số đơn", "số lượt", "lượt xe", "phiếu", "số phiếu")):
                d_cols = table_date_cols.get(order_fact_table, [])
                req_c = (d_cols[0],) if d_cols else ()
                discovered_metrics["order_count"] = MetricDefinition(
                    metric_id="order_count",
                    name="Số đơn / Số lượt / Phiếu",
                    aliases=("số đơn", "số lượt", "lượt xe", "phiếu", "số phiếu", "bao nhiêu đơn", "mấy phiếu"),
                    preferred_table=order_fact_table,
                    required_columns=req_c,
                    formula_hint=rule.text,
                    unit="count",
                    applicable_rule_ids=(r_id,),
                )

            # (D) Bảo hành
            if "bảo hành" in txt_l:
                note_cols = [c for c in col_to_tables.keys() if any(k in c for k in ("ghi_chu", "note", "trang_thai", "status"))]
                if note_cols:
                    pref_tbl = col_to_tables.get(note_cols[0], [order_fact_table])[0]
                    discovered_metrics["warranty_count"] = MetricDefinition(
                        metric_id="warranty_count",
                        name="Phiếu bảo hành",
                        aliases=("bảo hành", "phiếu bảo hành", "xe bảo hành"),
                        preferred_table=pref_tbl,
                        required_columns=(note_cols[0],),
                        formula_hint=rule.text,
                        unit="count",
                        applicable_rule_ids=(r_id,),
                    )

            # (E) Giá vốn / Chi phí
            if any(k in txt_l for k in ("giá vốn", "chi phí")):
                cost_cols = [c for c in col_to_tables.keys() if any(k in c for k in ("gia_von", "cost", "chi_phi", "unit_cost"))]
                if cost_cols:
                    pref_tbl = col_to_tables[cost_cols[0]][0]
                    discovered_metrics["cost"] = MetricDefinition(
                        metric_id="cost",
                        name="Giá vốn / Chi phí",
                        aliases=("giá vốn", "chi phí"),
                        preferred_table=pref_tbl,
                        required_columns=(cost_cols[0],),
                        formula_hint=rule.text,
                        unit="VND",
                        applicable_rule_ids=(r_id,),
                    )

            # (F) Lãi gộp / Lợi nhuận
            if any(k in txt_l for k in ("lãi gộp", "lợi nhuận")):
                cost_cols = [c for c in col_to_tables.keys() if any(k in c for k in ("gia_von", "cost", "chi_phi", "unit_cost"))]
                if cost_cols and any(table_money_cols.values()):
                    discovered_metrics["gross_profit"] = MetricDefinition(
                        metric_id="gross_profit",
                        name="Lãi gộp / Lợi nhuận",
                        aliases=("lãi gộp", "lợi nhuận", "tiền lời"),
                        preferred_table=order_fact_table,
                        required_columns=(),
                        formula_hint=rule.text,
                        unit="VND",
                        applicable_rule_ids=(r_id,),
                    )

            # (G) Số lượng bán
            if any(k in txt_l for k in ("số lượng", "bán chạy", "bán được")):
                qty_cols = [c for c in col_to_tables.keys() if any(k in c for k in ("so_luong", "soluong", "sl", "qty", "quantity"))]
                if qty_cols:
                    pref_tbl = col_to_tables[qty_cols[0]][0]
                    discovered_metrics["sold_qty"] = MetricDefinition(
                        metric_id="sold_qty",
                        name="Số lượng bán",
                        aliases=("số lượng", "bán chạy", "bán được", "chiếc", "cái"),
                        preferred_table=pref_tbl,
                        required_columns=(qty_cols[0],),
                        formula_hint=rule.text,
                        unit="qty",
                        applicable_rule_ids=(r_id,),
                    )

        # 2. Heuristic fallback nếu metric cốt lõi chưa xuất hiện
        if "revenue" not in discovered_metrics:
            for t_name, m_cols in table_money_cols.items():
                if m_cols and t_name not in worker_tables:
                    discovered_metrics["revenue"] = MetricDefinition(
                        metric_id="revenue",
                        name="Doanh thu / Tổng tiền",
                        aliases=("doanh thu", "tổng tiền", "tiền bán", "dthu"),
                        preferred_table=t_name,
                        required_columns=(m_cols[0],),
                        unit="VND",
                    )
                    break

        if "order_count" not in discovered_metrics:
            discovered_metrics["order_count"] = MetricDefinition(
                metric_id="order_count",
                name="Số đơn / Lượt xe",
                aliases=("số đơn", "số lượt", "lượt xe", "phiếu", "số phiếu"),
                preferred_table=order_fact_table,
                required_columns=tuple(table_date_cols.get(order_fact_table, [])[:1]),
                unit="count",
            )

        # Bổ sung sold_qty nếu có cột số lượng
        for t_name, q_cols in table_qty_cols.items():
            if q_cols:
                discovered_metrics["sold_qty"] = MetricDefinition(
                    metric_id="sold_qty",
                    name="Số lượng bán",
                    aliases=("số lượng", "bán chạy", "bán được"),
                    preferred_table=t_name,
                    required_columns=(q_cols[0],),
                    unit="qty",
                )
                break

        # Khám phá heuristic suggested joins giữa các bảng
        table_cols: dict[str, list[str]] = {tbl.name: [col.name for col in tbl.columns] for tbl in schema.tables}
        heuristic_joins: list[dict[str, Any]] = []
        # 1. Liên kết nhân sự / thợ: một bảng danh mục có họ tên và bảng giao dịch có tho/nhan_vien/nguoi_ban
        for w_tbl in worker_tables:
            w_cols = table_cols.get(w_tbl, [])
            name_col = next((c for c in w_cols if c in ("ho_ten", "ten", "ten_nhan_vien", "ten_tho", "nguoi_thuc_hien")), None)
            if not name_col:
                continue
            for other_tbl, o_cols in table_cols.items():
                if other_tbl == w_tbl:
                    continue
                match_col = next((c for c in o_cols if c in ("tho", "nhan_vien", "nguoi_ban", "nguoi_lam", "ky_thuat")), None)
                if match_col:
                    heuristic_joins.append({
                        "left_table": other_tbl,
                        "left_column": match_col,
                        "right_table": w_tbl,
                        "right_column": name_col,
                        "join_type": "name_suffix_match",
                        "description": f"Liên kết nhân sự qua tên gọi/tên viết tắt ({match_col} <-> {name_col})",
                    })

        # 2. Khớp khóa ngoại chung mã (ma_khach_hang, ma_hang, ma_don...)
        for t1, cols1 in table_cols.items():
            for t2, cols2 in table_cols.items():
                if t1 >= t2:
                    continue
                common_keys = [c for c in cols1 if c in cols2 and (c.startswith("ma_") or c.endswith("_id") or c in ("id", "code"))]
                for k in common_keys:
                    heuristic_joins.append({
                        "left_table": t1,
                        "left_column": k,
                        "right_table": t2,
                        "right_column": k,
                        "join_type": "exact",
                        "description": f"Khóa ngoại liên kết ({k})",
                    })

        return SemanticCatalog(
            business_id=business_id,
            metrics=tuple(discovered_metrics.values()),
            suggested_joins=tuple(heuristic_joins),
            unsupported_capabilities=(),
        )


SEMANTIC_DISCOVERY_SYSTEM_PROMPT = """Bạn trích xuất metadata B02 từ tài liệu được cung cấp. Chỉ trả một JSON object.
KHÔNG dùng tri thức ngoài tài liệu. KHÔNG tự sáng tạo tên hàng, công thức hoặc JOIN.
Mỗi mục PHẢI có evidence gồm rule_id chính xác từ [ID] trong input và quote trích nguyên văn dòng nguồn (không gồm tiền tố [ID] source=...).
Thiếu bằng chứng thì bỏ mục; dùng mảng rỗng. Nếu tài liệu chỉ có quy đổi, các nhóm còn lại PHẢI rỗng.
Schema output:
- metrics: array các object {metric_id, name, preferred_table, required_columns, formula_hint, unit, evidence: {rule_id, quote}}. Chỉ khi tài liệu nói rõ metric và công thức; bảng/cột phải có trong schema. Không coi giá bán danh mục là doanh thu.
- suggested_joins: array các object {left_table, left_column, right_table, right_column, join_type, description, evidence: {rule_id, quote}}. Chỉ khi tài liệu nói rõ quan hệ. Không nối bảng với chính nó.
- unit_conversions: array các object {item_name, from_unit, to_unit, factor, evidence: {rule_id, quote}}. Chỉ trích phương trình được viết rõ, giữ chính xác tên hàng và đơn vị. Trích đầy đủ từng dòng có phương trình; quote phải chứa tên hàng và phương trình. factor là số dương.
- unsupported_capabilities: array rỗng; không suy luận dữ liệu thiếu từ việc chưa nhìn thấy cột.
Không thêm văn xuôi, markdown hoặc ví dụ giả định vào output.
"""


class LLMSemanticExtractor:
    """Trích xuất SemanticCatalog thông minh bằng mô hình 3B với xác thực lược đồ chặt chẽ."""

    def __init__(
        self,
        chat_fn: Any | None = None,
        model: Any | None = None,
        model_path: str | Path | None = None,
    ) -> None:
        self.chat_fn = chat_fn
        self.model = model
        self.model_path = model_path
        self.matcher = RuleSchemaMatcher()

    def extract_semantic_catalog(
        self,
        business_id: str,
        schema: SchemaCatalog,
        rules: Sequence[BusinessRule],
    ) -> SemanticCatalog:
        # 1. Luôn tính toán heuristic baseline để làm ngưỡng bảo vệ (guardrail)
        base_catalog = self.matcher.extract_semantic_catalog(business_id, schema, rules)

        # 2. Nếu không có LLM, trả về baseline ngay lập tức
        if self.chat_fn is None and self.model is None and not self.model_path:
            return base_catalog

        # 3. Gọi mô hình 3B để trích xuất ngữ nghĩa sâu sắc
        try:
            llm_result = self._call_llm(business_id, schema, rules)
            if llm_result is not None:
                from .verified_semantics import verified_merge
                return verified_merge(business_id, base_catalog, llm_result, schema, tuple(rules))
        except Exception as exc:
            logger.warning("LLMSemanticExtractor gặp lỗi (%s), dùng kết quả RuleSchemaMatcher", exc)

        return base_catalog

    def _call_llm(
        self,
        business_id: str,
        schema: SchemaCatalog,
        rules: Sequence[BusinessRule],
    ) -> dict[str, Any] | None:
        import json
        import re

        user_prompt = self._build_prompt(business_id, schema, rules)
        raw_text = ""
        if self.chat_fn is not None:
            raw_text = self.chat_fn(SEMANTIC_DISCOVERY_SYSTEM_PROMPT, user_prompt)
        elif self.model is not None:
            from datamate.planner.types import ChatMessage
            res = self.model.chat(
                [
                    ChatMessage(role="system", content=SEMANTIC_DISCOVERY_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=user_prompt),
                ]
            )
            raw_text = res.text
        elif self.model_path:
            from datamate.planner.config import ModelConfig
            from datamate.planner.vllm_model import VLLMModel
            from datamate.planner.types import ChatMessage, GenerationOptions
            cfg = ModelConfig(model_path=Path(self.model_path), max_model_len=4096)
            m = VLLMModel(cfg, default_options=GenerationOptions(max_new_tokens=1024, temperature=0.0))
            m.load()
            self.model = m
            res = m.chat(
                [
                    ChatMessage(role="system", content=SEMANTIC_DISCOVERY_SYSTEM_PROMPT),
                    ChatMessage(role="user", content=user_prompt),
                ]
            )
            raw_text = res.text

        if not raw_text:
            return None

        match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", raw_text)
        json_str = match.group(1) if match else raw_text.strip()
        return json.loads(json_str)

    def _build_prompt(
        self,
        business_id: str,
        schema: SchemaCatalog,
        rules: Sequence[BusinessRule],
    ) -> str:
        max_prompt_chars = 7_500
        lines = [f"DOANH NGHIỆP: {business_id}", "\n### LƯỢC ĐỒ CƠ SỞ DỮ LIỆU:"]
        for tbl in schema.tables:
            col_strs = [f"{c.name} ({c.data_type})" for c in tbl.columns if not c.name.startswith("__dm_")]
            lines.append(f"- Bảng `{tbl.name}`: {', '.join(col_strs)}")

        lines.append("\n### CÁC QUY TẮC NGHIỆP VỤ & TÀI LIỆU:")
        valid_rules = sorted(
            (rule for rule in rules if rule.status != "invalid"),
            key=lambda rule: (rule.scope != "business", -rule.precedence, rule.rule_id),
        )
        omitted = 0
        for index, rule in enumerate(valid_rules):
            rule_text = " ".join(str(rule.text).split())
            candidate = f"- [{rule.rule_id}] source={rule.source} {rule.topic or ''}: {rule_text}"
            remaining_rules = len(valid_rules) - index
            suffix = f"\n- ... đã lược bớt {remaining_rules} quy tắc để giữ giới hạn context"
            if len("\n".join((*lines, candidate))) + len(suffix) > max_prompt_chars:
                omitted = remaining_rules
                break
            lines.append(candidate)

        if omitted:
            lines.append(f"- ... đã lược bớt {omitted} quy tắc để giữ giới hạn context")
        prompt = "\n".join(lines)
        return prompt[:max_prompt_chars]

    def _merge_catalogs(self, business_id, base, llm_data, schema, rules=()):
        """Compatibility entrypoint; source checks also apply to direct callers."""
        from .verified_semantics import verified_merge
        return verified_merge(business_id, base, llm_data, schema, tuple(rules))


def create_semantic_extractor(
    chat_fn: Any | None = None,
    model: Any | None = None,
    model_path: str | Path | None = None,
) -> LLMSemanticExtractor:
    """Tạo đối tượng trích xuất ngữ nghĩa Dual-Engine."""
    return LLMSemanticExtractor(chat_fn=chat_fn, model=model, model_path=model_path)
