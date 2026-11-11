"""Contract tests for the business context runtime boundary."""

from __future__ import annotations

import hashlib
import json

import duckdb
import pytest

from datamate.context.runtime import (
    BusinessContextRuntimeError,
    BusinessContextRuntimeLoader,
)
from datamate.grounding.protocols import BusinessContextProtocol
from datamate.pipeline import B0Pipeline


def _valid_context(business_id: str = "biz_runtime") -> dict[str, object]:
    return {
        "contract_version": "1.0",
        "business_id": business_id,
        "schema_catalog": {
            "tables": [],
            "key_candidates": [],
            "join_graph": [],
            "warnings": [],
        },
        "rule_catalog": {
            "rules": [],
            "warnings": [],
            "business_id": business_id,
        },
    }


def _write_context(tmp_path, payload: object) -> None:
    (tmp_path / "business_context.json").write_text(
        json.dumps(payload), encoding="utf-8"
    )


def test_load_returns_planner_and_grounding_views(tmp_path) -> None:
    payload = _valid_context()
    _write_context(tmp_path, payload)

    runtime = BusinessContextRuntimeLoader().load(
        tmp_path, expected_business_id="biz_runtime"
    )

    assert runtime.business_id == "biz_runtime"
    assert runtime.bundle_dir == tmp_path.resolve()
    assert runtime.planner_context == payload
    assert isinstance(runtime.grounding_context, BusinessContextProtocol)
    assert runtime.grounding_context.business_id == runtime.business_id


def test_load_rejects_expected_business_id_mismatch(tmp_path) -> None:
    _write_context(tmp_path, _valid_context())

    with pytest.raises(BusinessContextRuntimeError) as caught:
        BusinessContextRuntimeLoader().load(
            tmp_path, expected_business_id="another_business"
        )

    assert caught.value.code == "BUSINESS_ID_MISMATCH"
    assert caught.value.bundle_dir == tmp_path.resolve()


@pytest.mark.parametrize(
    ("raw_content", "expected_code"),
    [
        ("not-json", "CONTEXT_JSON_INVALID"),
        (json.dumps([]), "CONTEXT_CONTRACT_INVALID"),
        (json.dumps(_valid_context() | {"contract_version": "2.0"}), "CONTEXT_CONTRACT_INVALID"),
        (json.dumps(_valid_context() | {"business_id": ""}), "CONTEXT_CONTRACT_INVALID"),
    ],
)
def test_load_classifies_invalid_context(tmp_path, raw_content, expected_code) -> None:
    (tmp_path / "business_context.json").write_text(raw_content, encoding="utf-8")

    with pytest.raises(BusinessContextRuntimeError) as caught:
        BusinessContextRuntimeLoader().load(tmp_path)

    assert caught.value.code == expected_code


def test_load_classifies_missing_file(tmp_path) -> None:
    with pytest.raises(BusinessContextRuntimeError) as caught:
        BusinessContextRuntimeLoader().load(tmp_path)

    assert caught.value.code == "CONTEXT_FILE_MISSING"


def test_load_classifies_non_utf8_context_as_invalid_json(tmp_path) -> None:
    (tmp_path / "business_context.json").write_bytes(b"\xff\xfe")

    with pytest.raises(BusinessContextRuntimeError) as caught:
        BusinessContextRuntimeLoader().load(tmp_path)

    assert caught.value.code == "CONTEXT_JSON_INVALID"
    assert isinstance(caught.value.__cause__, UnicodeDecodeError)


def test_load_wraps_adapter_validation_failure(tmp_path) -> None:
    payload = _valid_context()
    payload["schema_catalog"] = {"tables": "invalid"}
    _write_context(tmp_path, payload)

    with pytest.raises(BusinessContextRuntimeError) as caught:
        BusinessContextRuntimeLoader().load(tmp_path)

    assert caught.value.code == "CONTEXT_CONTRACT_INVALID"
    assert caught.value.__cause__ is not None


def test_loader_caches_by_resolved_bundle_and_revalidates_expected_id(tmp_path) -> None:
    _write_context(tmp_path, _valid_context())
    loader = BusinessContextRuntimeLoader()

    first = loader.load(tmp_path)
    (tmp_path / "business_context.json").unlink()
    second = loader.load(tmp_path / ".", expected_business_id="biz_runtime")

    assert second is first
    with pytest.raises(BusinessContextRuntimeError) as caught:
        loader.load(tmp_path, expected_business_id="another_business")
    assert caught.value.code == "BUSINESS_ID_MISMATCH"


def test_loader_does_not_share_cache_between_bundles(tmp_path) -> None:
    first_bundle = tmp_path / "first"
    second_bundle = tmp_path / "second"
    first_bundle.mkdir()
    second_bundle.mkdir()
    _write_context(first_bundle, _valid_context("first"))
    _write_context(second_bundle, _valid_context("second"))

    loader = BusinessContextRuntimeLoader()

    assert loader.load(first_bundle).business_id == "first"
    assert loader.load(second_bundle).business_id == "second"


def test_loader_enriches_from_duckdb_without_modifying_bundle(tmp_path) -> None:
    _write_context(tmp_path, _valid_context())
    database_path = tmp_path / "data.duckdb"
    with duckdb.connect(str(database_path)) as connection:
        connection.execute('CREATE TABLE "don hang" (id INTEGER, loai VARCHAR)')
        connection.execute("INSERT INTO \"don hang\" VALUES (1, 'a'), (2, 'b')")
    context_path = tmp_path / "business_context.json"
    context_hash = hashlib.sha256(context_path.read_bytes()).hexdigest()
    database_hash = hashlib.sha256(database_path.read_bytes()).hexdigest()

    runtime = BusinessContextRuntimeLoader().load(tmp_path)

    assert set(
        runtime.planner_context["categorical_samples"]["don hang"]["loai"]
    ) == {"a", "b"}
    assert hashlib.sha256(context_path.read_bytes()).hexdigest() == context_hash
    assert hashlib.sha256(database_path.read_bytes()).hexdigest() == database_hash


def test_loader_logs_and_ignores_duckdb_enrichment_failure(tmp_path, caplog) -> None:
    _write_context(tmp_path, _valid_context())
    (tmp_path / "data.duckdb").write_bytes(b"not-a-duckdb-database")

    runtime = BusinessContextRuntimeLoader().load(tmp_path)

    assert "categorical_samples" not in runtime.planner_context
    assert "bỏ qua enrichment" in caplog.text


def test_pipeline_load_context_delegates_to_strict_runtime_boundary(tmp_path) -> None:
    _write_context(tmp_path, {})

    with pytest.raises(BusinessContextRuntimeError) as caught:
        B0Pipeline.load_context(tmp_path)

    assert caught.value.code == "CONTEXT_CONTRACT_INVALID"
