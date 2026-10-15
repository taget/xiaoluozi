import inspect
import json
import re
import threading
import time
import uuid
from dataclasses import dataclass

from xiaoluozi.agents.request import agent_request
from xiaoluozi.errors import ModelNotConfigured, ReplyError
from xiaoluozi.log import get_logger
from xiaoluozi.memory import TurnRecord
from xiaoluozi.router import INTENT_UNKNOWN, RoutingDecision
from xiaoluozi.skills import system_with_skills
from xiaoluozi.tools import DELEGATE_SPEC, tool_specs

logger = get_logger("xiaoluozi.loop")

UNSAVED_NOTE = "这一轮没有存进记忆。"
DEFAULT_DECISION_LIMIT = 10
AGENT_TIMEOUT = 60
ROUND_TIMEOUT = 70
TEAM_DELEGATE_LIMIT = 4
_CONVERSATION = re.compile(r"[^A-Za-z0-9_.:-]")
_ACKS = {
    "好的",
    "好",
    "是的",
    "是",
    "对",
    "对的",
    "确认",
    "嗯",
    "嗯嗯",
    "行",
    "可以",
    "ok",
    "okay",
    "收到",
    "明白",
    "知道了",
    "没问题",
}


@dataclass(frozen=True)
class Reply:
    """What handle returns. text is the only sentence the page shows as the answer."""

    text: str
    saved: bool
    note: str | None = None


@dataclass(frozen=True)
class Trace:
    """A short step for the web page. WeChat's handle() ignores these."""

    title: str
    lines: tuple[str, ...]


@dataclass(frozen=True)
class DecisionBasis:
    """Latest user input handed to laya. It is not an agent's memory."""

    message: str


@dataclass(frozen=True)
class AgentPiece:
    """One agent's finished text in this turn. error is empty when it completed."""

    agent_id: str
    text: str
    error: str = ""


@dataclass(frozen=True)
class QueuedDecision:
    """One routing result kept on that agent's queue until the queue is full."""

    message: str
    agent_id: str
    reason: str
    intent: str
    conversation_id: str = "default"


