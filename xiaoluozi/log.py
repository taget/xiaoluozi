import logging
import sys


class _Stderr:
    """Write to the current stderr so test capture sees the lines."""

    def write(self, text: str) -> int:
        return sys.stderr.write(text)

    def flush(self) -> None:
        sys.stderr.flush()


def get_logger(name: str) -> logging.Logger:
    parent = logging.getLogger("xiaoluozi")
    if not parent.handlers:
        handler = logging.StreamHandler(_Stderr())
        handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s %(message)s"))
        parent.addHandler(handler)
        parent.setLevel(logging.INFO)
        parent.propagate = False
    return logging.getLogger(name)


class QuietHistoryAccess(logging.Filter):
    """History polls stay out of uvicorn's access log. Other requests still log."""

    def filter(self, record: logging.LogRecord) -> bool:
        return not _is_history_poll(record)


def silence_history_access_log() -> None:
    access = logging.getLogger("uvicorn.access")
    if any(isinstance(item, QuietHistoryAccess) for item in access.filters):
        return
    access.addFilter(QuietHistoryAccess())


def _is_history_poll(record: logging.LogRecord) -> bool:
    args = record.args
    if isinstance(args, tuple) and len(args) >= 5 and args[1] == "GET" and args[4] == 200:
        path = args[2]
        if isinstance(path, str) and path.split("?", 1)[0] == "/api/history":
            return True
    try:
        message = record.getMessage()
    except Exception:
        return False
    return '"GET /api/history ' in message and message.rstrip().endswith(" 200")
