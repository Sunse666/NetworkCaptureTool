import logging

from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models.settings import OperationLog, UserSetting

logger = logging.getLogger(__name__)


class SettingsRepository:
    """设置和操作日志数据访问层。"""

    LOG_FIELD_LIMITS = {
        "module": 64,
        "action": 64,
        "result": 32,
        "batch_no": 32,
        "request_id": 128,
    }

    def __init__(self, db: Session):
        self.db = db

    def get_setting(self, key: str) -> UserSetting | None:
        """按 key 查询用户设置。"""
        return self.db.scalar(select(UserSetting).where(UserSetting.setting_key == key))

    def upsert_setting(self, key: str, value: dict, description: str | None = None) -> UserSetting:
        """新增或更新用户设置，保证同一个 key 只有一条记录。"""
        setting = self.get_setting(key)
        if setting is None:
            setting = UserSetting(setting_key=key, setting_value=value, description=description)
            self.db.add(setting)
        else:
            setting.setting_value = value
            if description is not None:
                setting.description = description
        self.db.commit()
        self.db.refresh(setting)
        return setting

    def create_log(
        self,
        module: str,
        action: str,
        result: str,
        message: str | None = None,
        batch_no: str | None = None,
        request_id: str | None = None,
    ) -> OperationLog:
        """记录用户操作日志，便于排查问题和审计关键动作。"""
        log = OperationLog(
            module=self._limit_text(module, self.LOG_FIELD_LIMITS["module"]),
            action=self._limit_text(action, self.LOG_FIELD_LIMITS["action"]),
            result=self._limit_text(result, self.LOG_FIELD_LIMITS["result"]),
            message=message,
            batch_no=self._limit_text(batch_no, self.LOG_FIELD_LIMITS["batch_no"]),
            request_id=self._limit_text(request_id, self.LOG_FIELD_LIMITS["request_id"]),
        )
        self.db.add(log)
        try:
            self.db.commit()
            self.db.refresh(log)
        except SQLAlchemyError:
            # 日志是辅助审计能力，写入失败不应阻断导出、采集等主业务流程。
            self.db.rollback()
            logger.warning("操作日志写入失败，已忽略本次日志。", exc_info=True)
        return log

    def _limit_text(self, value: str | None, limit: int) -> str | None:
        """按数据库字段长度裁剪文本，避免日志字段过长导致主业务失败。"""
        if value is None or len(value) <= limit:
            return value
        suffix = "...[截断]"
        return value[: max(0, limit - len(suffix))] + suffix