class Loop:
    """Sole orchestrator: recall, laya decides agent and intent, the agent calls the LLM, then retain."""

    def __init__(
        self,
        registry,
        router,
        model,
        memory,
        *,
        model_configured: bool = True,
        history=None,
        decision_limit: int = DEFAULT_DECISION_LIMIT,
        agent_timeout: float = AGENT_TIMEOUT,
        round_timeout: float = ROUND_TIMEOUT,
    ):
        if decision_limit < 1:
            raise ValueError("决策队列长度至少是 1。")
        self.registry = registry
        self.router = router
        self.model = model
        self.memory = memory
        self.model_configured = model_configured
        self.history = history
        self.decision_limit = decision_limit
        self.agent_timeout = agent_timeout
        self.round_timeout = round_timeout
        self._decisions: dict[str, list[QueuedDecision]] = {}
        self._recent: list[QueuedDecision] = []
        self._lock = threading.RLock()

    def handle(self, message: str, *, channel: str = "web", conversation: str = "", mode: str = "") -> Reply:
        with self._lock:
            return self._collect(self._generate(message, channel, conversation, mode))

    def stream(self, message: str, *, channel: str = "web", conversation: str = "", mode: str = ""):
        """Yield model text as it arrives, then the finished Reply. WeChat keeps using handle."""
        with self._lock:
            yield from self._generate(message, channel, conversation, mode)

    def _collect(self, events) -> Reply:
        reply = None
        for item in events:
            if isinstance(item, Reply):
                reply = item
        if reply is None:
            raise ReplyError("模型没有返回内容。")
        return reply

    def _generate(self, message: str, channel: str, conversation: str = "", mode: str = ""):
        text = message.strip()
        conversation_id = _conversation_key(conversation)
        team = (mode or "").strip() == "team"
        logger.info("回路开始 %s", text)
        if not text:
            logger.info("回路拒绝 先写一句话。")
            raise ReplyError("先写一句话。")
        if not self.model_configured:
            logger.info("回路拒绝 模型还没配好。")
            raise ModelNotConfigured("模型还没配好。在 .env 里设置 TYPESAFE_API_KEY 后再试。")

        basis = DecisionBasis(message=text)
        logger.info("+++++ 调用 laya +++++")
        logger.info("决策依赖\n%s", basis.message)
        logger.info("------------- 以下为模型调用 -----------")
        failed = False
        try:
            decision = self._route(basis.message, conversation_id, team=team)
        except Exception as exc:
            latest = self._latest_decision(conversation_id)
            if latest is None:
                detail = str(exc).strip() or "模型调用失败。"
                logger.info("回路拒绝 %s", detail)
                raise
            decision = RoutingDecision(latest.agent_id, latest.reason, latest.intent)
            failed = True
            logger.info("决策失败，沿用这个会话的最新一条 agent_id=%s，不入队。", decision.agent_id)
        else:
            if team:
                decision.consultants = ()
            self._record_decision(text, decision, conversation_id)
        if team:
            decision.consultants = ()
        logger.info(">>>>>> 回路意图 %s", decision.intent)
        yield from self._trace_route(decision, failed=failed)
        self._give_fallback(decision)
        pieces = []
        parts: tuple[tuple[str, str], ...] = ()
        consulted: tuple[str, ...] = ()
        try:
            if decision.consultants:
                gathered = self._fanout(text, decision, conversation_id)
                yield Trace(
                    "顾问",
                    tuple(
                        f"{item.agent_id}：{'完成' if item.text else '没有完成'}"
                        for item in gathered
                        if item.agent_id != decision.agent_id
                    ),
                )
                reply = self._combine(text, gathered)
                parts = tuple((item.agent_id, item.text) for item in gathered if item.text and not item.error)
                if reply:
                    pieces.append(reply)
                    yield reply
            elif team:
                reply, parts, consulted = yield from self._team(text, decision, conversation_id)
                if reply:
                    pieces.append(reply)
                    yield reply
            else:
                context = self._revise_context(text, self._context(text, decision.agent_id, conversation_id))
                logger.info("上下文记忆 agent_id=%s\n%s", decision.agent_id, context.strip() or "没有可用的上下文。")
                yield Trace("代理入参", _agent_in(decision, text, context))
                for piece in self._agent_text(decision.agent_id, text, context, decision.intent, conversation_id):
                    if not isinstance(piece, str) or not piece:
                        continue
                    pieces.append(piece)
                    yield piece
        except Exception as exc:
            detail = str(exc).strip() or "模型调用失败。"
            logger.info("回路拒绝 %s", detail)
            raise ReplyError(detail) from exc
        reply = "".join(pieces).strip()
        if not reply:
            logger.info("回路拒绝 模型没有返回内容。")
            raise ReplyError("模型没有返回内容。")
        yield Trace("代理出参", (f"共 {len(reply)} 字。{_brief(reply, 80)}",))
        shown = _shown(reply, decision, consulted)
        logger.info("回路回复 agent_id=%s %s", decision.agent_id, shown)

        turn = TurnRecord(
            turn_id=uuid.uuid4().hex,
            user_message=text,
            agent_id=decision.agent_id,
            reason=decision.reason,
            reply=reply,
            cognition=decision.intent,
            channel=channel,
        )
        if not self._remembers(decision.agent_id):
            note = self._memory_note(decision.agent_id)
            logger.info("回路不写入记忆 agent_id=%s", decision.agent_id)
            self._remember(turn, shown, note, conversation_id, parts)
            yield Reply(text=shown, saved=False, note=note)
            return
        try:
            self.memory.retain_turn(turn)
        except Exception as exc:
            logger.info("回路写入 turn_id=%s saved=false %s", turn.turn_id, exc)
            self._remember(turn, shown, UNSAVED_NOTE, conversation_id, parts)
            yield Reply(text=shown, saved=False, note=UNSAVED_NOTE)
            return
        logger.info("回路写入 turn_id=%s saved=true", turn.turn_id)
        self._remember(turn, shown, None, conversation_id, parts)
        yield Reply(text=shown, saved=True, note=None)

    def _agent_text(self, agent_id: str, text: str, context: str, intent: str, conversation_id: str = "default"):
        agent = self.registry.get(agent_id)
        source = getattr(agent, "stream", None)
        if source is None:
            whole = _call_agent(agent, "handle", text, context, intent, conversation_id)
            if isinstance(whole, str) and whole:
                yield whole
            return
        yielded = _call_agent(agent, "stream", text, context, intent, conversation_id)
        yield from yielded

    def _fanout(self, text: str, decision, conversation_id: str) -> list[AgentPiece]:
        ids = [decision.agent_id, *decision.consultants]
        stop = threading.Event()
        results: dict[str, AgentPiece] = {}
        lock = threading.Lock()

        def run(agent_id: str) -> None:
            piece = self._one_agent(agent_id, text, decision.intent, conversation_id, stop)
            with lock:
                if agent_id not in results:
                    results[agent_id] = piece

        threads = []
        for agent_id in ids:
            thread = threading.Thread(
                target=run,
                args=(agent_id,),
                name=f"xiaoluozi-agent-{agent_id}",
                daemon=True,
            )
            thread.start()
            threads.append((agent_id, thread))
        deadline = time.monotonic() + self.round_timeout
        for _agent_id, thread in threads:
            remaining = deadline - time.monotonic()
            thread.join(max(0.0, remaining))
        stop.set()
        for _agent_id, thread in threads:
            thread.join(0.2)
        for agent_id, _thread in threads:
            with lock:
                if agent_id not in results:
                    logger.info("这一轮超时，代理未完成 agent_id=%s", agent_id)
                    results[agent_id] = AgentPiece(agent_id, "", "超时")
        return [results[agent_id] for agent_id in ids]

    def _one_agent(
        self,
        agent_id: str,
        text: str,
        intent: str,
        conversation_id: str,
        stop: threading.Event | None = None,
        *,
        prompt: str | None = None,
        timeout: float | None = None,
    ) -> AgentPiece:
        context = self._revise_context(text, self._context(text, agent_id, conversation_id))
        logger.info("上下文记忆 agent_id=%s\n%s", agent_id, context.strip() or "没有可用的上下文。")
        limit = self.agent_timeout if timeout is None else timeout
        deadline = time.monotonic() + limit
        pieces = []
        timed_out = False
        outgoing = text if prompt is None else prompt
        generator = self._agent_text(agent_id, outgoing, context, intent, conversation_id)
        try:
            for piece in generator:
                if (stop is not None and stop.is_set()) or time.monotonic() > deadline:
                    timed_out = True
                    logger.info("代理超时 agent_id=%s", agent_id)
                    break
                if isinstance(piece, str) and piece:
                    pieces.append(piece)
        except Exception as exc:
            detail = str(exc).strip() or "模型调用失败。"
            logger.info("顾问没有完成 agent_id=%s %s", agent_id, detail)
            return AgentPiece(agent_id, "", detail)
        finally:
            if timed_out:
                closer = getattr(generator, "close", None)
                if closer is not None:
                    try:
                        closer()
                    except Exception:
                        logger.info("代理超时后没有停住 agent_id=%s", agent_id)
        if timed_out:
            return AgentPiece(agent_id, "", "超时")
        return AgentPiece(agent_id, "".join(pieces).strip(), "")

    def _team(self, text: str, decision, conversation_id: str):
        agent = self.registry.get(decision.agent_id)
        names = self._delegates_for(decision.agent_id)
        system = self._team_system(agent, names)
        context = self._revise_context(text, self._context(text, decision.agent_id, conversation_id))
        logger.info("上下文记忆 agent_id=%s\n%s", decision.agent_id, context.strip() or "没有可用的上下文。")
        request = agent_request(text, context, decision.intent, getattr(agent, "roster_note", "") or "")
        round_deadline = time.monotonic() + self.round_timeout
        used: list[str] = []
        parts_map: dict[str, str] = {}
        order: list[str] = []
        events: list[str] = []
        stop = threading.Event()

        def delegate(arguments: str) -> str:
            if time.monotonic() > round_deadline:
                stop.set()
                return "这一轮已经超时。"
            agent_id, result, ok = self._delegate_once(
                arguments,
                user_text=text,
                conversation_id=conversation_id,
                primary_id=decision.agent_id,
                stop=stop,
                used=used,
                timeout=min(self.agent_timeout, max(0.0, round_deadline - time.monotonic())),
            )
            if agent_id:
                events.append(f"{agent_id}：{'完成' if ok else '没有完成'}")
                if ok and result:
                    if agent_id not in parts_map:
                        order.append(agent_id)
                    parts_map[agent_id] = result
            return result

        answer = self._lead_answer(agent, system, request, delegate, text)
        if events:
            yield Trace("委派", tuple(events))
        final = (answer or "").strip()
        parts = tuple((agent_id, parts_map[agent_id]) for agent_id in order)
        if final:
            parts = parts + ((decision.agent_id, final),)
        return final, parts, tuple(order)

    def _delegates_for(self, primary_id: str) -> list[str]:
        names = []
        for agent_id in sorted(self.registry.ids()):
            if agent_id == primary_id:
                continue
            agent = self.registry.get(agent_id)
            if getattr(agent, "consultable", False) and not getattr(agent, "exclusive", False):
                names.append(agent_id)
        return names

    def _team_system(self, agent, names: list[str]) -> str:
        system = system_with_skills(getattr(agent, "system", "") or "", getattr(agent, "_skills", ()))
        note = (getattr(agent, "routing_note", "") or "").strip()
        if note:
            system = f"{system}\n\n{note}"
        if names:
            extra = (
                "你是这一轮的主代理。可以调用 Delegate 请只读代理核对子任务。"
                "每次要写清目标代理、子任务和要核对的假设。"
                "拿到结果后先判断是否相关、假设是否成立、还缺什么，再决定继续调用或给出最终答复。"
                "不要在正文里假装已经调用了别人。"
                "不能调用会发消息或改数据的代理；需要时只建议用户改选。"
                "子代理不能再调度别人。"
                f"可调用：{'、'.join(names)}。"
            )
        else:
            extra = "你是这一轮的主代理。这一轮没有可以自动调用的只读代理。直接回答，不要编造别人的结论。"
        return f"{system}\n\n{extra}"

    def _lead_answer(self, agent, system: str, request: str, delegate, recall_query: str) -> str:
        llm = getattr(agent, "_llm", None)
        answer = getattr(llm, "answer", None)
        if not callable(answer):
            raise ReplyError("模型没有返回内容。")
        tools = [*tool_specs(getattr(agent, "_skills", ())), DELEGATE_SPEC]
        kwargs = {
            "tools": tools,
            "env": dict(getattr(agent, "_env", {}) or {}),
            "remember": bool(getattr(agent, "remembers", True)),
            "recall_query": recall_query,
        }
        try:
            parameters = inspect.signature(answer).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "delegate" in parameters or any(
            item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()
        ):
            kwargs["delegate"] = delegate
        return answer(system, request, **kwargs)

    def _delegate_once(
        self,
        arguments: str,
        *,
        user_text: str,
        conversation_id: str,
        primary_id: str,
        stop: threading.Event,
        used: list[str],
        timeout: float,
    ) -> tuple[str, str, bool]:
        try:
            payload = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return "", "参数不是 JSON。", False
        if not isinstance(payload, dict):
            return "", "参数不是 JSON。", False
        agent_id = str(payload.get("agent") or "").strip()
        task = str(payload.get("task") or "").strip()
        hypothesis = str(payload.get("hypothesis") or "").strip()
        evidence = str(payload.get("evidence") or "").strip()
        if not agent_id or not task or not hypothesis:
            return agent_id, "要写目标代理、子任务和要核对的假设。", False
        if len(used) >= TEAM_DELEGATE_LIMIT:
            return agent_id, "这一轮的委派已经用完。", False
        if agent_id == primary_id:
            return agent_id, "主代理不能委派给自己。", False
        if agent_id not in self.registry.ids():
            return agent_id, f"没有这个代理：{agent_id}。", False
        target = self.registry.get(agent_id)
        if not getattr(target, "consultable", False) or getattr(target, "exclusive", False):
            return agent_id, f"{agent_id} 会发消息或改数据，不能自动调用。需要的话请改选它。", False
        if stop.is_set() or timeout <= 0:
            return agent_id, "这一轮已经超时。", False
        used.append(agent_id)
        prompt = (
            f"用户问题：{user_text}\n"
            f"子任务：{task}\n"
            f"要核对的假设：{hypothesis}\n"
            f"已有证据：{evidence or '没有。'}\n"
            "只完成这个子任务。不要调度其他代理，不要改配置，也不要发消息。"
        )
        piece = self._one_agent(
            agent_id,
            user_text,
            hypothesis,
            conversation_id,
            stop,
            prompt=prompt,
            timeout=timeout,
        )
        if piece.error or not piece.text.strip():
            detail = piece.error or "没有完成"
            return agent_id, f"{agent_id} 没有完成。{detail}", False
        return agent_id, piece.text.strip(), True

    def _combine(self, text: str, gathered: list[AgentPiece]) -> str:
        usable = [item for item in gathered if item.text.strip()]
        if not usable:
            raise ReplyError("模型没有返回内容。")
        if len(usable) == 1:
            return usable[0].text
        return self._synthesize(text, usable, [item.agent_id for item in gathered if not item.text.strip()])

    def _synthesize(self, text: str, usable: list[AgentPiece], missing: list[str]) -> str:
        blocks = [f"【{item.agent_id}】\n{item.text}" for item in usable]
        fallback = "\n\n".join(blocks)
        agent = self.registry.get(getattr(self.router, "_default_agent", "chat"))
        llm = getattr(agent, "_llm", None)
        answer = getattr(llm, "answer", None)
        if not callable(answer):
            return fallback
        request = f"用户问题：{text}\n\n" + "\n\n".join(blocks)
        if missing:
            request += "\n\n没有完成：" + "、".join(missing)
        try:
            combined = answer(
                "你是小落子的协调代理。下面是几个代理对同一句话的回答。"
                "合成一条中文回复：去掉重复，冲突写明谁说了什么，不要编造他们没说过的事实。"
                "不要写选用了哪个代理。",
                request,
                remember=False,
                recall_query=text,
            )
        except Exception as exc:
            logger.info("协调失败 %s", exc.__class__.__name__)
            return fallback
        cleaned = (combined or "").strip()
        return cleaned or fallback

    def _give_fallback(self, decision) -> None:
        """When no specialist was found, hand laya's return to the fallback agent."""
        agent = self.registry.get(decision.agent_id)
        if not hasattr(agent, "routing_note"):
            return
        raw = (getattr(decision, "laya", "") or "").strip()
        if not raw:
            agent.routing_note = ""
            return
        agent.routing_note = (
            "这次没有找到专职代理，由你兜底。下面是 laya 的返回。\n"
            f"{raw}\n"
            "能回答的部分直接回答。做不到的说明缺什么，不要编造执行结果。"
        )

    def append_decision(self, message: str, decision, conversation_id: str = "default") -> None:
        """Put one routing decision on that agent's queue. A full queue is saved, then cleared."""
        with self._lock:
            agent_id = decision.agent_id
            queue = self._queue(agent_id)
            if len(queue) >= self.decision_limit:
                self._refresh_decisions(agent_id)
            queue = self._queue(agent_id)
            if len(queue) >= self.decision_limit:
                logger.info("决策队列已满 agent_id=%s，这一条没有进入队列。", agent_id)
                return
            item = QueuedDecision(
                message=message,
                agent_id=agent_id,
                reason=decision.reason,
                intent=decision.intent,
                conversation_id=conversation_id or "default",
            )
            queue.append(item)
            self._recent.append(item)
            logger.info(
                "决策进入队列 %s/%s agent_id=%s",
                len(queue),
                self.decision_limit,
                agent_id,
            )
            if len(queue) >= self.decision_limit:
                self._refresh_decisions(agent_id)

    def _record_decision(self, message: str, decision, conversation_id: str = "default") -> None:
        latest = self._latest_decision(conversation_id)
        if latest is not None and _same_decision(decision, latest):
            logger.info("决策与最新一条一致 agent_id=%s，不入队。", decision.agent_id)
            return
        self.append_decision(message, decision, conversation_id)

    def _latest_decision(self, conversation_id: str | None = None) -> QueuedDecision | None:
        if not self._recent:
            return None
        if conversation_id is None:
            return self._recent[-1]
        for item in reversed(self._recent):
            if item.conversation_id == conversation_id:
                return item
        return None

    def decision_at(self, agent_id: str, index: int) -> QueuedDecision:
        """Return one agent's decision at this position. The first one is 0."""
        with self._lock:
            try:
                return self._decisions.get(agent_id, [])[index]
            except IndexError as exc:
                raise IndexError(f"决策队列 {agent_id} 没有第 {index} 条。") from exc

    def refresh_decisions(self, agent_id: str) -> bool:
        """Save this agent's queue once it is full, then clear it. A short queue stays."""
        with self._lock:
            return self._refresh_decisions(agent_id)

    def _queue(self, agent_id: str) -> list[QueuedDecision]:
        return self._decisions.setdefault(agent_id, [])

    def _refresh_decisions(self, agent_id: str) -> bool:
        queue = self._decisions.get(agent_id, [])
        if len(queue) < self.decision_limit:
            logger.info(
                "决策队列未满 agent_id=%s %s/%s，不写入记忆。",
                agent_id,
                len(queue),
                self.decision_limit,
            )
            return False
        pending = list(queue)
        save = getattr(self.memory, "retain_decisions", None)
        if save is None:
            logger.info("决策队列没有记忆端口 agent_id=%s，未写入。", agent_id)
            return False
        try:
            save(pending)
        except Exception as exc:
            logger.info("决策队列写入失败 agent_id=%s %s", agent_id, exc)
            return False
        self._decisions[agent_id] = []
        self._recent = [item for item in self._recent if item.agent_id != agent_id]
        logger.info("决策队列已写入记忆 agent_id=%s %s 条", agent_id, len(pending))
        return True

    def _remember(
        self,
        turn: TurnRecord,
        shown: str,
        note: str | None,
        conversation_id: str = "default",
        parts: tuple[tuple[str, str], ...] = (),
    ) -> None:
        if self.history is None:
            return
        try:
            self.history.append(
                channel=turn.channel,
                agent_id=turn.agent_id,
                user_message=turn.user_message,
                reply=turn.reply,
                shown=shown,
                note=note,
                turn_id=turn.turn_id,
                conversation_id=conversation_id,
                parts=parts,
            )
        except Exception as exc:
            logger.info("回路历史没有写入 %s", exc)

    def _route(self, text: str, conversation_id: str = "default", *, team: bool = False) -> RoutingDecision:
        self._laya_call = None
        previous = self._previous_agent(conversation_id)
        if _is_ack(text) and previous:
            reason = f"这句话没有新的业务内容，沿用上次的 {previous}。"
            logger.info("回路沿用 agent_id=%s %s", previous, reason)
            return RoutingDecision(previous, reason, INTENT_UNKNOWN)
        route = self.router.route
        try:
            parameters = inspect.signature(route).parameters
        except (TypeError, ValueError):
            parameters = {}
        if "team" in parameters or any(item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()):
            decision = route(text, team=team)
        else:
            decision = route(text)
        self._laya_call = getattr(self.router, "last_call", None)
        return decision

    def _trace_route(self, decision, *, failed: bool):
        call = getattr(self, "_laya_call", None)
        if failed:
            yield Trace("laya", ("调用失败，沿用上一条决定。",))
        elif not call:
            lines = ["这一轮没有再问 laya。"]
            if decision.reason:
                lines.append(_brief(decision.reason, 96))
            yield Trace("laya", tuple(lines))
        else:
            yield Trace("laya 入参", _laya_in(call))
            yield Trace("laya 返回", _laya_out(call.get("answers")))
        yield Trace(
            "选用代理",
            (
                f"代理：{decision.agent_id}",
                f"依据：{_brief(decision.reason, 96)}",
                f"意图：{_brief(decision.intent, 40)}",
            )
            + (
                (f"顾问：{'、'.join(decision.consultants)}",)
                if getattr(decision, "consultants", ())
                else ()
            ),
        )

    def _previous_agent(self, conversation_id: str = "default") -> str:
        if self.history is None:
            return ""
        last = self.history.latest(conversation_id)
        if last is None:
            return ""
        agent_id = last.agent_id.strip()
        if agent_id not in self.registry.ids():
            return ""
        return agent_id

    def _revise_context(self, message: str, context: str) -> str:
        """Reserved. Edit this agent's gathered memory before the agent sees it."""
        return context

    def _context(self, message: str, agent_id: str, conversation_id: str = "default") -> str:
        parts = []
        if self.history is not None:
            recent = self.history.context(agent_id, conversation_id).strip()
            if recent:
                parts.append(recent)
        if self._remembers(agent_id):
            recalled = self._recall(message, agent_id)
            if recalled:
                parts.append(recalled)
        else:
            logger.info("回路不召回记忆 agent_id=%s", agent_id)
        return "\n\n".join(parts)

    def _remembers(self, agent_id: str) -> bool:
        return getattr(self.registry.get(agent_id), "remembers", True)

    def _memory_note(self, agent_id: str) -> str:
        return getattr(self.registry.get(agent_id), "memory_note", None) or "这一轮不写入记忆。"

    def _recall(self, message: str, agent_id: str) -> str:
        recall = getattr(self.memory, "recall", None)
        if recall is None:
            return ""
        try:
            memories = recall(message, agent_id)
        except TypeError:
            memories = recall(message)
        except Exception as exc:
            logger.info("回路上下文失败 agent_id=%s %s", agent_id, exc)
            return ""
        if not isinstance(memories, list):
            return ""
        lines = [item.strip() for item in memories if isinstance(item, str) and item.strip()]
        return "\n".join(lines)


