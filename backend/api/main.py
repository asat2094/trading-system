import asyncio
from contextlib import asynccontextmanager
from fastapi import FastAPI, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from prometheus_fastapi_instrumentator import Instrumentator
from api.middleware import TraceIdMiddleware
from api.routers import auth, technical, scanner, admin, fno
from api.routers.technical import warm_symbol_cache
from api.signals_ws import websocket_endpoint
from core.logging import setup_logging


@asynccontextmanager
async def lifespan(app: FastAPI):
    # Pre-warm symbol cache in background — doesn't block startup
    asyncio.create_task(warm_symbol_cache())
    yield


def create_app() -> FastAPI:
    setup_logging()
    app = FastAPI(title="Trading System", version="0.1.0", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://localhost:3000"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    app.add_middleware(TraceIdMiddleware)
    Instrumentator().instrument(app).expose(app)

    app.include_router(auth.router)
    app.include_router(technical.router)
    app.include_router(scanner.router)
    app.include_router(admin.router)
    app.include_router(fno.router)

    @app.websocket("/ws/signals")
    async def signals_ws(ws: WebSocket, token: str, last_event_id: str = "0"):
        await websocket_endpoint(ws, token, last_event_id)

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    return app


app = create_app()
