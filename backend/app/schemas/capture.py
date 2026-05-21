from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, Field


class StartCaptureRequest(BaseModel):
    """启动采集入参：前端传入目标网址。"""

    url: str = Field(..., description="目标网站地址")


class CaptureBatchOut(BaseModel):
    """采集批次出参：用于历史列表和当前采集状态展示。"""

    batch_no: str
    target_url: str
    status: str
    started_at: datetime
    ended_at: datetime | None
    total_count: int
    api_count: int


class CapturedRequestListOut(BaseModel):
    """请求列表出参：列表只返回摘要字段，避免大响应体拖慢界面。"""

    id: int
    request_id: str
    batch_no: str
    method: str
    url: str
    domain: str
    path: str
    resource_type: str
    status_code: int | None
    start_time: datetime
    duration_ms: int | None
    request_size: int | None
    response_size: int | None
    is_new: bool
    is_api: bool
    dynamic_marks: list[dict[str, Any]]


class CapturedRequestDetailOut(CapturedRequestListOut):
    """请求详情出参：包含参数、响应、Header、Cookie、令牌和 cURL。"""

    query_params: dict[str, Any]
    request_headers: dict[str, Any]
    cookies: dict[str, Any]
    request_body: Any
    response_headers: dict[str, Any]
    response_body: Any
    raw_curl: str | None
    clean_curl: str | None
    auth_tokens: list[dict[str, Any]]


class ClearCurrentRequest(BaseModel):
    """清空当前采集入参。"""

    batch_no: str


class BatchExportRequest(BaseModel):
    """批量导出入参：前端传入勾选请求和目标导出格式。"""

    request_ids: list[int] = Field(..., min_length=1, description="需要导出的请求 ID 列表")
    format: Literal["openapi", "postman", "curl", "apifox"] = Field(..., description="导出格式")
