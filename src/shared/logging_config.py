"""Merkezi logging yapılandırması."""

from __future__ import annotations

import contextvars
import json
import logging
import logging.handlers
import os
import pathlib
import sys
import threading
import time

from src.shared.config import config

CORRELATION_ID = contextvars.ContextVar("correlation_id", default="-")

def get_correlation_id() -> str:
    return CORRELATION_ID.get()

def set_correlation_id(val: str) -> contextvars.Token:
    return CORRELATION_ID.set(val)

def clear_correlation_id(token: contextvars.Token) -> None:
    CORRELATION_ID.reset(token)


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self._iso_time(record.created),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
            "correlation_id": CORRELATION_ID.get(),
            "pid": os.getpid(),
            "thread": threading.current_thread().name,
        }
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        skip = {"name", "msg", "args", "created", "filename", "funcName", "levelname", "levelno", "lineno", "module", "msecs", "pathname", "process", "processName", "relativeCreated", "stack_info", "thread", "threadName", "exc_info", "exc_text", "message"}
        for key, value in record.__dict__.items():
            if key not in skip:
                payload[key] = value
        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _iso_time(ts: float) -> str:
        import datetime
        dt = datetime.datetime.fromtimestamp(ts)
        offset = dt.astimezone().strftime("%z")
        formatted_offset = f"{offset[:3]}:{offset[3:]}" if len(offset) == 5 else offset
        return dt.strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + formatted_offset


class PrettyFormatter(logging.Formatter):
    _LEVEL_ICONS = {"DEBUG": "🔍", "INFO": "ℹ️ ", "WARNING": "⚠️ ", "ERROR": "❌", "CRITICAL": "🔥"}

    def format(self, record: logging.LogRecord) -> str:
        correlation = CORRELATION_ID.get()
        trace_prefix = f" [{correlation}]" if correlation and correlation != "-" else ""
        base = f"{self.formatTime(record, '%H:%M:%S')} {self._LEVEL_ICONS.get(record.levelname, '  ')}{trace_prefix} [{record.name}] {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


def setup_logging() -> None:
    level = getattr(logging, config.log_level.upper(), logging.INFO)
    formatter = PrettyFormatter() if config.log_format == "pretty" else JsonFormatter()
    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)
    if config.log_file:
        try:
            pathlib.Path(config.log_file).parent.mkdir(parents=True, exist_ok=True)
            # Enterprise format: 50MB, max 10 backups
            file_handler = logging.handlers.RotatingFileHandler(config.log_file, maxBytes=50 * 1024 * 1024, backupCount=10, encoding="utf-8")
            file_handler.setFormatter(JsonFormatter())
            root.addHandler(file_handler)
        except Exception as exc:
            sys.stderr.write(f"[logging_config] Dosya logu açılamadı: {exc}\n")
    for name in ["httpx", "httpcore", "openai", "neo4j", "onnxruntime", "urllib3", "asyncio", "uvicorn.access", "fastapi"]:
        logging.getLogger(name).setLevel(logging.WARNING)
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)
    logging.getLogger(__name__).info("Logging başlatıldı", extra={"level": config.log_level, "format": config.log_format})


def get_logger(name: str) -> logging.Logger:
    return logging.getLogger(name)
