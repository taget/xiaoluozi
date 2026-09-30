from xiaoluozi.errors import ModelNotConfigured, ReplyError
from xiaoluozi.log import get_logger
from xiaoluozi.loop import Reply

logger = get_logger("xiaoluozi.entry")

_loop = None
_model_configured = False


def install(loop, *, model_configured: bool) -> None:
    global _loop, _model_configured
    _loop = loop
    _model_configured = model_configured


def handle(message: str, *, channel: str = "web") -> Reply:
    """Entry the workbench and future adapters call. Returns the reply for this turn."""
    if not _model_configured or _loop is None:
        logger.info("入口拒绝 模型还没配好。")
        raise ModelNotConfigured("模型还没配好。在 .env 里设置 TYPESAFE_API_KEY 后再试。")
    text = (message or "").strip()
    if not text:
        logger.info("入口拒绝 先写一句话。")
        raise ReplyError("先写一句话。")
    logger.info("入口接受 channel=%s %s", channel, text)
    return _loop.handle(text, channel=channel)
