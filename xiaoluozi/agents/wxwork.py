from xiaoluozi.agents.support import install, reply, stream_reply
from xiaoluozi.wecom import gate


class WxworkAgent:
    """企业微信操作。模型通过 Wecom 调用本机官方 wecom-cli。

    不选代理，不写记忆，也不打开企业微信窗口。
    """

    id = "wxwork"
    description = "处理企业微信里的联系人、文档、日程、会议、待办、邮件、微盘和消息。只打开企业微信窗口时不用这个。"
    system = (
        "你是小落子的企业微信代理。按后面的 wecom 说明调用本机官方 wecom-cli。"
        "命令没完成或没授权，就原样转述工具返回的那一句，不要编造授权步骤。"
        "回复用可读名称，不要把内部 id 写给用户。"
    )
    connector_ids = ("wecom",)
    skill_ids = ("wecom",)
    env_keys = ()
    exclusive = True

    def __init__(self, llm, skills=(), env=None):
        install(self, llm, skills, env)

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        blocked = gate()
        if blocked:
            return blocked
        return reply(self, message, context=context, intent=intent)

    def stream(self, message: str, *, context: str = "", intent: str = ""):
        blocked = gate()
        if blocked:
            yield blocked
            return
        yield from stream_reply(self, message, context=context, intent=intent)
