"""B0.1 Loader & Schema/Join Catalog package for DataMate - Zalo AI Challenge 2026."""

from .contracts import (
    ColumnMetadata,
    JoinEdge,
    KeyCandidate,
    SchemaCatalog,
    TableMetadata,
)
from .join_graph import JoinGraphNavigator, JoinPredicateCompiler
from .metadata_adapter import (
    BaseMetadataProvider,
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
    "SchemaCatalog",
    "JoinGraphNavigator",
    "JoinPredicateCompiler",
    "BaseMetadataProvider",
    "FoundationMetadata",
    "JSONMetadataProvider",
    "SchemaCatalogBuilder",
    "PreparationConfig",
    "PreparationError",
    "PreparedBusinessArtifacts",
    "prepare_business",
    "ingestion",
]