def _brief(text: str, limit: int = 72) -> str:
    flat = " ".join((text or "").split())
    if not flat:
        return "（空）"
    if len(flat) <= limit:
        return flat
    return flat[:limit].rstrip() + "…"


def _laya_in(call: dict) -> tuple[str, ...]:
    agents = [item for item in call.get("agents") or [] if isinstance(item, str)]
    shown = "、".join(agents[:8])
    if len(agents) > 8:
        shown += f" 等 {len(agents)} 个"
    lines = [
        f"问题：{_brief(call.get('question') or '', 72)}",
        "上下文：空",
        f"候选：{shown or '没有'}",
    ]
    named = call.get("named") or ""
    if named:
        lines.append(f"点名：{named}")
    return tuple(lines)


def _laya_out(answers) -> tuple[str, ...]:
    if not isinstance(answers, dict):
        return (f"返回：{_brief(str(answers), 96)}",)
    lines = []
    agent = answers.get("agent_id")
    intent = answers.get("intent")
    if isinstance(agent, dict):
        choice = agent.get("choice")
        if isinstance(choice, str) and choice.strip():
            lines.append(f"选择：{choice.strip()}")
        score = agent.get("confidence")
        if isinstance(score, (int, float)) and not isinstance(score, bool):
            lines.append(f"把握：{score}")
    if isinstance(intent, dict):
        choice = intent.get("choice")
        if isinstance(choice, str) and choice.strip():
            lines.append(f"意图：{choice.strip()}")
    if lines:
        return tuple(lines)
    return (f"返回：{_brief(json.dumps(answers, ensure_ascii=False), 96)}",)


