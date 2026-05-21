from typing import Any

from sqlalchemy.orm import Session

from app.repositories.settings_repository import SettingsRepository
from app.schemas.settings import BackgroundSetting


DEFAULT_BACKGROUND = BackgroundSetting().model_dump()


class SettingsService:
    """设置业务服务：管理背景、导出偏好和后续可扩展配置。"""

    def get_setting(self, db: Session, key: str) -> dict[str, Any]:
        """读取指定设置；背景设置不存在时返回默认值。"""
        setting = SettingsRepository(db).get_setting(key)
        if setting:
            return setting.setting_value
        if key == "background":
            return DEFAULT_BACKGROUND
        return {}

    def save_setting(
        self,
        db: Session,
        key: str,
        value: dict[str, Any],
        description: str | None = None,
    ) -> dict[str, Any]:
        """保存设置并记录用户操作日志。"""
        repo = SettingsRepository(db)
        setting = repo.upsert_setting(key, value, description)
        repo.create_log("settings", "save_setting", "success", f"保存设置：{key}")
        return setting.setting_value


settings_service = SettingsService()
