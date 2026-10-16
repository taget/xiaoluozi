from xiaoluozi.agents.support import install
from xiaoluozi.errors import ReplyError
from xiaoluozi.knot_mcp import KnotMcp, citation_tail, search_keywords
from xiaoluozi.log import get_logger

logger = get_logger("xiaoluozi.cvm_low_level")

_NOT_CONFIGURED = "Knot 还没配好。在 .env 里设置 KNOT_API_TOKEN 后再试。"
_EMPTY = "知识库里没有查到相关记录。"


class CvmLowLevelAgent:
    """Search the CVM low-level knowledge base through Knot MCP, then answer from those excerpts."""

    id = "cvm_low_level"
    description = (
        "检索 CVM 底层知识库。虚拟化实现、子机拉起、compute、libvirt 这类底层文档用这个。"
        "只检索，不写入记忆。查库存、配额和线上排障不用这个。"
    )
    system = (
        "你是小落子的 CVM 底层知识库代理。只根据检索结果回答，并写出来源标题。"
        "不要自己编造链接，文档链接会附在回答末尾。"
        "检索结果里没有的就说知识库里没有。不要编造。"
    )
    skill_ids = ()
    service_ids = ("Knot",)
    env_keys = ("KNOT_API_TOKEN",)
    remembers = False
    memory_note = "CVM 底层知识库只检索，这一轮不写入记忆。"
    consultable = True

    def __init__(self, llm, skills=(), env=None, search=None):
        install(self, llm, skills, env)
        self._search = search

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        return "".join(self.stream(message, context=context, intent=intent))

    def stream(self, message: str, *, context: str = "", intent: str = ""):
        material = self._material(message)
        if not material:
            yield _EMPTY
            return
        # 意图分类和本地对话不交给模型。模型曾把「在拿主意」当成要检索的主题。
        request = f"用户问题：{message.strip()}\n\n知识库检索结果：\n{material}"
        source = getattr(self._llm, "stream", None)
        if source is None:
            text = self._llm.answer(
                self.system, request, env=self._env, remember=False, recall_query=message
            )
            shown = f"{text or ''}{citation_tail(text or '', material)}"
            if shown.strip():
                yield shown
            return
        parts = []
        for piece in source(self.system, request, env=self._env, remember=False, recall_query=message):
            if not piece:
                continue
            parts.append(piece)
            yield piece
        tail = citation_tail("".join(parts), material)
        if tail:
            yield tail

    def _material(self, message: str) -> str:
        token = (self._env.get("KNOT_API_TOKEN") or "").strip()
        if not token:
            logger.info("知识库检索被拒绝 未配置")
            raise ReplyError(_NOT_CONFIGURED)
        if self._search is not None:
            return self._search(message)
        query = message.strip()
        logger.info("知识库检索 %s", query[:80])
        return KnotMcp(token).search(query, search_keywords(query))
