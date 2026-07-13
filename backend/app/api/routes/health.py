from fastapi import APIRouter

router = APIRouter(prefix="/healthz", tags=["health"])


@router.get("/")
async def healthz() -> dict:
    return {"status": "ok"}
