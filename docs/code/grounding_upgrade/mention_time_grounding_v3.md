# Grounding v3: mentions and detailed time

`NeoGroundingEngine` now makes one Qwen2.5-3B call to extract question spans and
structured temporal expressions. It does not generate a semantic execution plan.
The planner owns operation, answer type, source tables, column bindings, formulas,
aggregation grain, predicates, JOINs, cohorts, units, ordering and limits.

## Model output

Exactly six root fields are required. Unused arrays are empty. Mention IDs must
be unique across all groups and temporal expressions. Mention text and temporal
`raw_expression` must occur verbatim in the question (Unicode NFC and whitespace
normalization are allowed during verification). Mention groups preserve question
order. The model must preserve spelling, accents and abbreviations.

```json
{
  "metric_mentions": [{"id": "m1", "text": "Doanh thu"}],
  "entity_mentions": [],
  "condition_mentions": [],
  "temporal_intent": "single_period",
  "time": [{
    "id": "t1",
    "raw_expression": "tháng 3/2026",
    "kind": "month",
    "calendar": "gregorian",
    "year": 2026,
    "month": 3,
    "period_extent": "full_period",
    "comparison": "none",
    "role": "primary",
    "applies_to": ["m1"]
  }],
  "unresolved": []
}
```

Temporal fields retain calendar, kind, explicit date components, leap-month
selection, relative periods, count, extent, role, comparison, comparison_days,
Gregorian and lunar endpoints. `applies_to` references mention IDs, not measures
or database objects. An empty scope means the entire question. There is no
`column` or `date_role`; the planner binds windows to the correct event dates.

Explicit components cannot coexist with `relative`. Explicit months and quarters
require their month/quarter number. Unknown comparison/extent stays unresolved;
it does not become a default current period. Today/yesterday use explicit ranges.
Snapshot `end` is inclusive; range `end` is exclusive. The calendar resolver
materializes MTD, previous-year, previous-equal-days, lunar, Tet, snapshot and
recurrence windows with the existing calendar policies.

## Input and verification

The model receives the question, `as_of_date`, the rulebook's time section and
bounded business time notes. Schema, table aliases, JOIN candidates, unit
registries and metric registries are excluded. Essential temporal policies and
the question are never silently trimmed to fit a token budget.

`mention_contracts.py` defines the constrained decoding schema. Invalid individual
mentions/time specs are retained as rejection diagnostics without dropping valid
independent items. Duplicate IDs, fabricated spans, missing scopes, invalid
calendar specs and unpaired comparisons stay visible as unresolved requirements.
Syntactic validation cannot establish that every requirement was extracted or
that an interpretation is semantically correct.

## Planner contract

Code adds `request.contract_version = "3.0"`, the verified mentions/time specs,
`temporal_plan.resolved_windows` and `assessment`. Each window records its
`source_time_id`, role, scope, calculated bounds and calendar fingerprint.
Snapshot windows retain an unbounded history start; recurring dates retain their
range list. `completeness_status` describes temporal representation only.

`assessment.validation_status` is `valid` or `partial`; coverage always remains
`unknown`. The legacy `GroundedQuestion` wrapper reports unknown operation and
answer type. Gate evidence does not claim a catalog coverage check.

`planner_hint` dispatches on contract version. Both generation and repair receive
the same v3 evidence and instructions to bind date columns, preserve bounds,
check the original question, and reconstruct unresolved constraints. Historical
v2 artifacts and their verifier/schema helpers remain readable; new model calls
always use v3, including callers passing the old `compact_proposals` argument.

The Modal grounding job freezes prompt and contract versions in run settings.
Per-question checkpoints also record prompt version, so regeneration cannot
silently mix the previous extraction design into a new run. Use a new run name
when moving from the old grounding prompt; replaying saved v2 artifacts remains
supported.

## Validation

Local tests use fake model responses and the real calendar resolver, DuckDB and
planner/gate paths. They cover explicit historical months, MTD comparisons, Tet,
series, snapshots, malformed items, duplicate IDs, provenance, planner repair
hints and two-phase evaluation. These tests do not measure live Qwen accuracy;
a fresh GPU run is needed to compare against eval50.
