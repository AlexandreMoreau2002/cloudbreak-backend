from fastapi import APIRouter, Depends

from app.core.dependencies import get_current_user

router = APIRouter(prefix="/api/v1/user", tags=["user"])


@router.get("/me")
def get_me(current_user: dict[str, object] = Depends(get_current_user)) -> dict[str, object]:
    return current_user
