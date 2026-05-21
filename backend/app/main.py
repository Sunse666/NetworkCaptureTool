from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from sqlalchemy.exc import SQLAlchemyError

from app.api.routes import capture, health, history, requests, settings
from app.core.config import get_settings, resolve_resource_path
from app.core.database import Base, engine, ensure_database_exists, mark_database_error
from app.core.exceptions import register_exception_handlers
from app.core.logging import setup_logging


def _mount_frontend(app: FastAPI) -> None:
    """桌面版直接托管前端构建产物，exe 启动后不再依赖 Node/Vite。"""
    frontend_dir = resolve_resource_path(get_settings().frontend_dist_dir)
    index_file = frontend_dir / "index.html"
    assets_dir = frontend_dir / "assets"
    if not index_file.is_file():
        return
    if assets_dir.is_dir():
        app.mount("/assets", StaticFiles(directory=assets_dir), name="assets")

    @app.get("/{full_path:path}", include_in_schema=False)
    def serve_frontend(full_path: str) -> FileResponse:
        """返回 Vue 单页应用入口，让前端刷新和直接访问都能正常显示。"""
        return FileResponse(index_file)


def create_app() -> FastAPI:
    """创建 FastAPI 应用，集中注册中间件、路由和异常处理。"""
    setup_logging()
    try:
        ensure_database_exists()
        Base.metadata.create_all(bind=engine)
    except (SQLAlchemyError, Exception) as exc:
        # 数据库配置错误时仍允许服务启动，前端可通过健康检查看到中文提示。
        mark_database_error(exc)
    app = FastAPI(title="浏览器网络请求采集工具接口", version="0.1.0")
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )
    register_exception_handlers(app)
    app.include_router(health.router, prefix="/api")
    app.include_router(capture.router, prefix="/api")
    app.include_router(requests.router, prefix="/api")
    app.include_router(history.router, prefix="/api")
    app.include_router(settings.router, prefix="/api")
    _mount_frontend(app)
    return app


app = create_app()
