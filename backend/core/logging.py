import contextvars
import structlog

trace_id_var: contextvars.ContextVar[str] = contextvars.ContextVar("trace_id", default="")


def setup_logging() -> None:
    structlog.configure(
        processors=[
            structlog.contextvars.merge_contextvars,
            structlog.processors.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.JSONRenderer(),
        ],
        wrapper_class=structlog.BoundLogger,
        context_class=dict,
        logger_factory=structlog.PrintLoggerFactory(),
    )
    import logging
    logging.basicConfig(
        level=logging.INFO,
        format="%(message)s",
    )


def get_logger(name: str):
    return structlog.get_logger(name)


def setup_tracing() -> None:
    """Enable OpenTelemetry/Jaeger tracing when OTEL_ENABLED=true."""
    import os
    if os.getenv("OTEL_ENABLED", "false").lower() != "true":
        return
    from opentelemetry import trace
    from opentelemetry.sdk.trace import TracerProvider
    from opentelemetry.exporter.jaeger.thrift import JaegerExporter
    from opentelemetry.sdk.trace.export import BatchSpanProcessor

    provider = TracerProvider()
    exporter = JaegerExporter(agent_host_name="localhost", agent_port=6831)
    provider.add_span_processor(BatchSpanProcessor(exporter))
    trace.set_tracer_provider(provider)
