"""
Merkezi Logging Yapılandırması

Neden bu modül?
  MCP server stdio modunda çalışır — stdout MCP protokolü için ayrılmıştır.
  Tüm loglar stderr'e yazılmalıdır; aksi hâlde Claude Desktop bağlantısı bozulur.

Özellikler:
  - JSON formatında yapılandırılmış log (docker logs ile ayrıştırılabilir)
  - Her log satırında: timestamp, level, logger_name, message, [extra fields]
  - Gürültülü 3rd-party kütüphaneler (httpx, onnxruntime vb.) WARNING seviyesine çekilir
  - LOG_LEVEL env değişkeniyle çalışma zamanında seviye değiştirilebilir

Kullanım:
    from src.shared.logging_config import setup_logging, get_logger
    setup_logging()                         # mcp_server.py başında bir kez çağırılır
    logger = get_logger(__name__)           # her modülde
    logger.info("Bağlantı kuruldu", extra={"host": "neo4j", "latency_ms": 42})
"""

from __future__ import annotations

import json
import logging
import logging.handlers
import os
import sys
import time
import traceback
from typing import Any


# ---------------------------------------------------------------------------
# JSON Log Formatter
# ---------------------------------------------------------------------------

class JsonFormatter(logging.Formatter):
    """
    Her log kaydını tek satırlık JSON olarak üretir.

    Neden JSON?
      `docker logs graph-mcp | jq 'select(.level=="ERROR")'` gibi
      araçlarla anında filtrelenebilir. Düz metin loglar bu esnekliği vermez.
    """

    def format(self, record: logging.LogRecord) -> str:
        # Temel alanlar
        payload: dict[str, Any] = {
            "ts": self._iso_time(record.created),
            "level": record.levelname,
            "logger": record.name,
            "msg": record.getMessage(),
        }

        # Exception varsa stack trace ekle
        if record.exc_info:
            payload["exc"] = self.formatException(record.exc_info)
        elif record.exc_text:
            payload["exc"] = record.exc_text

        # logger.info("...", extra={"latency_ms": 42}) şeklinde gelen alanlar
        skip = {
            "name", "msg", "args", "created", "filename", "funcName",
            "levelname", "levelno", "lineno", "module", "msecs",
            "pathname", "process", "processName", "relativeCreated",
            "stack_info", "thread", "threadName", "exc_info", "exc_text",
            "message",
        }
        for k, v in record.__dict__.items():
            if k not in skip:
                payload[k] = v

        return json.dumps(payload, ensure_ascii=False, default=str)

    @staticmethod
    def _iso_time(ts: float) -> str:
        """Unix timestamp → ISO-8601 UTC string."""
        t = time.gmtime(ts)
        ms = int((ts - int(ts)) * 1000)
        return f"{t.tm_year}-{t.tm_mon:02d}-{t.tm_mday:02d}T" \
               f"{t.tm_hour:02d}:{t.tm_min:02d}:{t.tm_sec:02d}.{ms:03d}Z"


# ---------------------------------------------------------------------------
# İnsan Okunabilir Formatter (geliştirme ortamı)
# ---------------------------------------------------------------------------

class PrettyFormatter(logging.Formatter):
    """
    Terminalde renksiz ama okunabilir log satırı üretir.
    LOG_FORMAT=pretty env değişkeniyle aktive edilir.
    """

    _LEVEL_ICONS = {
        "DEBUG":    "🔍",
        "INFO":     "ℹ️ ",
        "WARNING":  "⚠️ ",
        "ERROR":    "❌",
        "CRITICAL": "🔥",
    }

    def format(self, record: logging.LogRecord) -> str:
        icon = self._LEVEL_ICONS.get(record.levelname, "  ")
        ts = self.formatTime(record, "%H:%M:%S")
        base = f"{ts} {icon} [{record.name}] {record.getMessage()}"
        if record.exc_info:
            base += "\n" + self.formatException(record.exc_info)
        return base


# ---------------------------------------------------------------------------
# Ana kurulum fonksiyonu
# ---------------------------------------------------------------------------

def setup_logging() -> None:
    """
    Root logger'ı yapılandırır. mcp_server.py başında bir kez çağırılmalıdır.

    Env değişkenleri:
      LOG_LEVEL  — DEBUG | INFO | WARNING | ERROR  (varsayılan: INFO)
      LOG_FORMAT — json | pretty                   (varsayılan: json)
      LOG_FILE   — Dosya yolu (varsayılan: /app/data/graph-mcp.log)
                   Boş string verilirse dosya logu devre dışı kalır.

    Neden dosya logu?
      MCP istemcisi her tool çağrısında `docker exec` ile yeni bir process başlatır.
      Bu process'in stderr'i docker logs'a değil, MCP istemcisine gider.
      Kalıcı log için /app/data/ (volume mount) altına yazılır; host'tan erişilebilir.
    """
    level_name = os.getenv("LOG_LEVEL", "INFO").upper()
    level = getattr(logging, level_name, logging.INFO)

    fmt_name = os.getenv("LOG_FORMAT", "json").lower()
    formatter: logging.Formatter = (
        PrettyFormatter() if fmt_name == "pretty" else JsonFormatter()
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.handlers.clear()

    # Tüm loglar stderr'e — stdout MCP protokolü için ayrılmış
    stderr_handler = logging.StreamHandler(sys.stderr)
    stderr_handler.setFormatter(formatter)
    root.addHandler(stderr_handler)

    # Dosya logu — docker exec process'leri de dahil tüm çağrıları yakalar
    log_file = os.getenv("LOG_FILE", "/app/data/graph-mcp.log")
    if log_file:
        try:
            import pathlib
            pathlib.Path(log_file).parent.mkdir(parents=True, exist_ok=True)
            file_handler = logging.handlers.RotatingFileHandler(
                log_file,
                maxBytes=10 * 1024 * 1024,  # 10 MB
                backupCount=5,
                encoding="utf-8",
            )
            file_handler.setFormatter(JsonFormatter())
            root.addHandler(file_handler)
        except Exception as _e:
            # Dosyaya yazılamazsa sessizce devam et — stderr çalışıyor
            sys.stderr.write(f"[logging_config] Dosya logu açılamadı: {_e}\n")

    # ---------------------------------------------------------------------------
    # Gürültülü 3rd-party kütüphaneleri sustur
    # ---------------------------------------------------------------------------
    _noisy = [
        "httpx", "httpcore", "openai", "neo4j",
        "onnxruntime", "urllib3", "asyncio",
        "uvicorn.access", "fastapi",
    ]
    for name in _noisy:
        logging.getLogger(name).setLevel(logging.WARNING)

    # neo4j.notifications çok verbose — sadece ERROR'a izin ver
    logging.getLogger("neo4j.notifications").setLevel(logging.ERROR)

    logging.getLogger(__name__).info(
        "Logging başlatıldı",
        extra={"level": level_name, "format": fmt_name},
    )


def get_logger(name: str) -> logging.Logger:
    """
    Modül düzeyinde logger alır.

    Kullanım:
        logger = get_logger(__name__)
    """
    return logging.getLogger(name)
