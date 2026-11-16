# adapters.py

Adapter B02 context và bridge GroundedQuestion sang Planner/Gate.

Source: [`adapters.py`](../../../../src/datamate/grounding/adapters.py)

## Trách nhiệm và luồng dữ liệu

Nếu planner_input có giá trị, formatter dùng neo_engine.planner_hint; nếu không dùng formatter cũ. B02ContextAdapter vẫn là interface legacy; engine mới đọc full context bằng GroundingContextIndex để giữ evidence không có trong protocol cũ.

## Interface

- `B02ContextAdapter`: Adapter wrapping a B0.2 BusinessContext to satisfy BusinessContextProtocol.
- `GroundingToPlannerAdapter`: Adapter converting GroundedQuestion into Planner prompt hints and B0.5 EvidenceProof.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
