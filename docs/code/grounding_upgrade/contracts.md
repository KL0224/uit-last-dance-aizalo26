# contracts.py

Dataclass/enum giao diện C grounding hiện hữu.

Source: [`contracts.py`](../../../../src/datamate/grounding/contracts.py)

## Trách nhiệm và luồng dữ liệu

GroundedQuestion thêm grounding_source và planner_input có default, giữ tương thích caller cũ. planner_input chứa contract v2; is_directly_unanswerable vẫn đòi missing proof checked_all_sources.

## Interface

- `OperationKind`: Primary analytical operation requested by the Vietnamese question.
- `AnswerTypeHint`: Expected answer type hints matching the competition's output types.
- `CoverageStatus`: Evidence and capability coverage status evaluated by C5 Precheck.
- `DateRole`: Semantic role of a temporal column in business operations.
- `QuestionRequest`: Normalized incoming question request with anchor as_of_date.
- `FilterCondition`: A filter condition extracted from the question before/after value grounding.
- `QuestionIntent`: Structured semantic representation of the user's question (C1 output).
- `ResolvedTimeRange`: Deterministic date range resolved from relative expressions and as_of_date (C2 output).
- `SchemaCandidate`: A candidate table and its relevant columns ranked by C3 Schema Grounder.
- `CandidateJoinPath`: A validated join path between two tables from the Join Graph.
- `SelectedSchema`: Selected tables, columns, and safe join paths for the Planner (C3 output).
- `MatchedValue`: Grounded database value linked from an entity or filter phrase (C4 output).
- `EvidenceRequirement`: Required capability or domain concept needed to answer the question.
- `MissingEvidenceProof`: Catalog-verified proof of missing evidence when a question is UNSUPPORTED (C5 output).
- `GroundedQuestion`: Deliverable contract of Component C passed to Component D (Planner) and G (Gate).

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
