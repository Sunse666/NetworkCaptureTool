from __future__ import annotations

import json
import logging
import shutil
import socket
import subprocess
import sys
import threading
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common import InvalidSessionIdException, NoSuchWindowException, TimeoutException, WebDriverException
from selenium.webdriver.chrome.service import Service as ChromeService

from app.core.config import get_settings, resolve_resource_path, resolve_runtime_path
from app.core.exceptions import AppError
from app.services.cdp_network_listener import CdpNetworkListener

logger = logging.getLogger(__name__)


class BrowserService:
    """浏览器控制服务：启动浏览器、访问目标网址并读取网络性能日志。"""

    DRIVER_QUIT_TIMEOUT_SECONDS = 5
    USE_PERFORMANCE_LOG_FALLBACK = False

    def __init__(self) -> None:
        self.settings = get_settings()
        self.driver: webdriver.Chrome | None = None
        self._network_enabled_handles: set[str] = set()
        self._debugger_port: int | None = None
        self._debugger_address: str | None = None
        self._cdp_listener = CdpNetworkListener()

    def start(self, url: str) -> None:
        """启动或复用浏览器访问目标网址。"""
        try:
            if self.driver is None or not self._is_session_alive():
                self.driver = self._create_chrome_driver()
            self._start_cdp_listener()
            self._enable_network_for_open_windows()
            self.clear_network_events()
            self._open_target_url(url)
            logger.info("浏览器已访问目标网站：%s", url)
        except (InvalidSessionIdException, NoSuchWindowException) as exc:
            logger.warning("启动采集过程中浏览器窗口被关闭：%s", exc)
            self._discard_driver()
            raise AppError("启动过程中检测到浏览器窗口已关闭，本次采集已取消；需要采集时请重新点击启动浏览器。", "BROWSER_WINDOW_CLOSED", 400) from exc
        except WebDriverException as exc:
            logger.exception("浏览器启动或访问失败：%s", exc)
            self._discard_driver()
            raise AppError("浏览器启动或访问网站失败，请检查浏览器驱动、端口占用或目标网站是否可访问。", "BROWSER_START_FAILED", 500) from exc

    def stop(self) -> None:
        """关闭当前浏览器实例，避免残留过多浏览器进程。"""
        driver = self.driver
        profile_dir = self.settings.browser_user_data_dir.resolve()
        if driver is not None:
            self._quit_driver_safely(driver)
        self._cdp_listener.stop()
        self._terminate_profile_processes(profile_dir)
        self._discard_driver()
        logger.info("浏览器已关闭")

    def reset_profile(self) -> None:
        """清理内置浏览器登录态，用于目标站反复提示 token 无效时重新登录。"""
        self.stop()
        profile_dir = self.settings.browser_user_data_dir.resolve()
        self._terminate_profile_processes(profile_dir)
        if profile_dir.exists():
            shutil.rmtree(profile_dir)
        logger.info("浏览器登录态目录已重置：%s", profile_dir)

    def clear_network_events(self) -> None:
        """开始新采集前清空旧 performance 日志，保证首屏采集只包含当前目标页。"""
        if self.driver is None:
            return
        self._cdp_listener.clear_events()
        if not self.USE_PERFORMANCE_LOG_FALLBACK:
            return
        try:
            self.driver.get_log("performance")
        except WebDriverException:
            logger.debug("清空旧网络日志失败，将在后续轮询中继续尝试读取。")

    def poll_network_events(self) -> list[dict[str, Any]]:
        """读取并解析 Chrome performance 日志，包含受控浏览器内已打开标签页的请求。"""
        if self.driver is None:
            raise AppError("浏览器尚未启动，请先启动浏览器后再采集请求。", "BROWSER_NOT_STARTED")
        cdp_events = self._cdp_listener.poll_events()
        if cdp_events or not self.USE_PERFORMANCE_LOG_FALLBACK:
            return cdp_events
        # 只有回退到 Selenium performance log 时才扫描标签页；常规 CDP 监听已自动附着多标签页，频繁扫描会明显拖慢浏览器。
        self._enable_network_for_open_windows()
        try:
            logs = self.driver.get_log("performance")
        except WebDriverException as exc:
            raise AppError("读取网络请求日志失败，可尝试重新启动浏览器。", "NETWORK_LOG_READ_FAILED", 500) from exc
        events: list[dict[str, Any]] = []
        for item in logs:
            try:
                events.append(json.loads(item["message"]))
            except (KeyError, ValueError):
                continue
        return events

    def get_response_body(self, request_id: str) -> Any:
        """通过 CDP 读取响应体，读取失败时返回 None，避免影响请求主流程入库。"""
        if self.driver is None:
            return None
        cdp_body = self._cdp_listener.get_response_body(request_id)
        if cdp_body is not None:
            if cdp_body.get("base64Encoded"):
                body = cdp_body.get("body", "")
                return {
                    "__hidden_payload__": True,
                    "reason": "响应体为二进制或压缩内容，已隐藏原文。",
                    "size": len(body),
                }
            return cdp_body.get("body")
        webview, raw_request_id = self._split_scoped_request_id(request_id)
        original_handle = self._safe_current_window_handle()
        try:
            target_handle = self._find_handle_by_webview(webview) if webview else None
            if target_handle:
                self.driver.switch_to.window(target_handle)
            result = self.driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": raw_request_id})
        except WebDriverException as exc:
            logger.debug("响应体读取失败，请求 ID：%s，原因：%s", request_id, exc)
            return None
        finally:
            self._restore_window_handle(original_handle)
        body = result.get("body")
        if body in (None, ""):
            return None
        if result.get("base64Encoded"):
            return {
                "__hidden_payload__": True,
                "reason": "响应体为二进制或压缩内容，已隐藏原文。",
                "size": len(body),
            }
        return body

    def _create_chrome_driver(self) -> webdriver.Chrome:
        """创建开启 performance log 的 Chrome，用于采集网络请求。"""
        options = webdriver.ChromeOptions()
        if self.USE_PERFORMANCE_LOG_FALLBACK:
            options.set_capability("goog:loggingPrefs", {"performance": "ALL"})
        # 抓包工具只需要把页面导航发出去，不应等待所有资源加载完成后才返回启动结果。
        options.page_load_strategy = "none"
        options.add_argument("--remote-allow-origins=*")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        # 某些站点会用 navigator.webdriver 识别自动化浏览器并切换到特殊登录链路；这里隐藏该标记，避免目标站误触发异常 token 流程。
        options.add_argument("--disable-blink-features=AutomationControlled")
        user_data_dir = resolve_runtime_path(self.settings.browser_user_data_dir)
        self._terminate_profile_processes(user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)
        # 使用独立 Chrome 用户目录保存登录态，避免每次启动都是全新匿名浏览器导致目标站提示 token 无效。
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument("--profile-directory=Default")
        self._debugger_port = self._debugger_port or self._find_free_port()
        self._debugger_address = f"127.0.0.1:{self._debugger_port}"
        options.add_argument(f"--remote-debugging-port={self._debugger_port}")
        options.add_argument("--remote-debugging-address=127.0.0.1")
        options.add_argument(f"--window-size={self.settings.browser_window_width},{self.settings.browser_window_height}")
        if self.settings.browser_headless:
            options.add_argument("--headless=new")
        if self.settings.chrome_binary:
            options.binary_location = self.settings.chrome_binary
        if self.USE_PERFORMANCE_LOG_FALLBACK:
            options.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True, "enablePage": True})
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        driver_path = self._resolve_driver_path()
        if not driver_path:
            raise AppError(
                "未找到项目内置 chromedriver，请确认 runtime/drivers/chromedriver.exe 已随软件一起发布。",
                "BUNDLED_DRIVER_NOT_FOUND",
                500,
            )
        service = ChromeService(executable_path=driver_path)
        try:
            driver = webdriver.Chrome(service=service, options=options)
        except WebDriverException:
            # Chrome 用户目录被残留进程占用时会启动崩溃，清理本工具进程后给调用方重试一次。
            self._terminate_profile_processes(user_data_dir)
            driver = webdriver.Chrome(service=service, options=options)
        # 给页面加载设置明确上限，用户在启动中关闭窗口或页面长期加载时不会无限等待。
        driver.set_page_load_timeout(self.settings.browser_page_load_timeout)
        driver.set_script_timeout(self.settings.browser_script_timeout)
        # 在页面脚本执行前覆写 webdriver 标记，配合 Chrome 参数覆盖更多版本差异。
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": """
Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined
});
""",
            },
        )
        # 开启 Network 域后，后续才能通过 Network.getResponseBody 读取响应体。
        driver.execute_cdp_cmd("Network.enable", {})
        self._network_enabled_handles = {driver.current_window_handle}
        return driver

    def _terminate_profile_processes(self, profile_dir: Path) -> None:
        """只结束占用本工具 Chrome 用户目录的残留进程，不影响用户日常浏览器。"""
        if sys.platform != "win32":
            return
        profile_text = str(profile_dir)
        script = r"""
