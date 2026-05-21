from datetime import datetime
from typing import Any

from sqlalchemy import Select, and_, func, select, update
from sqlalchemy.exc import DataError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.models.capture import CapturedRequest, CaptureBatch, CaptureStatus


class CaptureRepository:
    """采集数据访问层：封装批次和请求记录的数据库读写。"""

    def __init__(self, db: Session):
        self.db = db

    def create_batch(self, batch_no: str, target_url: str) -> CaptureBatch:
        """创建新采集批次，并清除旧请求的 NEW 状态。"""
        self.db.execute(update(CapturedRequest).values(is_new=False))
        batch = CaptureBatch(batch_no=batch_no, target_url=target_url)
        self.db.add(batch)
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def finish_batch(self, batch_no: str, status: str = CaptureStatus.STOPPED.value) -> CaptureBatch | None:
        """结束采集批次，写入结束时间和最终状态。"""
        batch = self.get_batch_by_no(batch_no)
        if not batch:
            return None
        batch.status = status
        batch.ended_at = datetime.now()
        self.db.commit()
        self.db.refresh(batch)
        return batch

    def get_batch_by_no(self, batch_no: str) -> CaptureBatch | None:
        """按批次编号查询采集批次。"""
        stmt = select(CaptureBatch).where(CaptureBatch.batch_no == batch_no)
        return self.db.scalar(stmt)

    def list_batches(self, keyword: str | None = None, limit: int = 30) -> list[CaptureBatch]:
        """查询历史采集批次，支持按目标 URL 模糊搜索。"""
        stmt: Select[tuple[CaptureBatch]] = select(CaptureBatch).order_by(CaptureBatch.started_at.desc()).limit(limit)
        if keyword:
            stmt = stmt.where(CaptureBatch.target_url.like(f"%{keyword}%"))
        return list(self.db.scalars(stmt))

    def save_request(self, request: CapturedRequest) -> CapturedRequest:
        """保存请求记录，并同步更新批次统计。"""
        self.db.add(request)
        batch = self.db.get(CaptureBatch, request.batch_id)
        if batch:
            batch.total_count += 1
            if request.is_api:
                batch.api_count += 1
        try:
            self.db.commit()
        except DataError:
            self.db.rollback()
            request = self._shrink_oversized_request(request)
            self.db.add(request)
            batch = self.db.get(CaptureBatch, request.batch_id)
            if batch:
                batch.total_count += 1
                if request.is_api:
                    batch.api_count += 1
            self.db.commit()
        except SQLAlchemyError:
            self.db.rollback()
            raise
        self.db.refresh(request)
        return request

    def list_requests(
        self,
        batch_no: str | None = None,
        method: str | None = None,
        keyword: str | None = None,
        only_api: bool = True,
        limit: int = 200,
    ) -> list[CapturedRequest]:
        """按筛选条件查询请求列表，默认只展示接口类请求。"""
        stmt = select(CapturedRequest).join(CaptureBatch).order_by(CapturedRequest.start_time.desc()).limit(limit)
        if batch_no:
            stmt = stmt.where(CaptureBatch.batch_no == batch_no)
        if method and method.upper() != "ALL":
            stmt = stmt.where(CapturedRequest.method == method.upper())
        if keyword:
            stmt = stmt.where(CapturedRequest.url.like(f"%{keyword}%"))
        if only_api:
            stmt = stmt.where(CapturedRequest.is_api.is_(True))
        return list(self.db.scalars(stmt))

    def get_request(self, request_pk: int) -> CapturedRequest | None:
        """按主键查询请求详情。"""
        return self.db.get(CapturedRequest, request_pk)

    def get_requests_by_ids(self, request_ids: list[int]) -> list[CapturedRequest]:
        """按用户勾选顺序批量查询请求，供多格式批量导出使用。"""
        if not request_ids:
            return []
        records = list(self.db.scalars(select(CapturedRequest).where(CapturedRequest.id.in_(request_ids))))
        record_map = {record.id: record for record in records}
        return [record_map[request_id] for request_id in request_ids if request_id in record_map]

    def get_request_by_browser_id(self, batch_id: int, request_id: str) -> CapturedRequest | None:
        """按浏览器 request_id 查询请求，用于把分批到达的响应信息补回同一条记录。"""
        stmt = select(CapturedRequest).where(
            CapturedRequest.batch_id == batch_id,
            CapturedRequest.request_id == request_id,
        )
        return self.db.scalar(stmt)

    def get_latest_request_by_signature(
        self,
        batch_id: int,
        method: str,
        domain: str,
        path: str,
    ) -> CapturedRequest | None:
        """按接口签名查找同批次最新请求，让重复轮询接口只保留最新一条。"""
        stmt = (
            select(CapturedRequest)
            .where(
                and_(
                    CapturedRequest.batch_id == batch_id,
                    CapturedRequest.method == method,
                    CapturedRequest.domain == domain,
                    CapturedRequest.path == path,
                ),
            )
            .order_by(CapturedRequest.start_time.desc(), CapturedRequest.id.desc())
            .limit(1)
        )
        return self.db.scalar(stmt)

    def update_request_runtime_fields(
        self,
        request: CapturedRequest,
        values: dict[str, Any],
    ) -> CapturedRequest:
        """更新状态码、耗时、Cookie、响应头和 cURL 等分批到达字段。"""
        for field in (
            "status_code",
            "duration_ms",
            "response_size",
            "request_headers",
            "cookies",
            "response_headers",
            "dynamic_marks",
            "raw_curl",
            "clean_curl",
        ):
            value = values.get(field)
            if value not in (None, {}, []):
                setattr(request, field, value)
        self.db.commit()
        self.db.refresh(request)
        return request

    def replace_request_with_latest_fields(
        self,
        request: CapturedRequest,
        values: dict[str, Any],
    ) -> CapturedRequest:
        """用同一路径的新请求覆盖旧记录，避免目标页轮询把列表和数据库刷爆。"""
        for field in (
            "request_id",
            "method",
            "url",
            "domain",
            "path",
            "resource_type",
            "status_code",
            "start_time",
            "duration_ms",
            "request_size",
            "response_size",
            "is_api",
            "query_params",
            "request_headers",
            "cookies",
            "request_body",
            "response_headers",
            "response_body",
            "raw_curl",
            "clean_curl",
            "dynamic_marks",
        ):
            if field in values:
                setattr(request, field, values[field])
        request.is_new = True
        self.db.commit()
        self.db.refresh(request)
        return request

    def update_response_body(self, request: CapturedRequest, response_body: Any) -> CapturedRequest:
        """按需补写响应体，避免列表轮询阶段读取大内容拖慢实时采集。"""
        request.response_body = response_body
        self.db.commit()
        self.db.refresh(request)
        return request

    def mark_request_viewed(self, request: CapturedRequest) -> CapturedRequest:
        """用户打开详情后清除 NEW 标记，保证刷新或轮询后不再重复提示。"""
        if request.is_new:
            request.is_new = False
            self.db.commit()
            self.db.refresh(request)
        return request

    def clear_current_requests(self, batch_no: str) -> int:
        """清空当前批次请求，不删除历史批次数据。"""
        batch = self.get_batch_by_no(batch_no)
        if not batch:
            return 0
        count = self.db.scalar(
            select(func.count(CapturedRequest.id)).where(CapturedRequest.batch_id == batch.id),
        ) or 0
        for request in list(batch.requests):
            self.db.delete(request)
        batch.total_count = 0
        batch.api_count = 0
        self.db.commit()
        return int(count)

    def _shrink_oversized_request(self, request: CapturedRequest) -> CapturedRequest:
        """兜底裁剪极端长字段，避免单条异常请求拖垮整批采集。"""
        request.url = self._truncate_text(request.url, 16000)
        request.path = self._truncate_text(request.path, 1000)
        request.raw_curl = self._truncate_text(request.raw_curl, 60000)
        request.clean_curl = self._truncate_text(request.clean_curl, 60000)
        return request

    def _truncate_text(self, value: str | None, limit: int) -> str | None:
        """按字符长度裁剪文本，并保留被裁剪提示。"""
        if value is None or len(value) <= limit:
            return value
        suffix = "...[内容过长，已裁剪]"
        return value[: max(0, limit - len(suffix))] + suffix
