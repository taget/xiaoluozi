def agent_request(message: str, context: str, intent: str) -> str:
    """The user turn passed to an agent: context, the intent laya named, and the question."""
    context_text = context.strip() or "没有可用的上下文。"
    intent_text = intent.strip() or "没有识别出意图。"
    return f"当前上下文：\n{context_text}\n\n用户意图：{intent_text}\n\n用户问题：{message}"
