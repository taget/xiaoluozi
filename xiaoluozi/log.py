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
