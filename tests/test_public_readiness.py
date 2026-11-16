"""Regression tests for issues that can invalidate a public-test run."""

from __future__ import annotations

import json
from pathlib import Path

from datamate.context.contracts import BusinessRule
from datamate.context.semantic_extractor import LLMSemanticExtractor, RuleSchemaMatcher
from datamate.grounding.adapters import B02ContextAdapter
from datamate.ingestion.contracts import ColumnMetadata, SchemaCatalog, TableMetadata
from datamate.planner.prompt import SYSTEM_INSTRUCTION, _select_rules
from scripts.run_pipeline import evaluate_predictions

ROOT = Path(__file__).resolve().parent.parent


def test_percent_change_prompt_preserves_negative_decreases() -> None:
    assert "ABS((ky_nay - ky_truoc)" not in SYSTEM_INSTRUCTION
    assert "(ky_nay - ky_truoc) / ky_truoc" in SYSTEM_INSTRUCTION


def test_rule_selection_keeps_score_relevant_topics_and_ordering_rules() -> None:
    rules = [
        {
            "rule_id": "week",
            "topic": "Tuần",
            "text": "Tuần tính từ thứ Hai đến Chủ nhật.",
            "scope": "split_default",
            "status": "active",
            "precedence": 5,
        },
        {
            "rule_id": "ordering",
            "topic": None,
            "text": "- **Danh sách:** đúng cả tập và thứ tự.",
            "scope": "split_default",
            "status": "active",
            "precedence": 5,
        },
        {
            "rule_id": "wire-format",
            "topic": "number",
            "text": "number | JSON number, không đơn vị",
            "scope": "split_default",
            "status": "active",
            "precedence": 5,
        },
    ]

    kept = _select_rules(rules, industry=None, question="Doanh thu tuần này?")
    kept_ids = {rule["rule_id"] for rule in kept}

    assert {"week", "ordering"} <= kept_ids
    assert "wire-format" not in kept_ids


def test_evaluator_obeys_list_table_and_missing_prediction_rules(tmp_path) -> None:
    answers = [
        {"id": "list", "type": "list", "answer": ["A", "B"]},
        {
            "id": "table",
            "type": "table",
            "answer": {"columns": ["name", "value"], "rows": [["A", 1], ["B", 2]]},
        },
        {"id": "missing", "type": "number", "answer": 3},
    ]
    predictions = [
        {"id": "list", "type": "list", "answer": ["B", "A"]},
        {
            "id": "table",
            "type": "table",
            "answer": {"columns": ["name", "value"], "rows": [["B", 2], ["A", 1]]},
        },
    ]
    answers_path = tmp_path / "answers.jsonl"
    submission_path = tmp_path / "submission.jsonl"
    answers_path.write_text("".join(json.dumps(row) + "\n" for row in answers), encoding="utf-8")
    submission_path.write_text(
        "".join(json.dumps(row) + "\n" for row in predictions), encoding="utf-8"
    )

    report = evaluate_predictions(
        submission_path=submission_path,
        answers_path=answers_path,
        questions=[{"id": row["id"], "business_id": "b"} for row in answers],
    )
    statuses = {detail["id"]: detail["status"] for detail in report["details"]}

    assert report["total_evaluated"] == 3
    assert statuses == {"list": "wrong", "table": "correct", "missing": "abstained"}


def test_adapter_preserves_serialized_semantic_catalog() -> None:
    payload = {
        "contract_version": "1.1",
        "business_id": "b",
        "schema_catalog": {
            "tables": [{"name": "orders", "columns": [{"name": "amount", "data_type": "BIGINT"}]}],
            "key_candidates": [],
            "join_graph": [],
            "warnings": [],
        },
        "rule_catalog": {"rules": [], "warnings": [], "business_id": "b"},
        "semantic_catalog": {
            "business_id": "b",
            "metrics": [
                {
                    "metric_id": "custom_metric",
                    "aliases": ["custom"],
                    "preferred_table": "orders",
                    "required_columns": ["amount"],
                    "formula_hint": "SUM(amount)",
                    "unit": "VND",
                }
            ],
        },
    }

    metrics = {metric.metric_id: metric for metric in B02ContextAdapter.from_dict(payload).get_metrics()}

    assert metrics["custom_metric"].required_columns == ("amount",)


