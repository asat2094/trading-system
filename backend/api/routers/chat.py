from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.config import settings

router = APIRouter(prefix="/chat", tags=["chat"])


class ChatRequest(BaseModel):
    query: str


class ChatResponse(BaseModel):
    dsl: dict
    explanation: str
    results: list[dict] = []


@router.post("/query", response_model=ChatResponse)
async def chat_query(req: ChatRequest, user: User = Depends(get_current_user)):
    if not settings.ENABLE_LLM_CHAT:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="LLM chat is disabled",
        )

    try:
        from llm.translator import translate_nl_to_dsl
        dsl = await translate_nl_to_dsl(req.query)
    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_429_TOO_MANY_REQUESTS, detail=str(exc))

    from scanner.engine import Scanner
    source = dsl.get("source", {})
    universe: list[str] = []  # full universe resolved at runtime via MarketData
    s = Scanner()
    results = s.run(universe=universe, max_symbols=200)

    return ChatResponse(
        dsl=dsl,
        explanation=f"Running scan: {req.query}",
        results=results[:50],
    )
