from xiaoluozi.agents.support import install, reply, stream_reply


class PerfGapAgent:
    """Cloud-versus-physical performance gap. Read the pasted evidence and plan the next step.

    It does not choose agents, write memory, open a shell, or change a host.
    """

    id = "perf_gap"
    description = (
        "处理云主机相对物理机的性能差距，尤其是吞吐下降约 20%–40% 的专项排障。"
        "只根据贴来的成绩和采集结果给出采集缺口、分层判断、实验计划和 RCA 草稿。"
        "不改配置，不跑压测。查库存、配额、售卖，以及一般 vstation 报错不用这个。"
    )
    system = (
        "你是小落子的云主机性能差距排障代理。按后面的 perf-gap 说明工作。"
        "材料不够时只给指标口径、公平性核对和采集清单，并写明现在不能认定根因。"
        "不要把业务差距直接写成虚拟化开销。"
        "不要建议在客户生产实例上改绑核、NUMA、QEMU 或规格。"
        "不要发起 SSH、压测或配置修改。实验和修复只写成待审批的计划。"
    )
    skill_ids = ("perf-gap",)
    env_keys = ()
    consultable = True

    def __init__(self, llm, skills=(), env=None):
        install(self, llm, skills, env)

    def handle(self, message: str, *, context: str = "", intent: str = "") -> str:
        return reply(self, message, context=context, intent=intent)

    def stream(self, message: str, *, context: str = "", intent: str = ""):
        yield from stream_reply(self, message, context=context, intent=intent)
