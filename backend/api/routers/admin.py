from fastapi import APIRouter, Depends
from core.auth.middleware import get_current_user
from core.auth.provider import User

router = APIRouter(prefix="/admin", tags=["admin"])


@router.get("/activities")
async def list_activities(user: User = Depends(get_current_user)):
    from workers.registry import register_all
    activities = register_all()
    return [{"name": name, "path": str(path)} for name, path in activities]