def test_rule_schema_matcher_never_binds_columns_from_another_table() -> None:
    schema = SchemaCatalog(
        tables=(
            TableMetadata(
                name="workers",
                columns=(
                    ColumnMetadata(name="ho_ten", data_type="VARCHAR"),
                    ColumnMetadata(name="hoa_hong", data_type="DOUBLE"),
                ),
            ),
            TableMetadata(
                name="repairs",
                columns=(
                    ColumnMetadata(name="ngay", data_type="DATE"),
                    ColumnMetadata(name="tho", data_type="VARCHAR"),
                    ColumnMetadata(name="tien", data_type="BIGINT"),
                ),
            ),
        )
    )
    rules = (
        BusinessRule(
            rule_id="commission",
            text="Hoa hồng của thợ tính trên tổng tiền.",
            source="README.md",
            scope="business",
            precedence=10,
            topic="Hoa hồng",
        ),
    )

    catalog = RuleSchemaMatcher().extract_semantic_catalog("b", schema, rules)
    columns_by_table = {table.name: {column.name for column in table.columns} for table in schema.tables}

    for metric in catalog.metrics:
        assert set(metric.required_columns) <= columns_by_table[metric.preferred_table]


def test_semantic_discovery_prompt_is_bounded_for_4096_token_model() -> None:
    schema = SchemaCatalog(
        tables=(
            TableMetadata(
                name="orders",
                columns=tuple(ColumnMetadata(name=f"column_{index}", data_type="VARCHAR") for index in range(30)),
            ),
        )
    )
    rules = tuple(
        BusinessRule(
            rule_id=f"r{index}",
            text=("Quy tắc nghiệp vụ rất dài " * 20) + str(index),
            source="rulebook.md",
            scope="split_default",
            precedence=5,
            topic=f"Topic {index}",
        )
        for index in range(150)
    )

    prompt = LLMSemanticExtractor()._build_prompt("b", schema, rules)

    assert len(prompt) <= 7_500
    assert "LƯỢC ĐỒ CƠ SỞ DỮ LIỆU" in prompt
    assert "CÁC QUY TẮC NGHIỆP VỤ" in prompt


def test_semantic_discovery_deserializes_complete_business_rules() -> None:
    from scripts.run_pipeline import _deserialize_business_rules

    rules = _deserialize_business_rules(
        [
            {
                "rule_id": "r1",
                "text": "Doanh thu là tổng tiền.",
                "source": "rulebook.md",
                "scope": "split_default",
                "precedence": 5,
                "status": "active",
                "topic": "Doanh thu",
                "required_fields": ["tien"],
            }
        ]
    )

    assert rules == [
        BusinessRule(
            rule_id="r1",
            text="Doanh thu là tổng tiền.",
            source="rulebook.md",
            scope="split_default",
            precedence=5,
            status="active",
            topic="Doanh thu",
            required_fields=("tien",),
        )
    ]


def test_gpu_deployments_install_checked_in_requirements() -> None:
    modal_script = (ROOT / "scripts" / "modal_run_pipeline.py").read_text(encoding="utf-8")
    dockerfile = (ROOT / "Dockerfile").read_text(encoding="utf-8")

    # Modal runs on isolated cloud containers pinned via requirements-lock.txt
    assert 'pip_install_from_requirements(str(PROJECT_ROOT / "requirements-lock.txt"))' in modal_script
    # Offline BTC Docker submission uses the pinned vLLM base image + runtime-only requirements-docker.txt (no cu13 overwrite)
    assert "ARG BASE_IMAGE=vllm/vllm-openai:v0.17.1" in dockerfile
    assert "COPY pyproject.toml requirements.txt requirements-docker.txt ./" in dockerfile
    assert "-r requirements-docker.txt" in dockerfile
