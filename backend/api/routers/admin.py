from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from core.auth.middleware import get_current_user
from core.auth.provider import User
from core.db import AsyncSessionLocal
from sqlalchemy import text

router = APIRouter(prefix="/admin", tags=["admin"])


class ActivitySubmit(BaseModel):
    name: str
    code: str
    prompt: str = ""
    generator: str = "human"


@router.get("/activities")
async def list_activities(user: User = Depends(get_current_user)):
    from workers.registry import register_all
    activities = register_all()
    return [{"name": name, "path": str(path)} for name, path in activities]


@router.post("/activities")
async def submit_activity(req: ActivitySubmit, user: User = Depends(get_current_user)):
    from workers.security import validate_activity_code, SecurityViolation
    try:
        validate_activity_code(req.code)
    except SecurityViolation as exc:
        raise HTTPException(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            detail=f"Security gate rejected: {exc}",
        )

    async with AsyncSessionLocal() as session:
        await session.execute(text("""
            INSERT INTO agent_activities (name, file_path, status, generator, prompt)
            VALUES (:name, :file_path, 'proposed', :generator, :prompt)
        """), {
            "name": req.name,
            "file_path": f"workers/activities/{req.name}.py",
            "generator": req.generator,
            "prompt": req.prompt,
        })
        await session.commit()

    return {"status": "proposed", "name": req.name}


@router.post("/activities/{name}/approve")
async def approve_activity(name: str, user: User = Depends(get_current_user)):
    async with AsyncSessionLocal() as session:
        result = await session.execute(
            text("SELECT file_path FROM agent_activities WHERE name = :name AND status = 'proposed'"),
            {"name": name},
        )
        row = result.fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="Activity not found or not in proposed state")

        await session.execute(text("""
            UPDATE agent_activities
            SET status = 'approved', approved_by = :approver, approved_at = now()
            WHERE name = :name
        """), {"name": name, "approver": user.username})
        await session.commit()

    return {"status": "approved", "name": name, "message": "Restart Temporal worker to activate"}
