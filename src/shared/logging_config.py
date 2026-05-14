"""Merkezi logging yapılandırması."""

from __future__ import annotations

import json
import logging
import logging.handlers
import pathlib
import sys
import time

from src.shared.config import config


class JsonFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        payload = {
            "ts": self._iso_time(record.created),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
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
        t = time.gmtime(ts)
        ms = int((ts - int(ts)) * 1000)
        return f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}T{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}.{ms:03d}Z"


class PrettyFormatter(logging.Formatter):
    _LEVEL_ICONS = {"DEBUG": "🔍", "INFO": "ℹ️ ", "WARNING": "⚠️ ", "ERROR": "❌", "CRITICAL": "🔥"}

    def format(self, record: logging.LogRecord) -> str:
        base = f"{self.formatTime(record, '%H:%M:%S')} {self._LEVEL_ICONS.get(record.levelname, '  ')} [{record.name}] {record.getMessage()}"
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
            file_handler = logging.handlers.RotatingFileHandler(config.log_file, maxBytes=10 * 1024 * 1024, backupCount=5, encoding="utf-8")
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
