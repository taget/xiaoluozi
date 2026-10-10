import json

from tests.fakes import FakeLlm, FakeMemory, FakeModel
from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.agents.kb import KbAgent
from xiaoluozi.loop import Loop
from xiaoluozi.model import LlmClient
from xiaoluozi.registry import Registry
from xiaoluozi.router import Router
from xiaoluozi.skills import SkillCatalog
from xiaoluozi.tools import run_tool
from xiaoluozi.vault import NOT_CONFIGURED


class _Message:
    def __init__(self, content):
        self.content = content


class _Choice:
    def __init__(self, content):
        self.message = _Message(content)


class _Response:
    def __init__(self, content):
        self.choices = [_Choice(content)]


class _Completions:
    def __init__(self, content, *, reject_hindsight=False):
        self.content = content
        self.calls = []
        self.reject_hindsight = reject_hindsight

    def create(self, **kwargs):
        if self.reject_hindsight and any(key.startswith("hindsight_") for key in kwargs):
            raise TypeError("Completions.create() got an unexpected keyword argument 'hindsight_inject_memories'")
        self.calls.append(kwargs)
        return _Response(self.content)


class _Client:
    def __init__(self, completions):
        self.chat = self
        self.completions = completions


def _vault(tmp_path):
    note = tmp_path / "superme" / "10-技术"
    note.mkdir(parents=True)
    (note / "云计算性能排障.md").write_text("排障先看宿主机水位。", encoding="utf-8")
    index = tmp_path / "superme" / "00-索引"
    index.mkdir()
    (index / "MOC.md").write_text("[[云计算性能排障]]", encoding="utf-8")
    hidden = tmp_path / ".git"
    hidden.mkdir()
    (hidden / "secret.md").write_text("不要读到。", encoding="utf-8")
    outside = tmp_path.parent / "kb-outside.md"
    outside.write_text("外面的笔记。", encoding="utf-8")
    (tmp_path / "superme" / "link.md").symlink_to(outside)
    return tmp_path, outside


def _env(root):
    return {"OBSIDIAN_VAULT_PATH": str(root)}


def test_vault_searches_and_reads_inside_the_checkout(tmp_path):
    root, outside = _vault(tmp_path)
    env = _env(root)

    found = run_tool("Vault", json.dumps({"action": "search", "query": "宿主机"}), env=env)
    body = run_tool(
        "Vault",
        json.dumps({"action": "read", "path": "superme/10-技术/云计算性能排障.md"}),
        env=env,
    )
    chart = run_tool("Vault", json.dumps({"action": "map"}), env=env)
    missed = run_tool("Vault", json.dumps({"action": "search", "query": "宿主机 不存在的词"}), env=env)

    assert "superme/10-技术/云计算性能排障.md" in found
    assert "不要读到" not in found
    assert "外面的笔记" not in found
    assert "排障先看宿主机水位。" in body
    assert "[[云计算性能排障]]" in chart
    assert "没有找到相关笔记。" in missed
    outside.unlink(missing_ok=True)


def test_vault_refuses_paths_outside_the_checkout(tmp_path):
    root, outside = _vault(tmp_path)
    env = _env(root)
    for path in ("../kb-outside.md", str(outside), ".git/secret.md", "superme/link.md"):
        result = run_tool("Vault", json.dumps({"action": "read", "path": path}), env=env)
        assert result == "路径不在知识库里。"
        assert "外面的笔记" not in result
        assert "不要读到" not in result
    outside.unlink(missing_ok=True)


def test_vault_without_a_path_does_not_search():
    assert run_tool("Vault", json.dumps({"action": "map"})) == NOT_CONFIGURED


def test_kb_agent_asks_once_with_the_vault_tool():
    llm = FakeLlm("知识库里没有这篇。")
    agent = KbAgent(
        llm,
        SkillCatalog().load(KbAgent.skill_ids),
        env={"OBSIDIAN_VAULT_PATH": "/tmp/vault"},
    )

    assert agent.id == "kb"
    assert agent.remembers is False
    assert "知识库" in agent.description
    assert agent.handle("云计算怎么排障", context="上次看过日记", intent="在查笔记") == "知识库里没有这篇。"

    call = llm.calls[0]
    assert call["system"].startswith(agent.system)
    assert "superme/" in call["system"]
    assert "00-索引/MOC.md" in call["system"]
    assert "上次看过日记" in call["message"]
    assert "用户意图：在查笔记" in call["message"]
    assert call["tools"][0]["function"]["name"] == "Vault"
    assert call["env"]["OBSIDIAN_VAULT_PATH"] == "/tmp/vault"
    assert call["remember"] is False
    assert len(llm.calls) == 1


def test_kb_omits_hindsight_kwargs_when_memory_is_off():
    completions = _Completions("知识库里没有。", reject_hindsight=True)
    agent = KbAgent(LlmClient(_Client(completions), "demo-llm"), SkillCatalog().load(KbAgent.skill_ids))

    assert agent.handle("云计算怎么排障") == "知识库里没有。"
    call = completions.calls[0]
    assert "hindsight_inject_memories" not in call
    assert "hindsight_store_conversations" not in call


def test_kb_tells_hindsight_not_to_store_when_memory_is_on():
    completions = _Completions("知识库里没有。")
    agent = KbAgent(
        LlmClient(_Client(completions), "demo-llm", memory_configured=True),
        SkillCatalog().load(KbAgent.skill_ids),
    )

    assert agent.handle("云计算怎么排障") == "知识库里没有。"
    call = completions.calls[0]
    assert call["hindsight_inject_memories"] is False
    assert call["hindsight_store_conversations"] is False


def test_laya_chooses_kb_and_the_turn_is_not_stored():
    model = FakeModel(
        [
            {
                "agent_id": {"type": "choice", "choice": "kb"},
                "intent": {"type": "choice", "choice": "查笔记"},
            }
        ]
    )
    llm = FakeLlm("知识库里没有。")
    memory = FakeMemory(memories=["不该召回的记忆"])
    agent = KbAgent(llm, SkillCatalog().load(KbAgent.skill_ids))
    registry = Registry([ChatAgent(FakeLlm()), agent])
    result = Loop(
        registry=registry,
        router=Router(model, registry, selectable=["chat", "kb"]),
        model=model,
        memory=memory,
    ).handle("云计算怎么排障")

    assert result.text.startswith("知识库里没有。\n\n选用 kb。")
    assert result.saved is False
    assert result.note == "知识库只检索，这一轮不写入记忆。"
    assert memory.attempts == 0
    assert memory.queries == []
    assert "- kb：" in model.calls[0]["state"]
    assert "不该召回的记忆" not in llm.calls[0]["message"]
    assert "superme/" in llm.calls[0]["system"]
