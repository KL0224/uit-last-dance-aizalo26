"""Component C: Question Grounding package for DataMate 2026."""

from .adapters import (
    B02ContextAdapter,
    BusinessContextAdapter,
    GroundingToPlannerAdapter,
)
from .answerability import AnswerabilityPrechecker
from .contracts import (
    AnswerTypeHint,
    CandidateJoinPath,
    CoverageStatus,
    DateRole,
    EvidenceRequirement,
    FilterCondition,
    GroundedQuestion,
    MatchedValue,
    MissingEvidenceProof,
    OperationKind,
    QuestionIntent,
    QuestionRequest,
    ResolvedTimeRange,
    SchemaCandidate,
    SelectedSchema,
)
from .engine import QuestionGroundingEngine
from .llm_fallback import (
    EXTRACTOR_SYSTEM_PROMPT,
    StructuredLLMParser,
    create_qwen3b_vllm_parser,
)
from .mock_provider import InMemoryBusinessContext, MockBusinessContextProvider
from .normalizer import VietnameseQuestionNormalizer
from .parser import FallbackDecision, QuestionIntentParser
from .protocols import (
    BusinessContextProtocol,
    CalendarEventSpec,
    ColumnSpec,
    JoinSpec,
    LLMParserProtocol,
    MetricSpec,
    TableSpec,
)
from .rules_matcher import VietnameseRuleMatcher
from .runtime import (
    GROUNDING_BUSINESS_MISMATCH,
    GROUNDING_CONTEXT_INVALID,
    GROUNDING_FAILED,
    GROUNDING_REQUEST_INVALID,
    QuestionGroundingRuntime,
    QuestionGroundingRuntimeError,
)
from .schema_grounder import SchemaGrounder
from .temporal import QuestionTemporalResolver
from .value_grounder import ValueGrounder

__all__ = [
    "OperationKind",
    "AnswerTypeHint",
    "CoverageStatus",
    "DateRole",
    "QuestionRequest",
    "FilterCondition",
    "QuestionIntent",
    "ResolvedTimeRange",
    "SchemaCandidate",
    "CandidateJoinPath",
    "SelectedSchema",
    "MatchedValue",
    "EvidenceRequirement",
    "MissingEvidenceProof",
    "GroundedQuestion",
    "ColumnSpec",
    "TableSpec",
    "JoinSpec",
    "MetricSpec",
    "CalendarEventSpec",
    "BusinessContextProtocol",
    "LLMParserProtocol",
    "InMemoryBusinessContext",
    "MockBusinessContextProvider",
    "VietnameseQuestionNormalizer",
    "VietnameseRuleMatcher",
    "EXTRACTOR_SYSTEM_PROMPT",
    "StructuredLLMParser",
    "create_qwen3b_vllm_parser",
    "QuestionIntentParser",
    "FallbackDecision",
    "QuestionTemporalResolver",
    "SchemaGrounder",
    "ValueGrounder",
    "AnswerabilityPrechecker",
    "QuestionGroundingEngine",
    "GROUNDING_BUSINESS_MISMATCH",
    "GROUNDING_CONTEXT_INVALID",
    "GROUNDING_FAILED",
    "GROUNDING_REQUEST_INVALID",
    "QuestionGroundingRuntime",
    "QuestionGroundingRuntimeError",
    "B02ContextAdapter",
    "BusinessContextAdapter",
    "GroundingToPlannerAdapter",
]
