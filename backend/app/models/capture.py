from datetime import datetime
from enum import Enum

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, Text
from sqlalchemy.dialects import mysql
from sqlalchemy.dialects.mysql import JSON
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.core.database import Base


class CaptureStatus(str, Enum):
    """采集批次状态：用于前端展示当前采集是否仍在运行。"""

    RUNNING = "running"
    STOPPED = "stopped"
    FAILED = "failed"


class CaptureBatch(Base):
    """采集批次表：一次输入 URL 并启动采集，对应一个批次。"""

    __tablename__ = "capture_batches"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    batch_no: Mapped[str] = mapped_column(String(32), unique=True, index=True, nullable=False)
    target_url: Mapped[str] = mapped_column(String(2048), nullable=False)
    status: Mapped[str] = mapped_column(String(24), default=CaptureStatus.RUNNING.value, nullable=False)
    started_at: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    total_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    api_count: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    remark: Mapped[str | None] = mapped_column(String(255), nullable=True)

    requests: Mapped[list["CapturedRequest"]] = relationship(
        back_populates="batch",
        cascade="all, delete-orphan",
    )


class CapturedRequest(Base):
    """请求记录表：保存一次浏览器网络请求的结构化信息。"""

    __tablename__ = "captured_requests"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    request_id: Mapped[str] = mapped_column(String(128), index=True, nullable=False)
    batch_id: Mapped[int] = mapped_column(ForeignKey("capture_batches.id"), nullable=False)
    method: Mapped[str] = mapped_column(String(16), index=True, nullable=False)
    url: Mapped[str] = mapped_column(Text().with_variant(mysql.LONGTEXT, "mysql"), nullable=False)
    domain: Mapped[str] = mapped_column(String(255), index=True, nullable=False)
    path: Mapped[str] = mapped_column(String(1024), index=True, nullable=False)
    resource_type: Mapped[str] = mapped_column(String(64), default="Other", nullable=False)
    status_code: Mapped[int | None] = mapped_column(Integer, index=True, nullable=True)
    start_time: Mapped[datetime] = mapped_column(DateTime, default=datetime.now, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer, nullable=True)
    request_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    response_size: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_new: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    is_api: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)
    query_params: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    request_headers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    cookies: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    request_body: Mapped[dict | str | None] = mapped_column(JSON, nullable=True)
    response_headers: Mapped[dict] = mapped_column(JSON, default=dict, nullable=False)
    response_body: Mapped[dict | str | None] = mapped_column(JSON, nullable=True)
    raw_curl: Mapped[str | None] = mapped_column(Text().with_variant(mysql.LONGTEXT, "mysql"), nullable=True)
    clean_curl: Mapped[str | None] = mapped_column(Text().with_variant(mysql.LONGTEXT, "mysql"), nullable=True)
    dynamic_marks: Mapped[list] = mapped_column(JSON, default=list, nullable=False)

    batch: Mapped[CaptureBatch] = relationship(back_populates="requests")
