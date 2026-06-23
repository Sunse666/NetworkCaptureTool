import sys
from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


def app_base_dir() -> Path:
    """返回应用资源根目录，兼容源码运行和 PyInstaller 打包运行。"""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).resolve().parent
    return Path.cwd()


def bundled_resource_dir() -> Path:
    """返回 PyInstaller 解包资源目录；源码运行时退回到当前工作目录。"""
    meipass = getattr(sys, "_MEIPASS", None)
    return Path(meipass).resolve() if meipass else Path.cwd()


def resolve_runtime_path(path: Path | str) -> Path:
    """解析运行时可写路径，桌面版写入 exe 同级目录，源码运行写入当前目录。"""
    target = Path(path)
    if target.is_absolute():
        return target
    return app_base_dir() / target


def resolve_resource_path(path: Path | str) -> Path:
    """解析随包资源路径，优先从 PyInstaller 解包目录读取。"""
    target = Path(path)
    if target.is_absolute():
        return target
    bundled_path = bundled_resource_dir() / target
    if bundled_path.exists():
        return bundled_path
    project_path = app_base_dir().parent / target
    if project_path.exists():
        return project_path
    return app_base_dir() / target


class Settings(BaseSettings):
    """应用配置：集中读取环境变量，避免配置散落在业务代码里。"""

    app_name: str = "浏览器网络请求采集工具"
    app_host: str = "127.0.0.1"
    app_port: int = 8710
    debug: bool = False

    mysql_host: str = "127.0.0.1"
    mysql_port: int = 3306
    mysql_user: str = "root"
    mysql_password: str = ""
    mysql_database: str = "network_capture_studio"
    mysql_charset: str = "utf8mb4"
    database_engine: str = "mysql"
    sqlite_path: Path = Field(default=Path("runtime/network_capture_studio.db"))

    auto_launch_browser: bool = True
    browser_type: str = "webview2"
    browser_headless: bool = False
    browser_window_width: int = 1440
    browser_window_height: int = 900
    browser_page_load_timeout: int = 15
    browser_script_timeout: int = 8
    browser_user_data_dir: Path = Field(default=Path("runtime/chrome-profile"))
    chrome_binary: str | None = None
    chromedriver_path: str | None = "runtime/drivers/chromedriver.exe"
    edge_binary: str | None = None
    msedgedriver_path: str | None = "runtime/drivers/msedgedriver.exe"
    edge_user_data_dir: Path = Field(default=Path("runtime/edge-profile"))
    frontend_dist_dir: Path = Field(default=Path("../frontend/dist"))

    log_dir: Path = Field(default=Path("logs"))
    max_response_body_chars: int = 8000

    model_config = SettingsConfigDict(
        env_file=resolve_resource_path(".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    @property
    def database_url(self) -> str:
        """拼接数据库连接串，桌面版默认可切换 SQLite，开发/团队环境仍可使用 MySQL。"""
        if self.database_engine.lower() == "sqlite":
            sqlite_path = resolve_runtime_path(self.sqlite_path)
            return f"sqlite:///{sqlite_path.as_posix()}"
        return (
            f"mysql+pymysql://{self.mysql_user}:{self.mysql_password}"
            f"@{self.mysql_host}:{self.mysql_port}/{self.mysql_database}"
            f"?charset={self.mysql_charset}"
        )


@lru_cache
def get_settings() -> Settings:
    """缓存配置对象，避免每次请求重复读取环境变量。"""
    return Settings()
