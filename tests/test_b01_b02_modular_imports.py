"""Verify that modular imports directly from datamate.b0.b01 and datamate.b0.b02 work seamlessly."""

from datamate.b0.b01 import (
    BaseMetadataProvider,
    ColumnMetadata,
    FoundationMetadata,
    JSONMetadataProvider,
    JoinEdge,
    JoinGraphNavigator,
    JoinPredicateCompiler,
    KeyCandidate,
    SchemaCatalog,
    SchemaCatalogBuilder,
    TableMetadata,
)
from datamate.b0.b02 import (
    CONTRACT_VERSION,
    BusinessContext,
    BusinessContextService,
    BusinessRule,
    BusinessRuleCompiler,
    ContractBuilder,
    PRECEDENCE,
    ResolvedRules,
    RuleCatalog,
    RuleResolver,
    RuleTemplateBinder,
)


def test_b01_exports() -> None:
    from datamate.b0.b01 import prepare_business, PreparationConfig
    assert callable(prepare_business)
    assert PreparationConfig is not None

    col = ColumnMetadata(name="id", data_type="INTEGER")
    table = TableMetadata(name="users", columns=(col,))
    builder = SchemaCatalogBuilder()
    catalog = builder.build([table])
    assert len(catalog.tables) == 1
    assert catalog.tables[0].name == "users"


def test_b02_exports() -> None:
    col = ColumnMetadata(name="id", data_type="INTEGER")
    table = TableMetadata(name="users", columns=(col,))
    builder = SchemaCatalogBuilder()
    catalog = builder.build([table])

    rule = BusinessRule(
        rule_id="r1",
        text="Rule 1",
        source="doc",
        scope="business",
        precedence=300,
    )
    rule_catalog = RuleCatalog(rules=(rule,), business_id="biz1")

    cb = ContractBuilder()
    context = cb.build(
        business_id="biz1",
        schema_catalog=catalog,
        rule_catalog=rule_catalog,
    )
    assert context.business_id == "biz1"
    assert context.contract_version == CONTRACT_VERSION
    assert len(context.schema_catalog.tables) == 1
    assert len(context.rule_catalog.rules) == 1

