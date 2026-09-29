from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse, JSONResponse
from pydantic import BaseModel

from xiaoluozi.config import Settings
from xiaoluozi.entry import handle, install
from xiaoluozi.errors import ModelError, ModelNotConfigured, ReplyError
from xiaoluozi.wiring import build_loop

_PAGE = Path(__file__).with_name("page.html").read_text(encoding="utf-8")


class MessageIn(BaseModel):
    message: str = ""


def create_app(loop=None, *, model_configured: bool | None = None) -> FastAPI:
    if loop is None:
        settings = Settings.from_env()
        loop = build_loop(settings)
        if model_configured is None:
            model_configured = settings.model_configured
    if model_configured is None:
        model_configured = True

    install(loop, model_configured=model_configured)
    app = FastAPI(title="小落子", docs_url=None, redoc_url=None, openapi_url=None)
    app.state.loop = loop
    app.state.model_configured = model_configured

    @app.get("/", response_class=HTMLResponse)
    def index():
        return HTMLResponse(_PAGE)

    @app.get("/api/status")
    def status():
        return {"model_configured": app.state.model_configured}

    @app.post("/api/handle")
    def post_handle(body: MessageIn):
        install(app.state.loop, model_configured=app.state.model_configured)
        try:
            reply = handle(body.message)
        except ModelNotConfigured as exc:
            return JSONResponse(status_code=503, content={"error": str(exc)})
        except ModelError as exc:
            return JSONResponse(status_code=502, content={"error": str(exc)})
        except ReplyError as exc:
            code = 400 if str(exc) == "先写一句话。" else 502
            return JSONResponse(status_code=code, content={"error": str(exc)})
        return {"reply": reply.text, "saved": reply.saved, "note": reply.note}

    return app


app = create_app()
