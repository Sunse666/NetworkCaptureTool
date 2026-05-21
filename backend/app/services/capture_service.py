import logging
from datetime import datetime
from typing import Any

from sqlalchemy.orm import Session

from app.core.exceptions import AppError
from app.models.capture import CapturedRequest, CaptureStatus
from app.repositories.capture_repository import CaptureRepository
from app.repositories.settings_repository import SettingsRepository
from app.schemas.capture import CaptureBatchOut, CapturedRequestDetailOut, CapturedRequestListOut
from app.services.browser_service import browser_service
from app.services.batch_export_service import BatchExportService
from app.services.request_parser import RequestParser
from app.utils.url_tools import normalize_url

logger = logging.getLogger(__name__)


class CaptureService:
    """采集业务服务：串联浏览器、解析器、存储和操作日志。"""

    MAX_RECORDS_PER_SYNC = 300

    def __init__(self) -> None:
        self.parser = RequestParser()
        self.batch_exporter = BatchExportService()
        self.current_batch_no: str | None = None

    def start_capture(self, db: Session, url: str) -> CaptureBatchOut:
        """启动新采集批次，并访问目标网站。"""
        normalized_url = normalize_url(url)
        repo = CaptureRepository(db)
        log_repo = SettingsRepository(db)
        batch_no = datetime.now().strftime("%Y%m%d%H%M%S")
        batch = repo.create_batch(batch_no=batch_no, target_url=normalized_url)
        self.current_batch_no = batch.batch_no
        self.parser.reset()
        try:
            browser_service.start(normalized_url)
            log_repo.create_log("browser", "start_capture", "success", "启动采集成功", batch_no=batch_no)
            batch = repo.get_batch_by_no(batch_no) or batch
        except AppError:
            repo.finish_batch(batch_no, CaptureStatus.FAILED.value)
            log_repo.create_log("browser", "start_capture", "failed", "启动采集失败", batch_no=batch_no)
            raise
        except Exception as exc:
            logger.exception("启动采集出现未知异常，目标网址：%s", normalized_url)
            repo.finish_batch(batch_no, CaptureStatus.FAILED.value)
            log_repo.create_log("browser", "start_capture", "failed", f"启动采集异常：{exc}", batch_no=batch_no)
            raise AppError(
                "启动采集失败，请确认目标网址可访问；如果浏览器已打开但列表无数据，请关闭残留浏览器后重试。",
                "CAPTURE_START_FAILED",
                500,
            ) from exc
        return self._batch_out(batch)

    def stop_browser(self, db: Session) -> dict[str, str]:
        """关闭浏览器并结束当前批次。"""
        if self.current_batch_no:
            CaptureRepository(db).finish_batch(self.current_batch_no)
            SettingsRepository(db).create_log("browser", "stop_browser", "success", "关闭浏览器", self.current_batch_no)
        browser_service.stop()
        return {"status": "stopped"}

    def reset_browser_profile(self, db: Session) -> dict[str, str]:
        """清理内置浏览器登录态，解决目标站 token 过期或污染后反复弹错的问题。"""
        if self.current_batch_no:
            CaptureRepository(db).finish_batch(self.current_batch_no)
        browser_service.reset_profile()
        SettingsRepository(db).create_log("browser", "reset_profile", "success", "重置浏览器登录态", self.current_batch_no)
        self.current_batch_no = None
        self.parser.reset()
        return {"status": "profile_reset"}

    def sync_requests(self, db: Session, batch_no: str | None = None) -> list[CapturedRequestListOut]:
        """轮询浏览器日志，把新增请求保存到当前批次。"""
        target_batch_no = batch_no or self.current_batch_no
        if not target_batch_no:
            raise AppError("当前没有采集批次，请先输入网址并启动浏览器。", "CAPTURE_BATCH_NOT_FOUND")
        repo = CaptureRepository(db)
        batch = repo.get_batch_by_no(target_batch_no)
        if not batch:
            raise AppError("采集批次不存在，请重新启动采集。", "CAPTURE_BATCH_NOT_FOUND")

        events = browser_service.poll_network_events()
        parsed_records = self.parser.parse_performance_events(events)
        parsed_records = self._dedupe_records_for_sync(parsed_records)
        saved: list[CapturedRequest] = []
        for record in parsed_records:
            finalized = self.parser.finalize_record(record)
            existing_request = repo.get_request_by_browser_id(batch.id, record["request_id"])
            if existing_request:
                saved.append(repo.update_request_runtime_fields(existing_request, finalized))
                continue
            latest_same_path = repo.get_latest_request_by_signature(
                batch.id,
                finalized["method"],
                finalized["domain"],
                finalized["path"],
            )
            if latest_same_path:
                saved.append(repo.replace_request_with_latest_fields(latest_same_path, finalized))
                continue
            request = CapturedRequest(batch_id=batch.id, **finalized)
            saved.append(repo.save_request(request))
        if saved:
            logger.info("已同步新增请求 %s 条，批次：%s", len(saved), target_batch_no)
        return [self._request_list_out(item) for item in saved]

    def list_batches(self, db: Session, keyword: str | None = None) -> list[CaptureBatchOut]:
        """查询历史采集批次。"""
        return [self._batch_out(item) for item in CaptureRepository(db).list_batches(keyword=keyword)]

    def list_requests(
        self,
        db: Session,
        batch_no: str | None = None,
        method: str | None = None,
        keyword: str | None = None,
        only_api: bool = True,
        limit: int = 200,
    ) -> list[CapturedRequestListOut]:
        """查询请求摘要列表。"""
        repo = CaptureRepository(db)
        requests = repo.list_requests(
            batch_no=batch_no,
            method=method,
            keyword=keyword,
            only_api=only_api,
            limit=limit,
        )
        return [self._request_list_out(item) for item in requests]

    def get_request_detail(self, db: Session, request_pk: int) -> CapturedRequestDetailOut:
        """查询请求详情，并记录用户查看动作。"""
        repo = CaptureRepository(db)
        request = repo.get_request(request_pk)
        if not request:
            raise AppError("请求记录不存在，可能已被清空或删除。", "REQUEST_NOT_FOUND", 404)
        if request.response_body is None and request.is_api:
            response_body = browser_service.get_response_body(request.request_id)
            parsed_body = self.parser.parse_response_body(response_body, request.response_headers)
            if parsed_body is not None:
                request = repo.update_response_body(request, parsed_body)
        SettingsRepository(db).create_log(
            "request",
            "view_detail",
            "success",
            "查看请求详情",
            request.batch.batch_no,
            request.request_id,
        )
        request = repo.mark_request_viewed(request)
        return self._request_detail_out(request)

    def export_requests(self, db: Session, request_ids: list[int], export_format: str) -> dict[str, Any]:
        """按用户选择的格式批量导出请求，支持 OpenAPI、Postman、cURL 和 Apifox。"""
        repo = CaptureRepository(db)
        requests = repo.get_requests_by_ids(request_ids)
        if not requests:
            raise AppError("未找到可导出的请求记录，请重新选择。", "REQUEST_NOT_FOUND", 404)
        try:
            payload = self.batch_exporter.build_payload(requests, export_format)
        except ValueError as exc:
            raise AppError(str(exc), "EXPORT_FORMAT_UNSUPPORTED", 400) from exc
        SettingsRepository(db).create_log(
            "request",
            f"export_{export_format}_batch",
            "success",
            f"批量导出 {export_format}：{len(requests)} 条",
            requests[0].batch.batch_no if requests[0].batch else None,
            self._request_ids_summary(requests),
        )
        return payload

    def _request_ids_summary(self, requests: list[CapturedRequest]) -> str:
        """生成适合写入日志短字段的请求摘要，避免长 request_id 列表撑爆数据库字段。"""
        if not requests:
            return ""
        first_id = requests[0].request_id
        return f"{first_id[:80]}... 共{len(requests)}条"

    def clear_current(self, db: Session, batch_no: str) -> dict[str, Any]:
        """清空当前批次请求，不删除历史批次。"""
        count = CaptureRepository(db).clear_current_requests(batch_no)
        SettingsRepository(db).create_log("capture", "clear_current", "success", f"清空当前采集 {count} 条", batch_no)
        return {"cleared_count": count}

    def _dedupe_records_for_sync(self, records: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """单次同步内按方法、域名、路径去重，保留最新记录，抵御异常轮询请求风暴。"""
        latest_records: dict[tuple[str, str, str], dict[str, Any]] = {}
        for record in records:
            key = (record.get("method", ""), record.get("domain", ""), record.get("path", ""))
            existing = latest_records.get(key)
            if not existing or record.get("start_time", datetime.min) >= existing.get("start_time", datetime.min):
                latest_records[key] = record
        deduped = sorted(latest_records.values(), key=lambda item: item.get("start_time", datetime.min), reverse=True)
        return deduped[: self.MAX_RECORDS_PER_SYNC]

    def _batch_out(self, batch) -> CaptureBatchOut:
        """把数据库批次模型转换为接口出参。"""
        return CaptureBatchOut(
            batch_no=batch.batch_no,
            target_url=batch.target_url,
            status=batch.status,
            started_at=batch.started_at,
            ended_at=batch.ended_at,
            total_count=batch.total_count,
            api_count=batch.api_count,
        )

    def _request_list_out(self, request: CapturedRequest) -> CapturedRequestListOut:
        """把请求模型转换为列表出参，列表中不暴露敏感 Header 明文。"""
        return CapturedRequestListOut(
            id=request.id,
            request_id=request.request_id,
            batch_no=request.batch.batch_no,
            method=request.method,
            url=request.url,
            domain=request.domain,
            path=request.path,
            resource_type=request.resource_type,
            status_code=request.status_code,
            start_time=request.start_time,
            duration_ms=request.duration_ms,
            request_size=request.request_size,
            response_size=request.response_size,
            is_new=request.is_new,
            is_api=request.is_api,
            dynamic_marks=request.dynamic_marks,
        )

    def _request_detail_out(self, request: CapturedRequest) -> CapturedRequestDetailOut:
        """把请求模型转换为详情出参，详情页直接展示原始 Header、Cookie 和令牌。"""
        base = self._request_list_out(request).model_dump()
        return CapturedRequestDetailOut(
            **base,
            query_params=request.query_params,
            request_headers=request.request_headers,
            cookies=request.cookies,
            request_body=request.request_body,
            response_headers=request.response_headers,
            response_body=request.response_body,
            raw_curl=request.raw_curl,
            clean_curl=request.clean_curl,
            auth_tokens=self._auth_tokens_out(request),
        )

    def _auth_tokens_out(self, request: CapturedRequest) -> list[dict[str, Any]]:
        """提取请求中的鉴权令牌字段，供前端集中展示和检查。"""
        tokens: list[dict[str, Any]] = []
        self._collect_tokens(tokens, "Header", request.request_headers)
        self._collect_tokens(tokens, "Cookie", request.cookies)
        self._collect_tokens(tokens, "Query", request.query_params)
        if isinstance(request.request_body, dict):
            self._collect_tokens(tokens, "Body", request.request_body)
        return tokens

    def _collect_tokens(self, tokens: list[dict[str, Any]], source: str, data: dict[str, Any] | None) -> None:
        """从指定数据源中收集 Authorization、Token、Session、CSRF 等鉴权字段。"""
        for key, value in (data or {}).items():
            if not self._is_token_key(str(key)):
                continue
            tokens.append(
                {
                    "source": source,
                    "name": str(key),
                    "value": value,
                    "raw_length": len(str(value)) if value is not None else 0,
                },
            )

    def _is_token_key(self, key: str) -> bool:
        """判断字段名是否属于常见令牌或会话凭据。"""
        normalized = key.lower().replace("-", "_")
        token_words = ("authorization", "token", "session", "sid", "csrf", "xsrf", "jwt")
        return any(word in normalized for word in token_words)


capture_service = CaptureService()
