from datetime import datetime
from types import SimpleNamespace

import pytest

from app.core.exceptions import AppError
from app.services.batch_export_service import BatchExportService
from app.services.capture_service import CaptureService
from app.services.curl_service import CurlService
from app.services.dynamic_param_service import DynamicParamService
from app.services.request_parser import RequestParser
from app.utils.url_tools import normalize_url


def test_clean_curl_removes_browser_headers():
    """精简 cURL 应移除浏览器无关请求头，同时保留业务必要 Header。"""
    service = CurlService()
    curl = service.build_curl(
        "POST",
        "https://example.com/api/list",
        {
            "Content-Type": "application/json",
            "User-Agent": "Chrome",
            "Sec-Fetch-Site": "same-origin",
            "X-Tenant-Id": "tenant-1",
        },
        {"session": "abc"},
        {"page": 1},
    )
    assert "User-Agent" not in curl
    assert "Sec-Fetch-Site" not in curl
    assert "Content-Type: application/json" in curl
    assert "X-Tenant-Id: tenant-1" in curl
    assert "session=abc" in curl


def test_dynamic_param_marks_common_fields():
    """动态参数识别应能标记 token、时间戳、分页和业务 ID。"""
    marks = DynamicParamService().mark_params(
        {
            "access_token": "token-value",
            "timestamp": "1779242737",
            "page": 1,
            "project_id": 1001,
        },
    )
    mark_types = {item["type"] for item in marks}
    assert {"auth", "dynamic", "pagination", "business_id"}.issubset(mark_types)


def test_normalize_url_adds_scheme_and_rejects_empty():
    """URL 规范化应补全 https 协议，并对空网址给出业务异常。"""
    assert normalize_url("example.com") == "https://example.com"
    with pytest.raises(AppError):
        normalize_url("")


def test_request_parser_merges_cookie_from_extra_info():
    """Chrome ExtraInfo 事件里的 Cookie 应合并进请求记录，避免 Cookie 页签为空。"""
    records = RequestParser().parse_performance_events(
        [
            {
                "method": "Network.requestWillBeSent",
                "params": {
                    "requestId": "1",
                    "wallTime": 1779242737,
                    "type": "Fetch",
                    "request": {
                        "url": "https://example.com/api/user",
                        "method": "GET",
                        "headers": {},
                    },
                },
            },
            {
                "method": "Network.requestWillBeSentExtraInfo",
                "params": {
                    "requestId": "1",
                    "headers": {
                        "Cookie": "sid=abc123; access_token=token456",
                        "Authorization": "Bearer token456",
                    },
                    "associatedCookies": [
                        {"cookie": {"name": "csrf_token", "value": "csrf789"}},
                    ],
                },
            },
        ],
    )
    assert records[0]["cookies"] == {
        "sid": "abc123",
        "access_token": "token456",
        "csrf_token": "csrf789",
    }
    assert records[0]["request_headers"]["Authorization"] == "Bearer token456"


def test_sync_records_keep_latest_by_method_domain_path():
    """单次同步遇到同一路径轮询时应只保留最新记录，避免请求风暴拖慢系统。"""
    service = CaptureService()
    records = [
        {
            "method": "GET",
            "domain": "example.com",
            "path": "/api/user",
            "start_time": datetime(2026, 5, 21, 10, 0, 0),
            "request_id": "old",
        },
        {
            "method": "GET",
            "domain": "example.com",
            "path": "/api/user",
            "start_time": datetime(2026, 5, 21, 10, 0, 2),
            "request_id": "new",
        },
        {
            "method": "POST",
            "domain": "example.com",
            "path": "/api/user",
            "start_time": datetime(2026, 5, 21, 10, 0, 1),
            "request_id": "post",
        },
    ]

    deduped = service._dedupe_records_for_sync(records)

    assert [item["request_id"] for item in deduped] == ["new", "post"]


def test_batch_export_service_supports_all_formats():
    """批量导出服务应支持 OpenAPI、Postman、cURL 和 Apifox 四种文件格式。"""
    request = SimpleNamespace(
        id=1,
        request_id="browser|1",
        batch=SimpleNamespace(batch_no="20260521123000"),
        method="POST",
        url="https://example.com/api/user?page=1",
        domain="example.com",
        path="/api/user",
        query_params={"page": "1"},
        request_headers={"Content-Type": "application/json", "X-Tenant-Id": "tenant-1"},
        cookies={"sid": "abc"},
        request_body={"name": "测试"},
        response_headers={"Content-Type": "application/json"},
        response_body={"ok": True},
        status_code=200,
        clean_curl="curl 'https://example.com/api/user'",
        raw_curl=None,
    )
    service = BatchExportService()

    openapi = service.build_payload([request], "openapi")
    postman = service.build_payload([request], "postman")
    curl = service.build_payload([request], "curl")
    apifox = service.build_payload([request], "apifox")

    assert openapi["data"]["openapi"] == "3.0.3"
    assert "/api/user" in openapi["data"]["paths"]
    assert postman["data"]["info"]["schema"].endswith("collection/v2.1.0/collection.json")
    assert "curl 'https://example.com/api/user'" in curl["data"]
    assert apifox["data"]["apifoxProject"] == "1.0.0"
    assert apifox["data"]["apiCollection"][0]["items"][0]["api"]["path"] == "/api/user"


def test_request_ids_summary_keeps_operation_log_short():
    """批量导出日志中的请求摘要应保持较短，避免 operation_logs.request_id 字段过长。"""
    requests = [
        SimpleNamespace(request_id=f"session-{index}|" + "x" * 120)
        for index in range(20)
    ]

    summary = CaptureService()._request_ids_summary(requests)

    assert len(summary) <= 128
    assert "共20条" in summary
