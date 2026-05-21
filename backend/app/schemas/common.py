from typing import Generic, TypeVar

from pydantic import BaseModel


T = TypeVar("T")


class ApiResponse(BaseModel, Generic[T]):
    """统一响应结构：前端可以稳定读取 success、message 和 data。"""

    success: bool = True
    code: str = "OK"
    message: str = "操作成功"
    data: T | None = None


def ok(data: T | None = None, message: str = "操作成功") -> ApiResponse[T]:
    """快速构造成功响应，减少路由层重复代码。"""
    return ApiResponse(data=data, message=message)
