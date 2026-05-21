from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.capture import ClearCurrentRequest, StartCaptureRequest
from app.schemas.common import ApiResponse, ok
from app.services.capture_service import capture_service

router = APIRouter(prefix="/capture", tags=["当前采集"])


@router.post("/start")
def start_capture(payload: StartCaptureRequest, db: Session = Depends(get_db)) -> ApiResponse:
    """启动浏览器并创建新采集批次。"""
    return ok(capture_service.start_capture(db, payload.url), "浏览器已启动，正在采集网络请求。")


@router.post("/stop-browser")
def stop_browser(db: Session = Depends(get_db)) -> ApiResponse:
    """关闭当前浏览器。"""
    return ok(capture_service.stop_browser(db), "浏览器已关闭。")


@router.post("/reset-profile")
def reset_browser_profile(db: Session = Depends(get_db)) -> ApiResponse:
    """重置内置浏览器登录态。"""
    return ok(capture_service.reset_browser_profile(db), "浏览器登录态已重置，请重新启动并登录目标网站。")


@router.post("/sync")
def sync_requests(batch_no: str | None = None, db: Session = Depends(get_db)) -> ApiResponse:
    """同步浏览器中新产生的请求记录。"""
    return ok(capture_service.sync_requests(db, batch_no), "请求同步完成。")


@router.delete("/current")
def clear_current(payload: ClearCurrentRequest, db: Session = Depends(get_db)) -> ApiResponse:
    """清空当前采集请求，不删除历史批次。"""
    return ok(capture_service.clear_current(db, payload.batch_no), "当前采集已清空。")
