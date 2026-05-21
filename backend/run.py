import uvicorn

from app.core.config import get_settings


def main() -> None:
    """本地启动入口：python run.py 即可启动后端服务。"""
    settings = get_settings()
    uvicorn.run(
        "app.main:app",
        host=settings.app_host,
        port=settings.app_port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
