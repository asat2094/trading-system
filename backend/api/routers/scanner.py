from fastapi import APIRouter, Depends
from pydantic import BaseModel
from core.auth.middleware import get_current_user
from core.auth.provider import User
from scanner.engine import Scanner

router = APIRouter(prefix="/scanner", tags=["scanner"])


class ScanRequest(BaseModel):
    universe: list[str] = []
    max_symbols: int = 500


@router.post("/run")
async def run_scan(req: ScanRequest, user: User = Depends(get_current_user)):
    s = Scanner()
    result = s.run(universe=req.universe, max_symbols=req.max_symbols)
    return {"results": result}


@router.get("/run")
async def run_scan_get(user: User = Depends(get_current_user)):
    return {"results": []}


@router.get("/signals")
async def list_signals(user: User = Depends(get_current_user)):
    from scanner.signals.loader import load_signals
    signals = load_signals()
    return [{"name": s.name, "category": s.category, "direction": s.direction} for s in signals]
