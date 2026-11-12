"""Tests for datamate canonical modular package structure and legacy facade compatibility."""

from __future__ import annotations

from unittest.mock import MagicMock
import pytest


def test_root_package_exports() -> None:
    """Ensure datamate exports all canonical subpackages and pipeline classes."""
    import datamate
    from datamate import (
        B0Pipeline,
        Pipeline,
        context,
        execution,
        gate,
        grounding,
        ingestion,
        pipeline,
        planner,
    )

    assert datamate.Pipeline is Pipeline
    assert datamate.B0Pipeline is B0Pipeline
    assert Pipeline is B0Pipeline
    assert datamate.ingestion is ingestion
    assert datamate.context is context
    assert datamate.grounding is grounding
    assert datamate.planner is planner
    assert datamate.execution is execution
    assert datamate.gate is gate
    assert datamate.pipeline is pipeline


def test_canonical_ingestion_exports() -> None:
    """Verify datamate.ingestion exports contracts, builders, and helpers."""
    from datamate.ingestion import (
        ColumnMetadata,
        JoinEdge,
        PreparationConfig,
        SchemaCatalog,
        SchemaCatalogBuilder,
        TableMetadata,
        prepare_business,
    )
    from datamate.ingestion.join_graph import JoinGraphNavigator
    from datamate.ingestion.metadata_adapter import BusinessContextSchemaReader

    assert callable(prepare_business)
    assert PreparationConfig is not None
    assert JoinGraphNavigator is not None
    assert BusinessContextSchemaReader is not None

    col = ColumnMetadata(name="id", data_type="INTEGER")
    table = TableMetadata(name="orders", columns=(col,))
    builder = SchemaCatalogBuilder()
    catalog = builder.build([table])
    assert len(catalog.tables) == 1
    assert catalog.tables[0].name == "orders"


def test_canonical_context_exports() -> None:
    """Verify datamate.context exports rule models, services, and compilers."""
    from datamate.context import (
        BusinessContext,
        BusinessContextService,
        BusinessRule,
        BusinessRuleCompiler,
        ContractBuilder,
        RuleCatalog,
        RuleResolver,
    )

    rule = BusinessRule(
        rule_id="r1",
        text="active orders",
        source="rulebook",
        scope="orders",
        precedence=1,
    )
    assert rule.rule_id == "r1"
    assert BusinessContextService is not None
    assert BusinessRuleCompiler is not None
    assert RuleResolver is not None


def test_canonical_grounding_exports() -> None:
    """Verify datamate.grounding exports core contracts and engine."""
    from datamate.grounding import (
        OperationKind,
        QuestionGroundingEngine,
        QuestionRequest,
        ResolvedTimeRange,
    )

    req = QuestionRequest(
        question_id="q1",
        business_id="b1",
        question="Doanh thu hôm nay là bao nhiêu?",
        as_of_date="2026-08-27",
    )
    assert req.question == "Doanh thu hôm nay là bao nhiêu?"
    assert QuestionGroundingEngine is not None
    assert OperationKind is not None


def test_canonical_planner_exports() -> None:
    """Verify datamate.planner exports LLM models, options, and parsers."""
    from datamate.planner import (
        BaseLLM,
        ChatMessage,
        GenerationDiagnostics,
        GenerationOptions,
        GenerationResult,
        ModelConfig,
        Text2SQLGenerator,
        VLLMModel,
        load_config,
    )
    from datamate.planner.errors import InferenceError, LLMError, ModelLoadError
    from datamate.planner.parser import parse_text2sql_response
    from datamate.planner.prompt import build_text2sql_messages

    assert issubclass(VLLMModel, BaseLLM)
    assert issubclass(ModelLoadError, LLMError)
    assert issubclass(InferenceError, LLMError)
    assert callable(parse_text2sql_response)
    assert callable(build_text2sql_messages)

    opts = GenerationOptions(max_new_tokens=4096, thinking_token_budget=2048)
    assert opts.thinking_token_budget == 2048


def test_canonical_execution_exports() -> None:
    """Verify datamate.execution exports execution functions and schemas."""
    from datamate.execution import (
        EmptyQueryError,
        ExecutionRequest,
        ExecutionResponse,
        QueryTimeoutError,
        execute_query,
        extract_clean_sql,
        validate_read_only_sql,
    )
    from datamate.execution.schemas import SecurityViolation

    assert callable(execute_query)
    assert callable(extract_clean_sql)
    assert callable(validate_read_only_sql)
    assert issubclass(SecurityViolation, Exception)


def test_canonical_gate_exports() -> None:
    """Verify datamate.gate exports gate evaluator, writers, and contracts."""
    from datamate.gate import (
        GateAction,
        GateOutcome,
        GateRequest,
        SubmissionFinalizer,
        SubmissionWriter,
        evaluate_gate,
    )
    from datamate.gate.contracts import AnswerType, Decision, ReleaseStatus
    from datamate.gate.formatter import format_answer
    from datamate.gate.retry import decide_retry

    assert callable(evaluate_gate)
    assert callable(format_answer)
    assert callable(decide_retry)
    assert SubmissionWriter is not None
    assert SubmissionFinalizer is not None


def test_canonical_pipeline_exports() -> None:
    """Verify datamate.pipeline exports the unified Pipeline orchestrator."""
    from datamate.pipeline import B0Pipeline, Pipeline

    assert Pipeline is B0Pipeline
    mock_gen = MagicMock()
    p = Pipeline(generator=mock_gen)
    assert hasattr(p, "answer_question")
    assert hasattr(p, "run_questions")
    assert hasattr(p, "prepare_bundle")
    assert hasattr(p, "load_context")


def test_b0_pipeline_alias_compatibility() -> None:
    """Verify that B0Pipeline alias is exported from datamate and datamate.pipeline."""
    from datamate import B0Pipeline, Pipeline
    from datamate.pipeline import B0Pipeline as PipelineB0Pipeline, Pipeline as PipelineCanonical

    assert B0Pipeline is Pipeline
    assert PipelineB0Pipeline is PipelineCanonical
    assert B0Pipeline is PipelineCanonical
