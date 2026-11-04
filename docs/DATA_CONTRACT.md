# DataMate Semantic Data Contract

The repository had no executable Data Contract before the B01/B02 implementation. `src/datamate/contracts.py` now defines contract version `1.0` using standard-library dataclasses; `BusinessContext.to_dict()` produces JSON-serializable output.

## Ownership

- B01 supplies physical table/column metadata, key candidates, candidate join edges, evidence, confidence and fanout warnings.
- B02 supplies source rules verbatim, stable rule IDs, scope, precedence, field references and validation state. Only explicitly structured expressions in the supported DSL can be compiled.
- Data Foundation owns source discovery, reading, normalization and profiling. It may supply `TableMetadata.profile_rows` to B01 and profiling/business metadata to `ContractBuilder`.
- Capability/answerability, question grounding and Text-to-SQL remain separate consumers. Missing fields remain missing; the builder does not infer capability or answerability.

Precedence values are `question_override=400`, `business=300`, `industry=200`, `split_default=100`, and `unknown=0`. Business scope is an explicit business README exception between a question override and shared industry/split rules.

## Status semantics

- Key candidates are candidates, not a declaration that a database constraint exists.
- Join edges inferred from observed overlap are always `uncertain`. Upstream-declared edges are `candidate` until both complete profiles and source evidence are available. Structural checks may mark declarations `validated` or `invalid`; incomplete/optional mappings remain uncertain. Equal column names without profile evidence do not create an edge.
- Document-ingested rules have `descriptive` status and preserve their source text. They are never translated from prose into executable SQL automatically.
- Structured rules may be `validated`, `invalid`, or `conflict`. Invalid/conflicting rules must not be applied by downstream systems.

## Structured expression DSL

Supported operations: `eq`, `ne`, `gt`, `gte`, `lt`, `lte`, `in`, `is_null`, `and`, `or`, `not`, `add`, `sub`, `mul`, `div`, `field`, `literal`, `sum`, `count_distinct`, and `count_rows`. Field identifiers are validated against the schema and quoted; literal values are passed as positional `?` parameters. Arbitrary SQL, functions, and subqueries are not accepted. `compile_expression()` returns `(sql_fragment, parameters)`; callers must pass both to a parameterized query API. Nested aggregates, non-finite numbers and compound literal parameters are rejected. Expression depth is limited to 32. Division promotes integer operands and uses `NULLIF` for a zero denominator. SUM over no rows and missing values retain SQL NULL semantics; financial rounding remains the responsibility of the typed output layer.

Example:

```json
{"op":"and","items":[
  {"op":"eq","field":"status","value":"Hoàn thành"},
  {"op":"gte","field":"amount","value":100}
]}
```

## Text-to-SQL boundary

The existing `input_output_text2sql.md` describes the downstream request conceptually as Data Contract + Vietnamese question + `as_of_date`. Its response (`status`, `answer_type`, `sql`, `tables_used`, `assumptions`, `reason`) is an intermediate query decision and remains distinct from the competition submission record (`id`, `type`, `answer`). The current contract deliberately does not define either question-level object or submission output.

Data profiling, business metadata and answerability constraints are nullable until their owning modules provide them. This prevents absent evidence from being serialized as invented empty facts.

## Keys, grain and completeness

`profile_is_complete` applies to the supplied rows only when their count agrees with `row_count` (if present). NULL and missing cells disqualify a key. Automatic search reports minimal single-column and two-column keys and checks at most 256 pairs per table; wider candidates may be supplied through `composite_key_candidates`. Profile-only grain is a structural row identity with evidence, not an inferred business meaning. An upstream documented `grain` is preserved with its provenance. Internal profile rows are excluded by `BusinessContext.to_dict()`.

## Resolving rules for a request

`RuleResolver.resolve(catalog, business_id, industry=None, question_id=None)` filters scope before precedence and returns `rules`, `blocked_topics` and `warnings`. Business/question rules need a catalog bound to that business. Industry headings in Markdown are retained in `BusinessRule.industry`; industry rules are excluded unless the request supplies a matching industry. Question overrides require an exact `question_id`.

Only rules with the same explicit `topic` compete. Table-row labels supply topics during ingestion; prose without a topic remains independent. Different phrasing is not automatically assumed to mean the same metric. Conflicting or invalid winners block the topic without falling back to a lower-priority rule. Descriptive winners may inform a prompt, while execution must use `compile_rule()` on a validated structured winner.

```python
from datamate.rule_compiler import BusinessRuleCompiler
from datamate.rule_resolver import RuleResolver

compiler = BusinessRuleCompiler()
rules = compiler.ingest_documents(
    ["data/train/rulebook.md", "data/train/data/biz_123/README.md"],
    business_id="biz_123",
)
applicable = RuleResolver().resolve(rules, "biz_123", industry="Nhà thuốc")
# Review applicable.blocked_topics before consuming applicable.rules.
```

