"""B0.1 Loader & Schema/Join Catalog package for DataMate - Zalo AI Challenge 2026."""

from .contracts import (
    ColumnMetadata,
    JoinEdge,
    JoinStatistics,
    KeyCandidate,
    RelationshipEvidence,
    SchemaCatalog,
    TableMetadata,
)
from .join_graph import JoinGraphNavigator, JoinPathResult, JoinPredicateCompiler
from .metadata_adapter import (
    BaseMetadataProvider,
    BusinessContextSchemaReader,
    FoundationMetadata,
    JSONMetadataProvider,
)
from .schema_catalog import SchemaCatalogBuilder
from . import ingestion
from .ingestion import (
    PreparationConfig,
    PreparationError,
    PreparedBusinessArtifacts,
    prepare_business,
)

__all__ = [
    "ColumnMetadata",
    "TableMetadata",
    "KeyCandidate",
    "JoinEdge",
    "JoinStatistics",
    "RelationshipEvidence",
    "SchemaCatalog",
    "JoinGraphNavigator",
    "JoinPathResult",
    "JoinPredicateCompiler",
    "BaseMetadataProvider",
    "FoundationMetadata",
    "JSONMetadataProvider",
    "BusinessContextSchemaReader",
    "SchemaCatalogBuilder",
    "PreparationConfig",
    "PreparationError",
    "PreparedBusinessArtifacts",
    "prepare_business",
    "ingestion",
]



