from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse


class AppError(Exception):
    """业务异常：用于向前端返回中文、可理解、可恢复的错误提示。"""

    def __init__(self, message: str, code: str = "BUSINESS_ERROR", status_code: int = 400):
        self.message = message
        self.code = code
        self.status_code = status_code
        super().__init__(message)


def register_exception_handlers(app: FastAPI) -> None:
    """注册统一异常处理，避免把技术堆栈直接暴露给用户。"""

    @app.exception_handler(AppError)
    async def handle_app_error(_: Request, exc: AppError) -> JSONResponse:
        return JSONResponse(
            status_code=exc.status_code,
            content={"success": False, "code": exc.code, "message": exc.message, "data": None},
        )

    @app.exception_handler(Exception)
    async def handle_unknown_error(_: Request, exc: Exception) -> JSONResponse:
        return JSONResponse(
            status_code=500,
            content={
                "success": False,
                "code": "SYSTEM_ERROR",
                "message": "系统开了个小差，请稍后重试；如果多次出现，请复制错误详情反馈给开发人员。",
                "data": {"detail": str(exc)},
            },
        )
