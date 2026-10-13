def agent_request(message: str, context: str, intent: str, roster_note: str = "") -> str:
    """The user turn passed to an agent: context, the intent laya named, and the question.

    The roster stays after the question. Recalled memories sit in the context above it,
    and Hindsight appends more memories to the system prompt. The current list has to
    be the last thing the model reads, or it repeats an old roster.
    """
    context_text = context.strip() or "没有可用的上下文。"
    intent_text = intent.strip() or "没有识别出意图。"
    text = f"当前上下文：\n{context_text}\n\n用户意图：{intent_text}\n\n用户问题：{message}"
    note = roster_note.strip()
    if note:
        text = f"{text}\n\n{note}"
    return text


def enabled_agent_note(agents: list[tuple[str, str]], default_agent: str) -> str:
    """The enabled roster. The answering model does not see the laya candidate list."""
    if not agents:
        return ""
    lines = []
    for agent_id, description in agents:
        suffix = "（默认）" if agent_id == default_agent else ""
        lines.append(f"- {agent_id}：{description}{suffix}")
    listed = "\n".join(lines)
    return (
        "当前已启用的代理：\n"
        f"{listed}\n"
        "用户问现在有哪些代理时，只按这份名单回答，并标明默认代理。不要改用记忆里的旧名单。"
    )
