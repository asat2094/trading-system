from fastapi import FastAPI, WebSocket
from api.middleware import TraceIdMiddleware
from api.routers import auth, technical, scanner, admin
from api.signals_ws import websocket_endpoint
from core.logging import setup_logging


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="Trading System", version="0.1.0")
    app.add_middleware(TraceIdMiddleware)

    app.include_router(auth.router)
    app.include_router(technical.router)
    app.include_router(scanner.router)
    app.include_router(admin.router)

    @app.websocket("/ws/signals")
    async def signals_ws(ws: WebSocket, token: str, last_event_id: str = "0"):
        await websocket_endpoint(ws, token, last_event_id)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
