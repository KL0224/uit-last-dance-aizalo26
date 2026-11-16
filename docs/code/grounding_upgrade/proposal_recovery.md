# proposal_recovery.py

Source: [proposal_recovery.py](../../../../src/datamate/grounding/proposal_recovery.py).

`parse_partial_proposal(raw, refs)` giữ validation chặt ở JSON syntax và root intent/source fields; production wire vẫn yêu cầu `time`. Không chấp nhận thêm root fields không có trong contract. JSON không đọc được, root không hợp lệ hoặc không còn nguồn hợp lệ vẫn là lỗi toàn request.

Optional groups được parse từng item qua chính bounded Pydantic model và ReferenceMap. Item lỗi schema hoặc alias không tồn tại bị loại riêng, ghi raw claim/reason/group/ref/affects vào rejected_claims. Item đúng không mất theo. Field vượt giới hạn không bị cắt âm thầm: phần vượt được ghi là rejected requirement. Literal không được thay alias, không fuzzy-map hoặc đoán cột vật lý.

Không tự thêm measure thiếu, đổi cột ngày, thêm nguồn JOIN hoặc chữa công thức. Sau materialization, neo_verifier kiểm dependencies giữa các item. Strict `WireProposal.model_validate` và `ReferenceMap.materialize` vẫn có thể dùng riêng khi caller cần fail-fast validation.
