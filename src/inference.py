from llm import ChatMessage, VLLMModel, GenerationOptions, load_config

config, options = load_config("configs/qwen3_5_9b.toml")
model = VLLMModel(config, options)
model.load()

result = model.chat([
    ChatMessage(role="system", content="Bạn là trợ lý trả lời bằng tiếng Việt."),
    ChatMessage(role="user", content="Giải thích self-attention."),
])

print(result.text)




reference_text = None
question = None

messages = [
    ChatMessage(
        role="system",
        content="Bạn là trợ lý phân tích dữ liệu. Chỉ kết luận dựa trên thông tin được cung cấp.",
    ),
    ChatMessage(
        role="user",
        content=f"""
            Tài liệu tham khảo:
            {reference_text}

            Câu hỏi:
            {question}
            """,
    ),
]

result = model.chat(messages)


messages = [
    ChatMessage(
        role="system",
        content=(
            "Phân loại cảm xúc của câu thành positive, negative hoặc neutral. "
            "Chỉ trả JSON theo các ví dụ."
        ),
    ),

    # Ví dụ 1
    ChatMessage(role="user", content="Sản phẩm rất tốt, tôi rất hài lòng."),
    ChatMessage(role="assistant", content='{"sentiment": "positive"}'),

    # Ví dụ 2
    ChatMessage(role="user", content="Giao hàng quá chậm, thật thất vọng."),
    ChatMessage(role="assistant", content='{"sentiment": "negative"}'),

    # Ví dụ 3
    ChatMessage(role="user", content="Tôi đã nhận được hàng hôm nay."),
    ChatMessage(role="assistant", content='{"sentiment": "neutral"}'),

    # Input thực tế cần model xử lý
    ChatMessage(role="user", content="Dịch vụ hỗ trợ rất nhiệt tình."),
]

result = model.chat(
    messages,
    options=GenerationOptions(temperature=0),
)

print(result.text)