## Verification

Unit tests use only the standard library:

```bash
PYTHONPATH=src python3 -m unittest discover -s tests -v
```

Opt-in real-data tests build metadata fixtures from CSV businesses `biz_111`, `biz_127` and SQLite business `biz_123`, then run B01, B02, scope resolution and JSON contract validation. SQLite connections use `mode=ro` and `query_only`. These readers live only in tests and do not define the production Data Foundation API. XLSX ingestion and question-level Text-to-SQL execution remain outside these tests.

```bash
DATAMATE_TRAIN_DIR=data/train PYTHONPATH=src python3 -m unittest discover -s tests -v
```

## Composite joins and downstream paths

`JoinEdge.left_column` and `right_column` remain the first column pair for compatibility. `additional_key_pairs` stores the remaining ordered `(left_column, right_column)` pairs; `edge.key_pairs` exposes all pairs in Python. Consumers must use every pair, not just the first pair. Validation compares whole tuples and excludes tuples containing NULL from equijoin matches. Matching individual values in each column does not prove a composite FK.

Composite candidates are inferred only when an inferred/declared composite identity has matching names in the other table (at most 64 candidates per pair of tables). Different column names require an explicit upstream mapping. These inferred edges always remain uncertain. `JoinGraphNavigator.find_path()` searches only `validated` edges. A missing validated path means metadata is unresolved, not that the question is unanswerable. `JoinPredicateCompiler.compile(edge, catalog)` quotes identifiers and includes every component of a validated catalog-owned edge. It emits a predicate, not a query, aliases or aggregation plan. The planner still owns preaggregation and fanout avoidance.

## Reviewed rulebook formula bindings

`RuleTemplateBinder` supports `revenue`, `gross_profit`, and `sold_qty_base` from the reviewed train clauses. It compares the full source clause (with NFC/whitespace normalization), not merely a topic name. A different split rule or question override stays descriptive until reviewed. No schema name is hardcoded into this library.

The caller passes a rule selected by `RuleResolver`, a role-to-column mapping, and evidence for each semantic requirement exposed by `binder.requirements(template)`. Formula fields must belong to one sales-line relation. Required evidence includes valid revenue orders, order-date scope and correct sales-line grain; gross profit additionally needs cost-at-sale and matching selling units. Missing evidence yields an invalid rule that `compile_rule()` refuses. Evidence is an upstream assertion with provenance, not a claim that this binder has verified the upstream SQL. The emitted fragment must run over the caller's correctly filtered relation. Business Context retains `requirements` and `binding_evidence` for traceability.

```python
from datamate.rule_templates import RuleTemplateBinder

binder = RuleTemplateBinder()
# source_rule must be the selected, reviewed "Lãi gộp" rule.
bound = binder.bind(
    source_rule,
    "gross_profit",
    {"line_amount": "sales.amount", "quantity": "sales.qty", "unit_cost": "sales.cost"},
    schema_catalog,
    evidence=upstream_evidence,  # required key -> non-empty source/validation trace
)
sql_fragment, parameters = compiler.compile_rule(bound, schema_catalog)
```

Production CSV/XLSX/SQLite loading, automatic free-text rule extraction and the team's Text-to-SQL integration remain separate work. Real-data tests exercise metadata contracts on CSV/SQLite and bind actual rulebook clauses to an in-memory numeric fixture; they do not constitute a full question-answer PA benchmark.

## Runnable producer adapter and service

`BaseMetadataProvider.load(business_id)` is the boundary for the team's Data Foundation. `JSONMetadataProvider` is the first adapter; it accepts a JSON envelope with `metadata_version: "1.0"`, `business_id`, `tables`, optional `relationships`, and the optional objects `data_profiling`, `business_metadata`, `answerability_constraints`. `examples/foundation_metadata.json` is a complete synthetic example. Tables use the DTO field names above, with arrays instead of tuples. Relationships omit `status`: upstream cannot force validation. Unknown fields, versions, wrong business scope, malformed profiles and unknown relationship references fail explicitly.

`BusinessContextService` receives the provider, schema builder, rule compiler and contract builder through its constructor. `prepare(business_id, documents)` composes B01/B02 and returns the contract. Missing documents remain warnings; no answerability decision is invented. A future in-process provider can implement the same ABC without changing B01/B02. This producer envelope is distinct from the serialized Business Context output.

```bash
PYTHONPATH=src python3 -m datamate \
  --metadata examples/foundation_metadata.json \
  --business-id example_shop \
  --document examples/README.md
```

`--document` can be repeated for the active rulebook and business README. The CLI emits JSON on stdout, reports input errors on stderr with exit code 1, and does not write caches or change source files.
