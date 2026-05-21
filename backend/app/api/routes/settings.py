from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.schemas.common import ApiResponse, ok
from app.schemas.settings import SettingUpdateRequest
from app.services.settings_service import settings_service

router = APIRouter(prefix="/settings", tags=["设置管理"])


@router.get("/{key}")
def get_setting(key: str, db: Session = Depends(get_db)) -> ApiResponse:
    """读取指定设置。"""
    return ok(settings_service.get_setting(db, key))


@router.put("")
def save_setting(payload: SettingUpdateRequest, db: Session = Depends(get_db)) -> ApiResponse:
    """保存指定设置。"""
    return ok(
        settings_service.save_setting(db, payload.key, payload.value, payload.description),
        "设置已保存。",
    )
