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
    "main",
]
