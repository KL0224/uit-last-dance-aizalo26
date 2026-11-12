# Giải Thích Mã Nguồn: `normalizer.py`

`VietnameseQuestionNormalizer` là bước N0 chạy trước C1. Nó chuẩn hóa Unicode NFC và mở rộng một allowlist bảo thủ gồm các viết tắt độc lập như `DT`, `SL`, `SP`, `KH`, `hnay`, `h.nay`, `hqua`, `thg này`.

Regex dùng lookaround whole-token nên không biến `SP01` thành `sản phẩm01`. Engine giữ nguyên `QuestionRequest.question` trong output để audit, nhưng truyền bản chuẩn hóa cho C1–C5. Nếu Qwen 3B trả `QuestionIntent.normalized_question`, engine chuẩn hóa lại giá trị đó rồi dùng làm câu hỏi hiệu lực cho Temporal, Schema, Value và Answerability.

Input và output chuẩn hóa đều bị giới hạn ở 8192 ký tự trước khi đi qua phần còn lại của pipeline.

Normalizing chỉ làm rõ ngôn ngữ; việc tính ngày vẫn hoàn toàn deterministic trong `QuestionTemporalResolver` dựa trên `as_of_date`.
