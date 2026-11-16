# neo_prompt.py

Source: [neo_prompt.py](../../../../src/datamate/grounding/neo_prompt.py).

`PROMPT_VERSION=neo-partial-v6`. System prompt được rút từ 9.664 xuống 7.330 ký tự so với v5 (khoảng 24%); đây là số ký tự, không phải số token Qwen. Giữ ba ví dụ bổ sung nhau: cohort khách/đơn, MTD matched-days và ratio hai measures có filter `=` lấy từ policy. Schema giả chỉ gửi một lần trong phần examples. Ví dụ không chứa evaluation IDs, baseline hoặc binding business thật.

Các khối chỉ dẫn: nhiệm vụ/input, JSON bắt buộc, measures/grain/operands, thời gian, filters/nguồn và kiểm tra cuối. JSON Schema vẫn truyền riêng cho sampler. Không yêu cầu model xuất suy luận hay SQL.

Temporal giữ explicit components theo kind, ba cách biểu diễn comparison, date role, lịch âm/range/snapshot và nguyên tắc unresolved. Không thay năm/tháng được hỏi bằng as_of_date. Operands [A,B] có nghĩa A-B, A/B hoặc (A-B)/B*100; không lặp measure chỉ vì so kỳ. JOIN phải đúng nguồn/khóa; policy có đủ binding phải thành filter. Những chỉ dẫn này không tự chứng minh model hiểu đúng câu hỏi.

Production dùng tokenizer backend để kiểm budget. [context_budget.py](context_budget.md) ưu tiên capability của nguồn và bảo vệ cột cần thiết trước khi cắt bằng chứng. Ví dụ được kiểm qua WireProposal; chất lượng ngữ nghĩa và token budget thực tế vẫn cần inference mới.
