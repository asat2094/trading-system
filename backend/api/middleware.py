import uuid
from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
import structlog


class TraceIdMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        structlog.contextvars.bind_contextvars(trace_id=trace_id)
        response = await call_next(request)
        response.headers["X-Trace-ID"] = trace_id
        structlog.contextvars.unbind_contextvars("trace_id")
        return response
