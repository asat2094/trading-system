import asyncio
from fastapi import WebSocket, WebSocketDisconnect, Query
from core.cache import get_redis
from core.auth.middleware import _get_provider
from core.logging import get_logger

log = get_logger(__name__)

STREAM_KEY = "signals:live"
CONSUMER_GROUP = "ws_clients"


async def websocket_endpoint(ws: WebSocket, token: str = Query(...), last_event_id: str = Query("0")):
    provider = _get_provider()
    user = await provider.verify_token(token)
    if user is None:
        await ws.close(code=1008)
        return

    await ws.accept()
    redis = get_redis()

    try:
        await redis.xgroup_create(STREAM_KEY, CONSUMER_GROUP, id="0", mkstream=True)
    except Exception:
        pass

    consumer_id = str(id(ws))
    start_id = last_event_id if last_event_id != "0" else ">"

    log.info("ws_client_connected", consumer=consumer_id)
    try:
        while True:
            messages = await redis.xreadgroup(
                groupname=CONSUMER_GROUP,
                consumername=consumer_id,
                streams={STREAM_KEY: start_id},
                count=10,
                block=5000,
            )
            if messages:
                for _, events in messages:
                    for event_id, data in events:
                        await ws.send_json({"event_id": event_id, **data})
                        await redis.xack(STREAM_KEY, CONSUMER_GROUP, event_id)
                        start_id = ">"
            await asyncio.sleep(0.1)
    except WebSocketDisconnect:
        log.info("ws_client_disconnected", consumer=consumer_id)
