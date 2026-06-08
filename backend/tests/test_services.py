from datetime import datetime
from types import SimpleNamespace

import pytest
from selenium.common import WebDriverException

from app.core.exceptions import AppError
from app.services import browser_service as browser_service_module
from app.services.batch_export_service import BatchExportService
from app.services.browser_service import BrowserService
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


def test_browser_service_disables_bfcache_for_spa_back_navigation():
    service = BrowserService()

    assert "BackForwardCache" in service.CHROME_DISABLED_FEATURES
    lifecycle_script = service._page_lifecycle_script()
    assert "pageshow" in lifecycle_script
    assert "event.persisted" in lifecycle_script
    assert "window.location.reload()" in lifecycle_script


def test_browser_service_opens_new_tab_when_reusing_existing_browser():
    service = BrowserService()
    calls = []

    class FakeSwitchTo:
        def new_window(self, window_type):
            calls.append(("new_window", window_type))

    class FakeDriver:
        current_url = "https://leetcode.cn/studyplan/top-100-liked/"
        window_handles = ["existing"]
        switch_to = FakeSwitchTo()

        def get(self, url):
            calls.append(("get", url))

        def get_log(self, log_type):
            return []

        def execute_script(self, script):
            if "document.readyState" in script:
                return "complete"
            if "document.body" in script:
                return 1
            return None

    service.driver = FakeDriver()
    service._enable_network_for_open_windows = lambda: calls.append(("enable_windows", None))

    service.start("https://example.com")

    assert ("new_window", "tab") in calls
    assert ("get", "https://example.com") in calls


def test_browser_service_does_not_kill_profile_before_normal_driver_create():
    service = BrowserService()

    assert service.KILL_PROFILE_PROCESSES_BEFORE_CREATE is False


def test_browser_service_does_not_kill_profile_after_driver_create_failure_by_default(tmp_path, monkeypatch):
    service = BrowserService()
    calls = []

    def fail_to_create_driver(*args, **kwargs):
        raise WebDriverException("profile is already in use")

    service.settings.browser_user_data_dir = tmp_path / "chrome-profile"
    service._resolve_driver_path = lambda: str(tmp_path / "chromedriver.exe")
    service._find_existing_debugger_address = lambda profile_dir: None
    service._find_free_port = lambda: 9222
    service._terminate_profile_processes = lambda profile_dir: calls.append("kill_profile")
    monkeypatch.setattr(browser_service_module.webdriver, "Chrome", fail_to_create_driver)

    with pytest.raises(WebDriverException):
        service._create_chrome_driver()

    assert calls == []


def test_browser_service_stop_preserves_controlled_chrome_tabs():
    service = BrowserService()
    calls = []
    driver = object()

    service.driver = driver
    service._quit_driver_safely = lambda driver: calls.append("quit")
    service._terminate_profile_processes = lambda profile_dir: calls.append("kill_profile")

    service.stop()

    assert calls == []
    assert service.driver is driver


def test_browser_service_parses_existing_debugger_port_from_command_line():
    command_line = (
        '"C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" '
        '--user-data-dir="D:\\Code\\NetworkCaptureTool\\runtime\\chrome-profile" '
        "--remote-debugging-port=52956"
    )

    assert BrowserService._debugger_address_from_command_line(command_line) == "127.0.0.1:52956"


def test_browser_service_detaches_chrome_from_driver_lifecycle():
    service = BrowserService()

    class FakeOptions:
        def __init__(self):
            self.experimental_options = {}

        def add_experimental_option(self, name, value):
            self.experimental_options[name] = value

    options = FakeOptions()

    service._apply_chrome_lifecycle_options(options)

    assert options.experimental_options["detach"] is True


def test_browser_service_reset_profile_closes_controlled_chrome_before_delete(tmp_path):
    service = BrowserService()
    calls = []
    profile_dir = tmp_path / "chrome-profile"
    profile_dir.mkdir()
    (profile_dir / "Preferences").write_text("{}", encoding="utf-8")

    service.settings.browser_user_data_dir = profile_dir
    service.driver = object()
    service._quit_driver_safely = lambda driver: calls.append("quit")
    service._terminate_profile_processes = lambda profile: calls.append(("kill_profile", profile))

    service.reset_profile()

    assert "quit" in calls
    assert ("kill_profile", profile_dir) in calls
    assert not profile_dir.exists()
