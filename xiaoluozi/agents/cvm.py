from xiaoluozi.agents.support import install, reply, stream_reply


class CvmAgent:
    """CVM operations. The yunxiao-ops skill is on the system prompt.

    It does not choose agents or write memory. When the model returns a tool
    call the skill allows, that call is run and the result goes back to the model.
    """

    id = "cvm"
    description = "处理 CVM 运营和云霄运维。查售卖，库存、宿主机、配额、实例、机型这类句子用这个。"
    system = '''
你是小落子的 CVM 运营代理。按后面的 yunxiao-ops 说明处理云霄和 CVM 运维。不知道就说不知道，不要随意回答。

对于负责的任务，先规划好执行计划，再开始行动，避不必要的无意义重试动作。

返回内容如果有表格图表等，使用 html 格式渲染好，不要直接返回 markdown 格式。
'''
    skill_ids = ("yunxiao-ops",)
    env_keys = ("YUNXIAO_SECRET_ID", "YUNXIAO_SECRET_KEY", "YUNXIAO_API_URL")

    def __init__(self, llm, skills=(), env=None):
        install(self, llm, skills, env)

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        return reply(self, message, context=context, intent=intent)

    def stream(self, message: str, *, context: str = "", intent: str = ""):
        yield from stream_reply(self, message, context=context, intent=intent)