def _agent_in(decision, text: str, context: str) -> tuple[str, ...]:
    body = (context or "").strip()
    if not body:
        context_line = "上下文：没有可用的上下文。"
    else:
        context_line = f"上下文：共 {len(body)} 字。{_brief(body, 48)}"
    return (
        f"代理：{decision.agent_id}",
        f"意图：{_brief(decision.intent, 40)}",
        context_line,
        f"用户的话：{_brief(text, 72)}",
    )


def _is_ack(text: str) -> bool:
    cleaned = text.strip().lower().strip("。！？!?.,，、…~～ ")
    return cleaned in _ACKS


def _conversation_key(raw: str) -> str:
    text = _CONVERSATION.sub("", (raw or "").strip())[:80]
    return text or "default"


def _shown(reply: str, decision, consulted: tuple[str, ...] = ()) -> str:
    text = f"{reply}\n\n选用 {decision.agent_id}。依据：{decision.reason}"
    names = tuple(getattr(decision, "consultants", ())) or tuple(consulted)
    if names:
        text += "\n参考了 " + "、".join(names) + "。"
    return text


def _call_agent(agent, name: str, text: str, context: str, intent: str, conversation_id: str):
    method = getattr(agent, name)
    kwargs = {"context": context, "intent": intent}
    try:
        parameters = inspect.signature(method).parameters
    except (TypeError, ValueError):
        parameters = {}
    if "conversation_id" in parameters or any(
        item.kind == inspect.Parameter.VAR_KEYWORD for item in parameters.values()
    ):
        kwargs["conversation_id"] = conversation_id
    return method(text, **kwargs)


def _same_decision(decision, latest: QueuedDecision) -> bool:
    return (
        decision.agent_id == latest.agent_id
        and decision.reason == latest.reason
        and decision.intent == latest.intent
        and tuple(getattr(decision, "consultants", ())) == tuple(getattr(latest, "consultants", ()))
    )
