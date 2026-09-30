from tests.fakes import FakeLlm
from xiaoluozi.agents.chat import ChatAgent
from xiaoluozi.skills import SkillCatalog


def _write(root, directory, name, description, body, *, extra=None):
    folder = root / directory
    folder.mkdir(parents=True)
    folder.joinpath("SKILL.md").write_text(
        f"---\nname: {name}\ndescription: {description}\n---\n\n{body}\n",
        encoding="utf-8",
    )
    if extra:
        for relative, text in extra.items():
            path = folder / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(text, encoding="utf-8")


class _Prepared(ChatAgent):
    skill_ids = ("bring-umbrella", "pack-list")


def test_named_skills_append_their_bodies_in_order(tmp_path):
    root = tmp_path / "skills"
    _write(root, "bring-umbrella", "bring-umbrella", "出门时提醒看天气。", "先看降雨。")
    _write(
        root,
        "pack-list",
        "pack-list",
        "出门前列要带的东西。",
        "只列三件。",
        extra={"references/LIST.md": "雨伞、外套、水杯。"},
    )
    catalog = SkillCatalog(root)
    llm = FakeLlm("带伞。")
    agent = _Prepared(llm, catalog.load(_Prepared.skill_ids))
    assert agent.handle("今天出门吗", context="上次说要出门", intent="在提问") == "带伞。"

    system = llm.calls[0]["system"]
    assert system == f"{ChatAgent.system}\n\n先看降雨。\n\n只列三件。"
    assert "出门时提醒看天气。" not in system
    assert "雨伞、外套、水杯。" not in system
    assert "上次说要出门" in llm.calls[0]["message"]
    assert "用户意图：在提问" in llm.calls[0]["message"]
    assert len(llm.calls) == 1


def test_agent_without_named_skills_keeps_its_system_prompt():
    llm = FakeLlm("在的。")
    agent = ChatAgent(llm)
    agent.handle("在吗")
    assert llm.calls[0]["system"] == ChatAgent.system


def test_missing_skill_is_refused(tmp_path):
    catalog = SkillCatalog(tmp_path)
    try:
        catalog.load(("missing",))
    except ValueError as exc:
        assert str(exc) == "未知 skill missing。"
    else:
        raise AssertionError("unknown skill must be refused")


def test_empty_body_is_refused(tmp_path):
    _write(tmp_path, "bring-umbrella", "bring-umbrella", "出门时提醒看天气。", "   ")
    catalog = SkillCatalog(tmp_path)
    try:
        catalog.load(("bring-umbrella",))
    except ValueError as exc:
        assert str(exc) == "skill bring-umbrella 的说明是空的。"
    else:
        raise AssertionError("empty skill body must be refused")


def test_directory_name_must_match_skill_name(tmp_path):
    _write(tmp_path, "weather", "umbrella", "出门时提醒看天气。", "先看降雨。")
    try:
        SkillCatalog(tmp_path)
    except ValueError as exc:
        assert str(exc) == "skill 目录名 weather 和 name umbrella 不一致。"
    else:
        raise AssertionError("mismatched skill name must be refused")


def test_skill_without_frontmatter_is_refused(tmp_path):
    folder = tmp_path / "bring-umbrella"
    folder.mkdir()
    folder.joinpath("SKILL.md").write_text("先看降雨。\n", encoding="utf-8")
    try:
        SkillCatalog(tmp_path)
    except ValueError as exc:
        assert str(exc) == "skill bring-umbrella 的 SKILL.md 没有 frontmatter。"
    else:
        raise AssertionError("skill without frontmatter must be refused")


def test_folded_description_stays_metadata(tmp_path):
    folder = tmp_path / "bring-umbrella"
    folder.mkdir()
    folder.joinpath("SKILL.md").write_text(
        "---\nname: bring-umbrella\ndescription: >\n  出门时提醒看天气。\n  提到下雨也用。\n---\n\n先看降雨。\n",
        encoding="utf-8",
    )
    skill = SkillCatalog(tmp_path).load(("bring-umbrella",))[0]
    assert skill.description == "出门时提醒看天气。 提到下雨也用。"
    assert skill.body == "先看降雨。"


def test_illegal_name_is_refused(tmp_path):
    _write(tmp_path, "Bring-Umbrella", "Bring-Umbrella", "出门时提醒看天气。", "先看降雨。")
    try:
        SkillCatalog(tmp_path)
    except ValueError as exc:
        assert str(exc) == "skill Bring-Umbrella 的 name 不合法。"
    else:
        raise AssertionError("illegal skill name must be refused")


def test_missing_description_is_refused(tmp_path):
    folder = tmp_path / "bring-umbrella"
    folder.mkdir()
    folder.joinpath("SKILL.md").write_text("---\nname: bring-umbrella\n---\n\n先看降雨。\n", encoding="utf-8")
    try:
        SkillCatalog(tmp_path)
    except ValueError as exc:
        assert str(exc) == "skill bring-umbrella 缺少 description。"
    else:
        raise AssertionError("skill without description must be refused")


def test_agent_refuses_to_start_without_its_named_skills():
    try:
        _Prepared(object())
    except ValueError as exc:
        assert str(exc) == "技能没有按声明加载：需要 bring-umbrella、pack-list，得到（无）。"
    else:
        raise AssertionError("named skills must be loaded before the agent starts")
