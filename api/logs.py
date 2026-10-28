import json
import logging
import sys
from contextlib import contextmanager
from contextvars import ContextVar

from fastapi import Request

IDS = ("user_id", "workspace_id", "run_id")

# one dict per request (or worker run). FastAPI runs sync dependencies in a copy of the context,
# so a .set() there would never reach the route: they mutate this dict through tag() instead
context: ContextVar[dict | None] = ContextVar("log_context", default=None)


@contextmanager
def scope(**ids):
    token = context.set(ids)
    try:
        yield
    finally:
        context.reset(token)


def tag(**ids) -> None:
    current = context.get()
    if current is not None:
        current.update(ids)


class ContextFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        for key, value in (context.get() or {}).items():
            if not hasattr(record, key):
                setattr(record, key, value)
        return True


class JsonFormatter(logging.Formatter):
    # Cloud Logging reads one JSON object per stdout line; the traceback rides inside `message`
    def format(self, record: logging.LogRecord) -> str:
        entry = {"severity": record.levelname, "logger": record.name, "message": super().format(record)}
        entry.update({k: getattr(record, k) for k in IDS if hasattr(record, k)})
        return json.dumps(entry, ensure_ascii=False)


def setup() -> None:
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(JsonFormatter())
    handler.addFilter(ContextFilter())
    # no force=: under pytest the root already holds the capture handlers, and basicConfig leaves them alone
    logging.basicConfig(level=logging.INFO, handlers=[handler])
    # uvicorn's loggers bring their own text handlers and don't propagate; uvicorn.error goes through "uvicorn"
    for name in ("uvicorn", "uvicorn.access"):
        logger = logging.getLogger(name)
        logger.handlers = [handler]
        logger.propagate = False


async def request_context(request: Request, call_next):
    with scope():
        return await call_next(request)
