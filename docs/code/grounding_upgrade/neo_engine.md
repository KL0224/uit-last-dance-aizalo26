# neo_engine.py

Điều phối Qwen một lần rồi verify, trả GroundedQuestion tương thích pipeline.

Source: [`neo_engine.py`](../../../../src/datamate/grounding/neo_engine.py)

## Trách nhiệm và luồng dữ liệu

from_qwen dùng QwenStructuredBackend với schema-constrained decoding bắt buộc, chỉ nạp một instance. Token counter dùng tokenizer backend; constructor inject fake chat/token counter phục vụ CPU tests. JSON lỗi không retry. last_diagnostics nằm ngoài Planner payload. planner_hint dùng cùng JSON khi generate và repair.

## Interface

- `planner_hint`: Xem implementation để biết chi tiết interface.
- `NeoGroundingEngine`: Xem implementation để biết chi tiết interface.

## Tích hợp và kiểm tra

Xem [overall_neo_grounding.md](overall_neo_grounding.md) cho contract, chế độ chạy, fallback và giới hạn verification. Chạy `uv run pytest tests/grounding tests/test_grounded_planner_bridge.py tests/test_datamate_pipeline.py` để kiểm hồi quy.

## Sửa sau smoke inference thực tế

Prompt trimming loại JOIN stats trước schema và không bỏ schema card cuối. Nếu phần bắt buộc không vừa budget thì fail trước khi gọi model. Prompt yêu cầu JSON compact, bỏ optional fields không dùng và exact qualified refs. Không tự đoán tên bảng cho bare columns.

`debug_model_output=False` mặc định. Khi bật, diagnostics ghi raw response; luôn ghi stage và elapsed_ms cả khi fail. Chat factory lưu input/output tokens, finish_reason và output limit qua `chat_fn.last_generation`. `finish_reason=length` được báo GROUNDING_OUTPUT_TRUNCATED, không nhận JSON dở dang. Model budget mới 2048 output thay cho 768 sau khi run cũ trả EOF/invalid JSON; cần benchmark lại GPU.

## Proposal v3

Luồng production dùng ReferenceMap + WireProposal; schema nằm trong sampler, không đưa vào prompt. Prompt version neo-compact-v3, tham khảo neo_prompt.md, compact_proposal.md, neo_backend.md. Tests legacy có thể inject compact_proposals=False để giữ physical Proposal; factory production luôn bật compact và constrained decoding.

## Luồng hiện tại: neo-partial-v6

`GroundingContextIndex -> ReferenceMap.context -> fit_context -> one Qwen call -> parse_partial_proposal -> verify_proposal -> partial Planner contract`.

Xem [context_budget.md](context_budget.md) cho xếp hạng/bảo vệ nguồn/cột; [proposal_recovery.md](proposal_recovery.md) cho parse từng claim; [neo_verifier.md](neo_verifier.md) cho dependency recovery. Các mô tả v3 phía trên là lịch sử triển khai.

Diagnostics bổ sung context_budget, rejected_claims (số claim), blocked_refs (số measure). JSON không đọc được, output bị truncate và root/business không hợp lệ vẫn failed. Item/group bị loại có thông tin hữu ích còn lại thì trả partial; giữ tám nhóm contract v2.0 và adapter hiện có.
