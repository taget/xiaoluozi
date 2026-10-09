import json
import threading
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from xiaoluozi.channels.weixin import WeixinApi, WeixinChannel, sync_path
from xiaoluozi.config import Settings, env_path
from xiaoluozi.entry import handle, install
from xiaoluozi.errors import ModelError, ModelNotConfigured, ReplyError
from xiaoluozi.history import History, history_path
from xiaoluozi.log import get_logger, silence_history_access_log
from xiaoluozi.wiring import build_loop

logger = get_logger("xiaoluozi.app")
silence_history_access_log()

_PAGE = Path(__file__).with_name("page.html").read_text(encoding="utf-8")


class MessageIn(BaseModel):
    message: str = ""


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
        return HTMLResponse(_PAGE)

    @app.get("/api/status")
    def status():
        payload = {
            "model_configured": app.state.model_configured,
            "weixin_configured": app.state.weixin_configured,
        }
        logger.info("请求 GET /api/status\n%s", json.dumps(payload, ensure_ascii=False))
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
            reply = handle(body.message)
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

    return app


def _turn_payload(turn) -> dict:
    return {
        "id": turn.turn_id,
        "channel": turn.channel,
        "user": turn.user_message,
        "reply": turn.shown,
        "note": turn.note,
    }


def _error(status_code: int, message: str) -> JSONResponse:
    payload = {"error": message}
    logger.info("响应 %s POST /api/handle\n%s", status_code, json.dumps(payload, ensure_ascii=False))
    return JSONResponse(status_code=status_code, content=payload)


app = create_app()