param([string]$ProfileDir)
$escaped = [WildcardPattern]::Escape($ProfileDir)
$all = Get-CimInstance Win32_Process | Where-Object { $_.Name -in @('chrome.exe', 'chromedriver.exe') }
$chrome = $all | Where-Object { $_.CommandLine -like "*$escaped*" }
$parentIds = @($chrome | ForEach-Object { $_.ParentProcessId }) | Where-Object { $_ }
$targets = @($chrome.ProcessId)
$targets += @($all | Where-Object { $_.Name -eq 'chromedriver.exe' -and $parentIds -contains $_.ProcessId } | ForEach-Object { $_.ProcessId })
$targets | Sort-Object -Unique | ForEach-Object {
  try { Stop-Process -Id $_ -Force -ErrorAction Stop } catch {}
}
"""
        try:
            subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script, "-ProfileDir", profile_text],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            logger.debug("清理本工具 Chrome 残留进程失败。", exc_info=True)

    def _quit_driver_safely(self, driver: webdriver.Chrome) -> None:
        """给 driver.quit 增加超时兜底，避免目标页卡死时停止接口被 Selenium 长时间阻塞。"""
        error_holder: list[Exception] = []

        def quit_driver() -> None:
            try:
                driver.quit()
            except Exception as exc:
                error_holder.append(exc)

        thread = threading.Thread(target=quit_driver, name="chrome-driver-quit", daemon=True)
        thread.start()
        thread.join(timeout=self.DRIVER_QUIT_TIMEOUT_SECONDS)
        if thread.is_alive():
            logger.warning("浏览器正常关闭超过 %s 秒，改用进程清理兜底。", self.DRIVER_QUIT_TIMEOUT_SECONDS)
            return
        if error_holder:
            logger.debug("浏览器关闭时出现异常，将继续执行进程清理：%s", error_holder[0])

    def _open_target_url(self, url: str) -> None:
        """通过 CDP 发起页面导航，不等待目标站完整加载，避免慢页面卡住启动接口。"""
        if self.driver is None:
            return
        try:
            self.driver.execute_cdp_cmd("Page.enable", {})
            self.driver.execute_cdp_cmd("Page.navigate", {"url": url})
        except TimeoutException:
            if not self._is_session_alive():
                raise
            logger.warning(
                "目标页面加载超过 %s 秒，已保留浏览器并继续采集：%s",
                self.settings.browser_page_load_timeout,
                url,
            )

    def _start_cdp_listener(self) -> None:
        """启动浏览器级 CDP 监听器，用于捕获用户后续新开标签页的请求。"""
        if self._cdp_listener.is_running:
            return
        self._cdp_listener.start(self._debugger_address)

    def _find_free_port(self) -> int:
        """获取本机空闲端口，供 Chrome remote debugging 使用。"""
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
            server.bind(("127.0.0.1", 0))
            return int(server.getsockname()[1])

    def _enable_network_for_open_windows(self) -> None:
        """为受控浏览器中新开的标签页补充开启 Network 域，便于后续读取请求和响应体。"""
        if self.driver is None:
            return
        try:
            handles = self.driver.window_handles
        except WebDriverException:
            return
        new_handles = [handle for handle in handles if handle not in self._network_enabled_handles]
        if not new_handles:
            return
        original_handle = self._safe_current_window_handle()
        for handle in new_handles:
            try:
                self.driver.switch_to.window(handle)
                self.driver.execute_cdp_cmd("Network.enable", {})
                self._network_enabled_handles.add(handle)
            except WebDriverException as exc:
                logger.debug("为新标签页开启 Network 采集失败，标签页：%s，原因：%s", handle, exc)
        self._restore_window_handle(original_handle)

    def _split_scoped_request_id(self, request_id: str) -> tuple[str | None, str]:
        """拆分带标签页上下文的请求 ID，兼容历史未带上下文的老数据。"""
        if "|" not in request_id:
            return None, request_id
        webview, raw_request_id = request_id.rsplit("|", 1)
        return webview or None, raw_request_id

    def _find_handle_by_webview(self, webview: str | None) -> str | None:
        """把 performance log 中的 webview 标识映射回 Selenium window handle。"""
        if self.driver is None or not webview:
            return None
        try:
            handles = self.driver.window_handles
        except WebDriverException:
            return None
        normalized_webview = webview.replace("CDwindow-", "")
        for handle in handles:
            normalized_handle = handle.replace("CDwindow-", "")
            if webview == handle or normalized_webview == normalized_handle:
                return handle
        return None

    def _safe_current_window_handle(self) -> str | None:
        """安全读取当前标签页句柄，标签页被用户关闭时不抛出到业务层。"""
        if self.driver is None:
            return None
        try:
            return self.driver.current_window_handle
        except WebDriverException:
            return None

    def _restore_window_handle(self, handle: str | None) -> None:
        """执行标签页级 CDP 操作后尽量切回用户原来所在的标签页。"""
        if self.driver is None or not handle:
            return
        try:
            if handle in self.driver.window_handles:
                self.driver.switch_to.window(handle)
        except WebDriverException:
            logger.debug("恢复原标签页失败，可能标签页已被用户关闭。")

    def _resolve_driver_path(self) -> str | None:
        """只使用项目内置或显式配置的 chromedriver，避免公用版依赖用户本机缓存。"""
        if not self.settings.chromedriver_path:
            return None
        driver_path = Path(self.settings.chromedriver_path)
        if not driver_path.is_absolute():
            driver_path = resolve_resource_path(driver_path)
        if driver_path.is_file():
            return str(driver_path)
        return None

    def _is_session_alive(self) -> bool:
        """检查浏览器会话是否仍有效，用户手动关闭浏览器后会自动触发重建。"""
        if self.driver is None:
            return False
        try:
            _ = self.driver.current_url
            return True
        except WebDriverException:
            self._discard_driver()
            return False

    def _discard_driver(self) -> None:
        """丢弃当前 driver 引用，避免继续复用已失效的浏览器会话。"""
        self.driver = None
        self._network_enabled_handles.clear()
        self._debugger_port = None
        self._debugger_address = None


browser_service = BrowserService()
