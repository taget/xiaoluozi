from xiaoluozi.errors import ModelNotConfigured, ReplyError
from xiaoluozi.loop import Reply

_loop = None
_model_configured = False


def install(loop, *, model_configured: bool) -> None:
    global _loop, _model_configured
    _loop = loop
    _model_configured = model_configured


def handle(message: str) -> Reply:
    """Entry the workbench and future adapters call. Returns the reply for this turn."""
    if not _model_configured or _loop is None:
        raise ModelNotConfigured("模型还没配好。设置 TYPESAFE_API_KEY 后再试。")
    text = (message or "").strip()
    if not text:
        raise ReplyError("先写一句话。")
    return _loop.handle(text)
