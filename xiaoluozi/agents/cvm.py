from xiaoluozi.agents.support import install, reply


class CvmAgent:
    """CVM operations. The yunxiao-ops skill is on the system prompt.

    It does not choose agents or write memory. When the model returns a tool
    call the skill allows, that call is run and the result goes back to the model.
    """

    id = "cvm"
    description = "处理 CVM 运营和云霄运维。查库存、宿主机、配额、实例、机型这类句子用这个。"
    system = "你是小落子的 CVM 运营代理。按后面的 yunxiao-ops 说明处理云霄和 CVM 运维。不知道就说不知道，不要编造。"
    skill_ids = ("yunxiao-ops",)
    env_keys = ("YUNXIAO_SECRET_ID", "YUNXIAO_SECRET_KEY", "YUNXIAO_API_URL")

    def __init__(self, llm, skills=(), env=None):
        install(self, llm, skills, env)

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        return reply(self, message, context=context, intent=intent)
