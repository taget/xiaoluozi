import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, StreamingResponse
from pydantic import BaseModel

from xiaoluozi.channels.weixin import WeixinApi, WeixinChannel, sync_path
from xiaoluozi.config import Settings, env_path
from xiaoluozi.entry import handle, install, stream_handle
from xiaoluozi.loop import Reply, Trace
from xiaoluozi.open_apps import find_open_app, launch_app, load_open_apps
from xiaoluozi.errors import ModelError, ModelNotConfigured, ReplyError
from xiaoluozi.history import History, history_path
from xiaoluozi.log import get_logger, silence_history_access_log
from xiaoluozi.wiring import build_loop

logger = get_logger("xiaoluozi.app")
silence_history_access_log()

_PAGE = Path(__file__).with_name("page.html").read_text(encoding="utf-8")
_FAVICON = Path(__file__).with_name("favicon.ico")


class MessageIn(BaseModel):
    message: str = ""
    conversation: str = ""
    mode: str = ""


class OpenIn(BaseModel):
    id: str = ""


def create_app(
    loop=None,
    *,
    model_configured: bool | None = None,
    history: History | None = None,
    weixin: WeixinChannel | None = None,
) -> FastAPI:
    settings = None
    if loop is None:
        settings = Settings.load()
        root = env_path().parent
        history = history or History(history_path(root))
        loop = build_loop(settings, history=history)
        if model_configured is None:
            model_configured = settings.model_configured
        if weixin is None and settings.weixin_configured:
            weixin = WeixinChannel(
                WeixinApi(settings.weixin_base_url, settings.weixin_token),
                handle,
                sync_path(root, settings.weixin_account_id),
            )
    elif history is None:
        history = getattr(loop, "history", None) or History(None)
    if model_configured is None:
        model_configured = True

    install(loop, model_configured=model_configured)

    @asynccontextmanager
    async def lifespan(_app: FastAPI):
        stop = threading.Event()
        thread = None
        channel = _app.state.weixin
        if channel is not None:
            thread = threading.Thread(target=channel.run, args=(stop,), name="weixin", daemon=True)
            thread.start()
        try:
            yield
        finally:
            stop.set()
            if thread is not None:
                thread.join(timeout=1)

    app = FastAPI(
        title="小落子",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )
    app.state.loop = loop
    app.state.history = history
    app.state.model_configured = model_configured
    app.state.weixin = weixin
    app.state.weixin_configured = weixin is not None

    @app.get("/", response_class=HTMLResponse)
    def index():
        logger.info("请求 GET /")
        return HTMLResponse(_PAGE, headers={"Cache-Control": "no-store"})

    @app.get("/favicon.ico", include_in_schema=False)
    def favicon():
        return FileResponse(_FAVICON, media_type="image/x-icon")

    @app.get("/api/status")
    def status():
        payload = {
            "model_configured": app.state.model_configured,
            "weixin_configured": app.state.weixin_configured,
        }
        logger.info("请求 GET /api/status\n%s", json.dumps(payload, ensure_ascii=False))
        return payload

    @app.get("/api/agents")
    def agents_view():
        router = getattr(app.state.loop, "router", None)
        enabled = router.enabled() if router is not None and hasattr(router, "enabled") else []
        default_id = getattr(router, "_default_agent", "") if router is not None else ""
        registry = getattr(app.state.loop, "registry", None)
        payload = {
            "agents": [
                _agent_card(agent_id, description, default_id, registry) for agent_id, description in enabled
            ]
        }
        logger.info("请求 GET /api/agents %s", "、".join(item["id"] for item in payload["agents"]) or "没有")
        return payload

    @app.get("/api/history")
    def history_view():
        payload = {"turns": [_turn_payload(turn) for turn in app.state.history.turns()]}
        logger.debug("请求 GET /api/history %s 条", len(payload["turns"]))
        return payload

    @app.post("/api/handle")
    def post_handle(body: MessageIn):
        logger.info("请求 POST /api/handle %s", body.message)
        install(app.state.loop, model_configured=app.state.model_configured)
        try:
            reply = handle(body.message, conversation=body.conversation, mode=body.mode)
        except ModelNotConfigured as exc:
            return _error(503, str(exc))
        except ModelError as exc:
            return _error(502, str(exc))
        except ReplyError as exc:
            code = 400 if str(exc) == "先写一句话。" else 502
            return _error(code, str(exc))
        payload = {"reply": reply.text, "saved": reply.saved, "note": reply.note}
        logger.info("响应 200 POST /api/handle\n%s", json.dumps(payload, ensure_ascii=False))
        return payload

    @app.post("/api/handle/stream")
    def post_stream(body: MessageIn):
        logger.info("请求 POST /api/handle/stream %s", body.message)
        install(app.state.loop, model_configured=app.state.model_configured)
        return StreamingResponse(
            _stream_lines(body.message, body.conversation, body.mode),
            media_type="application/x-ndjson",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    @app.post("/api/open")
    def post_open(body: OpenIn):
        try:
            apps = load_open_apps()
        except ValueError as exc:
            return _error(500, str(exc))
        app_entry = find_open_app(body.id, apps)
        if app_entry is None:
            return _error(404, "不能打开这个应用。")
        if app_entry.url:
            return {"url": app_entry.url}
        try:
            launch_app(app_entry)
        except OSError:
            return _error(502, "没有打开。")
        logger.info("打开应用 %s", app_entry.id)
        return {"opened": True}

    return app


def _agent_card(agent_id: str, description: str, default_id: str, registry) -> dict:
    agent = None
    if registry is not None and hasattr(registry, "get") and agent_id in getattr(registry, "ids", lambda: ())():
        agent = registry.get(agent_id)
    return {
        "id": agent_id,
        "description": getattr(agent, "description", description) if agent is not None else description,
        "default": agent_id == default_id,
        "skills": _skill_names(agent),
        "services": _service_names(agent),
    }


def _skill_names(agent) -> list[str]:
    if agent is None:
        return []
    loaded = getattr(agent, "_skills", None) or ()
    names = [getattr(skill, "name", "") for skill in loaded]
    names = [name for name in names if name]
    if names:
        return names
    return [name for name in getattr(agent, "skill_ids", ()) if name]


def _service_names(agent) -> list[str]:
    if agent is None:
        return []
    names: list[str] = []
    loaded = getattr(agent, "_connectors", None) or ()
    if loaded:
        for connector in loaded:
            _append_name(names, getattr(connector, "id", ""))
    else:
        for name in getattr(agent, "connector_ids", ()):
            _append_name(names, name)
    for name in getattr(agent, "service_ids", ()):
        _append_name(names, name)
    return names


def _append_name(names: list[str], name: str) -> None:
    text = (name or "").strip()
    if text and text not in names:
        names.append(text)


def _turn_payload(turn) -> dict:
    return {
        "id": turn.turn_id,
        "channel": turn.channel,
        "user": turn.user_message,
        "reply": turn.shown,
        "note": turn.note,
    }


def _stream_lines(message: str, conversation: str = "", mode: str = ""):
    try:
        for item in stream_handle(message, conversation=conversation, mode=mode):
            if isinstance(item, Reply):
                payload = {"reply": item.text, "saved": item.saved, "note": item.note}
                logger.info(
                    "响应 200 POST /api/handle/stream\n%s",
                    json.dumps(payload, ensure_ascii=False),
                )
                yield _ndjson(payload)
            elif isinstance(item, Trace):
                yield _ndjson({"trace": {"title": item.title, "lines": list(item.lines)}})
            else:
                yield _ndjson({"delta": item})
    except ModelNotConfigured as exc:
        yield _ndjson(_stream_error(503, str(exc)))
    except ModelError as exc:
        yield _ndjson(_stream_error(502, str(exc)))
    except ReplyError as exc:
        code = 400 if str(exc) == "先写一句话。" else 502
        yield _ndjson(_stream_error(code, str(exc)))
    except Exception as exc:
        logger.info("流式回复失败 %s", exc)
        yield _ndjson(_stream_error(500, "没能回复。"))


def _ndjson(payload: dict) -> str:
    return json.dumps(payload, ensure_ascii=False) + "\n"


def _stream_error(status_code: int, message: str) -> dict:
    payload = {"error": message}
    logger.info(
        "响应 %s POST /api/handle/stream\n%s",
        status_code,
        json.dumps(payload, ensure_ascii=False),
    )
    return payload


def _error(status_code: int, message: str) -> JSONResponse:
    payload = {"error": message}
    logger.info("响应 %s POST /api/handle\n%s", status_code, json.dumps(payload, ensure_ascii=False))
    return JSONResponse(status_code=status_code, content=payload)


app = create_app()
