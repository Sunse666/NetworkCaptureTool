from collections.abc import Generator

import pymysql
from sqlalchemy import create_engine
from sqlalchemy.engine import Engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.core.config import get_settings, resolve_runtime_path
from app.core.exceptions import AppError


class Base(DeclarativeBase):
    """SQLAlchemy 模型基类：所有数据库表模型都继承它。"""


settings = get_settings()
database_ready = False
database_error = ""


def ensure_database_exists() -> None:
    """确保目标数据库存在，桌面版 SQLite 会自动创建文件，MySQL 会自动建库。"""
    global database_error, database_ready
    if settings.database_engine.lower() == "sqlite":
        sqlite_path = resolve_runtime_path(settings.sqlite_path)
        sqlite_path.parent.mkdir(parents=True, exist_ok=True)
        database_ready = True
        database_error = ""
        return
    connection = pymysql.connect(
        host=settings.mysql_host,
        port=settings.mysql_port,
        user=settings.mysql_user,
        password=settings.mysql_password,
        charset=settings.mysql_charset,
        autocommit=True,
    )
    try:
        with connection.cursor() as cursor:
            cursor.execute(
                f"CREATE DATABASE IF NOT EXISTS `{settings.mysql_database}` "
                f"DEFAULT CHARACTER SET {settings.mysql_charset} COLLATE {settings.mysql_charset}_unicode_ci",
            )
    finally:
        connection.close()
    database_ready = True
    database_error = ""


def mark_database_error(error: Exception) -> None:
    """记录数据库初始化失败原因，让健康检查和业务接口返回友好提示。"""
    global database_error, database_ready
    database_ready = False
    database_error = str(error)


def database_status() -> dict[str, str | bool]:
    """返回数据库当前状态，供健康检查接口展示。"""
    engine_name = settings.database_engine.lower()
    failure_hint = (
        "数据库未就绪，请检查 runtime 目录写入权限。"
        if engine_name == "sqlite"
        else "数据库未就绪，请检查 MySQL 服务、账号、密码和 .env 配置。"
    )
    return {
        "ready": database_ready,
        "message": "数据库连接正常。" if database_ready else failure_hint,
        "detail": database_error,
    }


def _create_engine() -> Engine:
    """按数据库类型创建 SQLAlchemy 引擎，SQLite 用于桌面点击即用版本。"""
    if settings.database_engine.lower() == "sqlite":
        return create_engine(
            settings.database_url,
            connect_args={"check_same_thread": False},
            echo=settings.debug,
        )
    # MySQL 连接池开启 pool_pre_ping，避免长时间空闲后连接失效。
    return create_engine(
        settings.database_url,
        pool_pre_ping=True,
        pool_recycle=1800,
        echo=settings.debug,
    )


engine = _create_engine()

SessionLocal = sessionmaker(
    bind=engine,
    autoflush=False,
    autocommit=False,
    expire_on_commit=False,
)


def get_db() -> Generator[Session, None, None]:
    """FastAPI 依赖：为每次请求提供独立数据库会话。"""
    if not database_ready:
        raise AppError(database_status()["message"], "DATABASE_NOT_READY", 503)
    db = SessionLocal()
    try:
        yield db
    finally:
        db.close()
