"""Dependency-injected orchestration for business semantic preparation."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from datamate.ingestion.metadata_adapter import BaseMetadataProvider
from datamate.ingestion.schema_catalog import SchemaCatalogBuilder

from .contracts import BusinessContext, ContractBuilder
from .rule_compiler import BusinessRuleCompiler


class BusinessContextService:
    """Combine a metadata provider and B01/B02 without depending on an LLM."""

    def __init__(
        self,
        provider: BaseMetadataProvider,
        schema_builder: SchemaCatalogBuilder,
        rule_compiler: BusinessRuleCompiler,
        contract_builder: ContractBuilder,
        semantic_extractor: Any | None = None,
    ) -> None:
        self.provider = provider
        self.schema_builder = schema_builder
        self.rule_compiler = rule_compiler
        self.contract_builder = contract_builder
        self.semantic_extractor = semantic_extractor

    def prepare(self, business_id: str, documents: list[str | Path]) -> BusinessContext:
        """Build a business context; missing documents remain explicit warnings."""
        metadata = self.provider.load(business_id)
        if metadata.business_id != business_id:
            raise ValueError("metadata provider returned another business")
        schema = self.schema_builder.build(
            list(metadata.tables), list(metadata.relationships), business_id=business_id
        )
        rules = self.rule_compiler.ingest_documents(documents, business_id, schema)
        semantic_catalog = None
        if self.semantic_extractor is not None:
            try:
                semantic_catalog = self.semantic_extractor.extract_semantic_catalog(
                    business_id=business_id,
                    schema=schema,
                    rules=rules.rules,
                )
            except Exception:
                semantic_catalog = None
        if semantic_catalog is None:
            try:
                from .semantic_extractor import RuleSchemaMatcher
                semantic_catalog = RuleSchemaMatcher().extract_semantic_catalog(
                    business_id=business_id,
                    schema=schema,
                    rules=rules.rules,
                )
            except Exception:
                semantic_catalog = None

        return self.contract_builder.build(
            business_id,
            schema,
            rules,
            metadata.data_profiling,
            metadata.business_metadata,
            metadata.answerability_constraints,
            metadata.normalized_data_handle,
            semantic_catalog=semantic_catalog,
        )
