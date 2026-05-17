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
