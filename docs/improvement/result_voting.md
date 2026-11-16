# Plan: Voting hai vòng cho Planner và Execution

> Cập nhật 2026-11-15: yêu cầu hiện tại dùng `vote_ratio >= threshold`, có hòa nhóm dẫn đầu thì chưa accept.
> Các mô tả `>` bên dưới là kế hoạch cũ; xem `docs/code/b1/b13/voting_mechanism.md` và runner saved grounding cho hành vi hiện tại.

## 1. Đánh giá và mục tiêu

Ý tưởng phù hợp để thử nghiệm: nhiều SQL khác nhau có thể hội tụ về cùng đáp án sau execution. Cách này tương đồng với hướng lấy mẫu nhiều lời giải rồi chọn đáp án đồng thuận trong nghiên cứu Self-Consistency. Tuy nhiên, hiệu quả trên pipeline này cần được kiểm chứng bằng benchmark.

Các rủi ro chính:

- Candidate có thể cùng hiểu sai câu hỏi; vote cao không đồng nghĩa đáp án đúng.
- Cấu hình hiện tại có temperature=0, dễ sinh candidate giống nhau.
- Với k=8, bốn candidate thinking mới có thể không đủ sửa đa số sai của vòng đầu.
- Chi phí tối đa là 24 attempts với k=4 hoặc 36 attempts với k=8, gồm generation ban đầu và hai lần repair mỗi candidate.

Tài liệu dự kiến: docs/code/planner_execution_voting_plan.md. Phiên hiện ở Plan Mode nên chưa ghi file; nội dung này là đặc tả để lưu vào file khi triển khai.

## 2. Hành vi đã chốt

### Luồng xử lý

1. Chuẩn bị context và grounding một lần cho mỗi câu hỏi; giữ các fast-path hiện có.
2. Sinh k candidate, mặc định k=4, hỗ trợ 4 hoặc 8, với thinking tắt.
3. Mỗi candidate đi qua execution và gate độc lập; lỗi được phân loại retryable có tối đa hai lần repair, tức attempts 0, 1, 2.
4. Vote sau khi toàn bộ candidate vòng đầu kết thúc.
5. Nếu chưa có nhóm vượt threshold, sinh thêm 4 candidate mới với thinking bật; chúng có cùng ngân sách retry.
6. Vote cộng dồn trên k+4 candidate, giữ nguyên threshold.
7. Nếu vẫn chưa có nhóm vượt threshold, trả abstain.

Repair giữ chế độ thinking của vòng sinh candidate. Candidate vòng hai được sinh độc lập từ cùng context và grounding, không đưa đáp án vòng một vào prompt.

### Cách tính phiếu

Mỗi candidate chỉ đóng góp một phiếu từ trạng thái cuối cùng:

| Trạng thái cuối | Phiếu |
|---|---|
| Có đáp án được gate chấp nhận | Một phiếu cho nhóm đáp án tương ứng |
| unanswerable được gate xác nhận | Một phiếu cho nhóm unanswerable chung |
| Lỗi, hết retry hoặc bị gate bác bỏ | Không có phiếu, vẫn tính vào mẫu số |

Công thức: vote_ratio = số candidate trong nhóm / tổng candidate đã sinh.

- Mặc định threshold=0.5; điều kiện thắng là vote_ratio > threshold.
- Chọn nhóm có nhiều phiếu nhất và vượt threshold. Nếu hòa ở vị trí cao nhất thì coi là chưa có winner.
- Retry không tạo candidate hoặc phiếu mới.
- unanswerable do model tự khai nhưng thiếu bằng chứng không được bỏ phiếu.
- Ví dụ: 2 A + 1 unanswerable + 1 lỗi cho A tỉ lệ 2/4, chưa vượt 0.5; 3 A + 1 lỗi thắng với 3/4.

### Gom nhóm đáp án

Dùng đáp án đã được gate kiểm tra và formatter chuẩn hóa, không so SQL hoặc chuỗi raw từ execution.

- Khóa nhóm gồm answer_type và answer.
- Chuẩn hóa biểu diễn số để 1 và 1.0 cùng nhóm; không gộp boolean với number.
- Giữ nguyên chữ hoa/thường và dấu theo formatter hiện tại.
- List và table giữ thứ tự hiện có; chưa bổ sung so sánh bỏ qua thứ tự hoặc fuzzy matching.
- Nhóm unanswerable không phân biệt nội dung reason.
- Lấy outcome của candidate có ID nhỏ nhất trong nhóm thắng làm đại diện, giữ bằng chứng và provenance.

## 3. Thay đổi triển khai

### Cấu hình và giao diện

