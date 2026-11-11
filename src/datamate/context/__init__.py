"""B0.2 Context & Business Rules package for DataMate - Zalo AI Challenge 2026."""

from .cli import main
from .context_service import BusinessContextService
from .contracts import (
    CONTRACT_VERSION,
    BusinessContext,
    BusinessRule,
    ContractBuilder,
    RuleCatalog,
)
from .rule_compiler import BusinessRuleCompiler
from .rule_resolver import PRECEDENCE, ResolvedRules, RuleResolver
from .rule_templates import RuleTemplateBinder
from .semantic_extractor import (
    LLMSemanticExtractor,
    RuleSchemaMatcher,
    create_semantic_extractor,
)

__all__ = [
    "CONTRACT_VERSION",
    "BusinessRule",
    "RuleCatalog",
    "BusinessContext",
    "ContractBuilder",
    "BusinessContextService",
    "BusinessRuleCompiler",
    "PRECEDENCE",
    "ResolvedRules",
    "RuleResolver",
    "RuleTemplateBinder",
    "LLMSemanticExtractor",
    "RuleSchemaMatcher",
    "create_semantic_extractor",
    "main",
]
