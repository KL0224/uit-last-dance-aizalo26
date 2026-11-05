"""Dependency-injected orchestration for business semantic preparation."""

from __future__ import annotations

from pathlib import Path

from datamate.contracts import BusinessContext, ContractBuilder
from datamate.metadata_adapter import BaseMetadataProvider
from datamate.rule_compiler import BusinessRuleCompiler
from datamate.schema_catalog import SchemaCatalogBuilder


class BusinessContextService:
    """Combine a metadata provider and B01/B02 without depending on an LLM."""

    def __init__(
        self,
        provider: BaseMetadataProvider,
        schema_builder: SchemaCatalogBuilder,
        rule_compiler: BusinessRuleCompiler,
        contract_builder: ContractBuilder,
    ) -> None:
        self.provider = provider
        self.schema_builder = schema_builder
        self.rule_compiler = rule_compiler
        self.contract_builder = contract_builder

    def prepare(self, business_id: str, documents: list[str | Path]) -> BusinessContext:
        """Build a business context; missing documents remain explicit warnings."""
        metadata = self.provider.load(business_id)
        if metadata.business_id != business_id:
            raise ValueError("metadata provider returned another business")
        schema = self.schema_builder.build(
            list(metadata.tables), list(metadata.relationships)
        )
        rules = self.rule_compiler.ingest_documents(documents, business_id, schema)
        return self.contract_builder.build(
            business_id,
            schema,
            rules,
            metadata.data_profiling,
            metadata.business_metadata,
            metadata.answerability_constraints,
        )
