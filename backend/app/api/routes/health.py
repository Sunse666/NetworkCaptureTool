from fastapi import APIRouter

from app.core.database import database_status
from app.schemas.common import ApiResponse, ok

router = APIRouter(prefix="/health", tags=["健康检查"])


@router.get("")
def health_check() -> ApiResponse:
    """服务健康检查，用于启动后自测。"""
    return ok({"status": "ok", "database": database_status()}, "服务运行正常。")
