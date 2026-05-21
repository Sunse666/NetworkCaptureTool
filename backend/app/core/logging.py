import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

from app.core.config import get_settings


def setup_logging() -> None:
    """初始化日志格式和滚动策略，记录用户操作与系统异常。"""
    settings = get_settings()
    log_dir = Path(settings.log_dir)
    log_dir.mkdir(parents=True, exist_ok=True)

    formatter = logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    )
    handler = RotatingFileHandler(
        log_dir / "network_capture.log",
        maxBytes=5 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    handler.setFormatter(formatter)

    root_logger = logging.getLogger()
    root_logger.setLevel(logging.DEBUG if settings.debug else logging.INFO)

    # 避免开发热重载或测试重复添加 handler 导致日志重复输出。
    if not any(isinstance(item, RotatingFileHandler) for item in root_logger.handlers):
        root_logger.addHandler(handler)
