from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import ApiResponse, ok
from app.services.capture_service import capture_service

router = APIRouter(prefix="/history", tags=["历史采集"])


@router.get("/batches")
def list_batches(keyword: str | None = None, db: Session = Depends(get_db)) -> ApiResponse:
    """查询历史采集批次。"""
    return ok(capture_service.list_batches(db, keyword=keyword))