- Thêm VotingConfig vào pipeline: enabled=False, initial_candidates=4, threshold=0.5; xác thực k thuộc {4,8} và threshold hữu hạn trong [0,1).
- Khi bật voting, dùng hai profile sampling riêng, mặc định temperature=0.7, top_p=0.8, top_k=20; kế thừa các giới hạn token và penalty hiện có.
- Thêm enable_thinking: bool | None vào GenerationOptions; None giữ hành vi cấu hình model hiện tại.
- Vòng đầu đặt thinking false và bỏ thinking budget; vòng hai đặt thinking true và dùng budget cấu hình hiện có.
- Thêm tham số CLI tương ứng vào runner local và Modal. Giữ load_config() trả hai giá trị như hiện tại; truyền cấu hình voting riêng từ runner để tránh phá caller.

### Planner và backend

- Dùng batch gồm k bản input để sinh k completion độc lập; giữ backend n=1, không đổi contract trả kết quả của vLLM.
- Gán candidate_id, round_id ổn định; cho phép output trùng nhau và giữ phiếu của từng mẫu. Không ép SQL phải khác bằng vòng sinh bổ sung.
- Override thinking theo request khi áp dụng chat template; không sửa cấu hình model dùng chung hoặc load thêm engine.
- Token counting và diagnostics phải phản ánh chế độ thinking thực tế.
- Khi yêu cầu override thinking, không được âm thầm fallback sang template bỏ qua override; báo lỗi rõ nếu backend không hỗ trợ.

### Orchestration và retry

- Tạo bộ điều phối candidate dùng chung cho answer_question() và run_questions() để hai entrypoint có cùng hành vi.
- Batch theo vòng generation và từng lớp repair; chỉ repair candidate cần sửa. Không gọi đồng thời một vLLM engine từ nhiều thread.
- Cô lập lỗi từng item, giữ ánh xạ question/candidate khi batch lỗi hoặc trả thiếu kết quả; fallback không tạo thêm phiếu.
- Thêm max_retries vào gate request, mặc định 1 để giữ tương thích; voting truyền 2 và đồng bộ sang execution.
- Thay các điều kiện hard-code retry cuối trong gate bằng ngân sách request. Parse lỗi được repair; lỗi security, timeout và lỗi khác giữ phân loại retryable hiện tại.
- Các candidate chỉ ghi attempt; ghi final output một lần sau quyết định voting. Giữ nguyên submission schema.

### Audit

- Bổ sung trường tùy chọn round_id, candidate_id, attempt và trạng thái cuối cho lịch sử candidate.
- Ghi histogram nhóm, mẫu số, threshold, tỉ lệ thắng, lý do chuyển vòng hai và candidate đại diện.
- Ghi tổng tokens, thời gian, số repair và chế độ thinking thực tế.
- Phân biệt VOTING_THRESHOLD_NOT_MET với candidate riêng lẻ bị RETRY_EXHAUSTED.

## 4. Kiểm thử và tiêu chí nghiệm thu

- Kiểm tra k=4/8, threshold bằng đúng tỉ lệ không thắng, hòa phiếu, toàn bộ candidate lỗi và nhóm unanswerable thắng.
- Xác nhận lỗi vẫn nằm trong mẫu số; repair thành công chỉ có một phiếu; vòng hai dùng đúng mẫu số k+4.
- Candidate được repair tối đa hai lần; lỗi không retryable kết thúc ngay.
- Kết quả qua formatter được gom đúng; khác kiểu, khác thứ tự list/table không bị gộp nhầm.
- Xác nhận thinking false/true đến đúng chat template và diagnostics; model config dùng chung không bị sửa.
- Batch có một item lỗi không làm mất kết quả item khác; hai entrypoint cho cùng quyết định với cùng kết quả giả lập.
- Voting tắt giữ hành vi cũ, gồm giới hạn một retry và submission schema.
- Chạy regression pipeline, planner diagnostics, executor và gate cho cả contract v1/v2.

Benchmark trên cùng tập câu hỏi: baseline một candidate, voting k=4 và voting k=8. Báo cáo accuracy, coverage, precision của unanswerable, tỉ lệ chuyển vòng hai, tokens, latency và số execution. Chỉ bật mặc định sau khi benchmark chứng minh lợi ích phù hợp với chi phí.

## 5. Mặc định và giới hạn

- Voting ban đầu là opt-in; không thay cấu hình grounding.
- Dùng chung dữ liệu và context trong cả hai vòng.
- Không bổ sung LLM judge, trọng số ưu tiên thinking hoặc vòng sinh thứ ba.
- Không yêu cầu các candidate phải có SQL khác nhau; sự đa dạng đến từ sampling.
- Chưa khẳng định voting tăng accuracy trước khi có kết quả benchmark.
