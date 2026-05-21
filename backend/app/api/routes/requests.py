from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.capture import BatchExportRequest
from app.schemas.common import ApiResponse, ok
from app.services.capture_service import capture_service

router = APIRouter(prefix="/requests", tags=["请求记录"])


@router.get("")
def list_requests(
    batch_no: str | None = None,
    method: str | None = None,
    keyword: str | None = None,
    only_api: bool = True,
    limit: int = Query(200, ge=1, le=1000),
    db: Session = Depends(get_db),
) -> ApiResponse:
    """查询请求列表，支持按批次、方法和关键字筛选。"""
    return ok(
        capture_service.list_requests(
            db,
            batch_no=batch_no,
            method=method,
            keyword=keyword,
            only_api=only_api,
            limit=limit,
        ),
    )


@router.get("/{request_id}")
def get_request_detail(request_id: int, db: Session = Depends(get_db)) -> ApiResponse:
    """查询单条请求详情。"""
    return ok(capture_service.get_request_detail(db, request_id))


@router.post("/export")
def export_requests(payload: BatchExportRequest, db: Session = Depends(get_db)) -> ApiResponse:
    """按指定格式批量导出用户勾选的请求。"""
    return ok(
        capture_service.export_requests(db, payload.request_ids, payload.format),
        "批量导出文件已生成。",
    )
