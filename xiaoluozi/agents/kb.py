from xiaoluozi.agents.support import install, reply, stream_reply


class KbAgent:
    """Read-only lookup in the personal knowledge vault.

    It does not choose agents, write the vault, or store the turn in memory.
    """

    id = "kb"
    description = "检索个人知识库里的笔记、技术沉淀、工作记录、每日记录和待办。只检索，不改知识库，也不写入记忆。闲聊和一般问答不用这个。"
    system = """你是小落子的知识库代理。只根据 Vault 检索到的笔记回答。先看知识地图或搜索，再读笔记。回答里写出来源路径。笔记里没有的就说知识库里没有。不要编造。不要写入、提交或推送。"""
    skill_ids = ("obsidian-kb",)
    env_keys = ("OBSIDIAN_VAULT_PATH",)
    remembers = False
    memory_note = "知识库只检索，这一轮不写入记忆。"

    def __init__(self, llm, skills=(), env=None):
        install(self, llm, skills, env)

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        return reply(self, message, context=context, intent=intent)

    def stream(self, message: str, *, context: str = "", intent: str = ""):
        yield from stream_reply(self, message, context=context, intent=intent)
