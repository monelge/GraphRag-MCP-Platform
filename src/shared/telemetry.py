"""
OpenTelemetry entegrasyonu — mevcut PipelineTracer API'si korunur.

OTEL_EXPORTER_OTLP_ENDPOINT env var set edilirse span'lar OTLP üzerinden export edilir.
Set edilmezse yalnızca in-process (NoOp) tracing çalışır.

Kullanım:
    from src.shared.telemetry import get_otel_tracer
    tracer = get_otel_tracer()
    with tracer.start_as_current_span("my_operation") as span:
        span.set_attribute("collection", collection)
"""

from __future__ import annotations

import logging

logger = logging.getLogger(__name__)

_tracer = None


def setup_telemetry():
    """OTEL TracerProvider'ı başlatır. Uygulama başlangıcında bir kez çağrılır."""
    global _tracer
    try:
        from opentelemetry import trace
        from opentelemetry.sdk.trace import TracerProvider
        from opentelemetry.sdk.trace.export import BatchSpanProcessor
        from opentelemetry.sdk.resources import Resource

        from src.shared.config import config

        resource = Resource.create({"service.name": "graph-mcp", "service.version": "2.0"})
        provider = TracerProvider(resource=resource)

        if config.otel_endpoint:
            try:
                from opentelemetry.exporter.otlp.proto.grpc.trace_exporter import OTLPSpanExporter
                exporter = OTLPSpanExporter(endpoint=config.otel_endpoint)
                provider.add_span_processor(BatchSpanProcessor(exporter))
                logger.info("OTEL export aktif: %s", config.otel_endpoint)
            except Exception as e:
                logger.warning("OTEL exporter başlatılamadı: %s", e)

        trace.set_tracer_provider(provider)
        _tracer = trace.get_tracer("graph-mcp")
        logger.info("OpenTelemetry başlatıldı")
        return _tracer

    except ImportError:
        logger.debug("opentelemetry-sdk yüklü değil, OTEL devre dışı")
        return None
    except Exception as e:
        logger.warning("OTEL setup hatası: %s", e)
        return None


def get_otel_tracer():
    """Mevcut OTEL tracer'ı döner. setup_telemetry çağrılmamışsa None döner."""
    return _tracer
