# value_verifier.py

Tra literal bằng query parameterized và budget giới hạn.

Source: [`value_verifier.py`](../../../../src/datamate/grounding/value_verifier.py)

## Trách nhiệm và luồng dữ liệu

Một connection read-only/request; timeout Timer interrupt rồi cancel/join. Hai query tối đa, 100ms/query, 200ms tổng; tối đa năm giá trị kết quả. Cache exact LRU theo immutable index; timeout là None, không là bằng chứng dữ liệu thiếu.

## Interface

- `ValueVerificationProvider`: Xem implementation để biết chi tiết interface.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.
