from __future__ import annotations

import json
import logging
import re
import shutil
import socket
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.common import InvalidSessionIdException, NoSuchWindowException, TimeoutException, WebDriverException
from selenium.webdriver.support.ui import WebDriverWait
from urllib3.exceptions import HTTPError as Urllib3HTTPError

from app.core.config import get_settings, resolve_resource_path, resolve_runtime_path
from app.core.exceptions import AppError
from app.services.browser_providers import get_provider
from app.services.browser_providers.base import BrowserProvider

logger = logging.getLogger(__name__)


class BrowserService:
    """浏览器控制服务：启动浏览器、访问目标网址并读取网络性能日志。"""

    DRIVER_QUIT_TIMEOUT_SECONDS = 5
    INITIAL_DOM_READY_TIMEOUT_SECONDS = 6
    KILL_PROFILE_PROCESSES_BEFORE_CREATE = False
    DISABLED_FEATURES = (
        "Translate",
        "AutomationControlled",
        "BackForwardCache",
    )

    def __init__(self) -> None:
        self.settings = get_settings()
        self.driver: webdriver.Remote | None = None
        self._provider: BrowserProvider = get_provider(self.settings.browser_type)
        self._network_enabled_handles: set[str] = set()
        self._debugger_port: int | None = None
        self._debugger_address: str | None = None
        self._attached_to_existing: bool = False

    def set_browser_type(self, browser_type: str) -> None:
        """运行时切换浏览器引擎，下一次启动采集时生效。"""
        if self._provider.browser_type == browser_type:
            return
        logger.info("Switching browser type from %s to %s", self._provider.browser_type, browser_type)
        self._discard_driver()
        self._provider = get_provider(browser_type)
        self.settings.browser_type = browser_type

    def start(self, url: str) -> None:
        """启动或复用浏览器访问目标网址。"""
        try:
            is_reusing_browser = self.driver is not None and self._is_session_alive()
            if not is_reusing_browser:
                self.driver = self._create_driver()
            self._enable_network_for_open_windows()
            self.clear_network_events()

            if self._attached_to_existing:
                self.driver.execute_cdp_cmd("Target.createTarget", {
                    "url": url,
                    "newWindow": False,
                })
                logger.info("已在现有浏览器中打开新标签页：%s", url)
                self._attached_to_existing = False
            else:
                if is_reusing_browser:
                    self._open_new_capture_tab()
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
        """停止当前采集控制，保留受控浏览器里的用户标签页。"""
        logger.info("采集控制已停止，受控浏览器保持打开")

    def close(self) -> None:
        """强制关闭受控浏览器，仅用于重置 profile 等明确需要销毁会话的场景。"""
        driver = self.driver
        profile_dir = self._provider.get_user_data_dir(self.settings)
        if driver is not None:
            self._quit_driver_safely(driver)
        self._terminate_profile_processes(profile_dir)
        self._discard_driver()
        logger.info("受控浏览器已关闭")

    def reset_profile(self) -> None:
        """清理内置浏览器登录态，用于目标站反复提示 token 无效时重新登录。"""
        self.close()
        profile_dir = self._provider.get_user_data_dir(self.settings)
        self._terminate_profile_processes(profile_dir)
        if profile_dir.exists():
            shutil.rmtree(profile_dir)
        logger.info("浏览器登录态目录已重置：%s", profile_dir)

    def clear_network_events(self) -> None:
        """开始新采集前清空旧 performance 日志，保证首屏采集只包含当前目标页。"""
        if self.driver is None:
            return
        try:
            self.driver.get_log("performance")
        except WebDriverException:
            logger.debug("清空旧网络日志失败，将在后续轮询中继续尝试读取。")

    def poll_network_events(self) -> list[dict[str, Any]]:
        """读取并解析 Chrome performance 日志，包含受控浏览器内已打开标签页的请求。"""
        if self.driver is None:
            raise AppError("浏览器尚未启动，请先启动浏览器后再采集请求。", "BROWSER_NOT_STARTED")
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
        """通过 CDP 读取响应体，读取失败时返回 None。

        Network.getResponseBody 是浏览器级方法，requestId 全局唯一，
        从任意标签页都能调用，不需要切换窗口。
        """
        if self.driver is None:
            return None
        _, raw_request_id = self._split_scoped_request_id(request_id)
        try:
            result = self.driver.execute_cdp_cmd("Network.getResponseBody", {"requestId": raw_request_id})
        except WebDriverException as exc:
            logger.debug("响应体读取失败，请求 ID：%s，原因：%s", request_id, exc)
            return None
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

    def _create_driver(self) -> webdriver.Remote:
        """创建开启 performance log 的浏览器，用于采集网络请求。

        优先尝试接管用户已打开的浏览器（需要该浏览器启动时带
        --remote-debugging-port 参数），这样可以在用户日常使用的
        浏览器里直接开新标签页采集，共享登录态和配置。
        """
        any_debugger = self._find_any_debugger_address()
        if any_debugger:
            try:
                logger.info("检测到已打开浏览器：%s，尝试接管...", any_debugger)
                driver = self._attach_to_existing_driver(any_debugger)
                self._attached_to_existing = True
                return driver
            except WebDriverException:
                logger.debug("接管已打开浏览器失败，将创建新浏览器。", exc_info=True)

        user_data_dir = self._provider.get_user_data_dir(self.settings)
        existing_debugger_address = self._find_existing_debugger_address(user_data_dir)
        if existing_debugger_address:
            try:
                return self._attach_to_existing_driver(existing_debugger_address)
            except WebDriverException:
                logger.debug("接管已打开的浏览器失败，将尝试创建新浏览器。", exc_info=True)

        options = self._provider.create_options()
        options.set_capability(self._provider.logging_prefs_key, {"performance": "ALL"})
        options.page_load_strategy = "none"
        options.add_argument("--remote-allow-origins=*")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
        options.add_argument("--lang=zh-CN")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-popup-blocking")
        options.add_argument("--disable-notifications")
        options.add_argument(f"--disable-features={','.join(self.DISABLED_FEATURES)}")
        options.add_argument("--disable-background-networking")
        options.add_argument("--disable-client-side-phishing-detection")
        options.add_argument("--disable-blink-features=AutomationControlled")
        if self.KILL_PROFILE_PROCESSES_BEFORE_CREATE:
            self._terminate_profile_processes(user_data_dir)
        user_data_dir.mkdir(parents=True, exist_ok=True)
        options.add_argument(f"--user-data-dir={user_data_dir}")
        options.add_argument("--profile-directory=Default")
        self._debugger_port = self._debugger_port or self._find_free_port()
        self._debugger_address = f"127.0.0.1:{self._debugger_port}"
        options.add_argument(f"--remote-debugging-port={self._debugger_port}")
        options.add_argument("--remote-debugging-address=127.0.0.1")
        options.add_argument(f"--window-size={self.settings.browser_window_width},{self.settings.browser_window_height}")
        if self.settings.browser_headless:
            options.add_argument("--headless=new")
        binary = self._provider.get_binary_location(self.settings)
        if binary:
            options.binary_location = binary
        options.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True, "enablePage": True})
        self._provider.apply_lifecycle_options(options)
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)
        options.add_experimental_option(
            "prefs",
            {
                "credentials_enable_service": False,
                "profile.password_manager_enabled": False,
                "intl.accept_languages": "zh-CN,zh",
            },
        )

        driver_path = self._resolve_driver_path()
        if not driver_path:
            name = self._provider.browser_display_name
            raise AppError(
                f"未找到{name}的浏览器驱动，请确认驱动文件已随软件一起发布。",
                "BUNDLED_DRIVER_NOT_FOUND",
                500,
            )
        service = self._provider.create_service(driver_path)
        try:
            driver = self._provider.create_driver(service, options)
        except WebDriverException:
            if not self.KILL_PROFILE_PROCESSES_BEFORE_CREATE:
                raise
            self._terminate_profile_processes(user_data_dir)
            driver = self._provider.create_driver(service, options)
        driver.set_page_load_timeout(self.settings.browser_page_load_timeout)
        driver.set_script_timeout(self.settings.browser_script_timeout)
        driver.execute_cdp_cmd(
            "Page.addScriptToEvaluateOnNewDocument",
            {
                "source": self._page_lifecycle_script(),
            },
        )
        driver.execute_cdp_cmd("Network.enable", {})
        self._network_enabled_handles = {driver.current_window_handle}
        return driver

    def _attach_to_existing_driver(self, debugger_address: str) -> webdriver.Remote:
        """接管仍在运行的受控浏览器，避免因 profile 占用而关闭用户手动标签页。"""
        options = self._provider.create_options()
        options.add_experimental_option("debuggerAddress", debugger_address)
        options.add_experimental_option("perfLoggingPrefs", {"enableNetwork": True, "enablePage": True})
        driver_path = self._resolve_driver_path()
        if not driver_path:
            name = self._provider.browser_display_name
            raise AppError(
                f"未找到{name}的浏览器驱动，请确认驱动文件已随软件一起发布。",
                "BUNDLED_DRIVER_NOT_FOUND",
                500,
            )
        driver = self._provider.create_driver(self._provider.create_service(driver_path), options)
        driver.set_page_load_timeout(self.settings.browser_page_load_timeout)
        driver.set_script_timeout(self.settings.browser_script_timeout)
        self._debugger_address = debugger_address
        self._debugger_port = int(debugger_address.rsplit(":", 1)[1])

        handles = driver.window_handles
        if len(handles) > 1:
            try:
                driver.close()
            except WebDriverException:
                pass
            remaining = driver.window_handles
            if remaining:
                driver.switch_to.window(remaining[0])

        try:
            driver.execute_cdp_cmd("Page.addScriptToEvaluateOnNewDocument", {"source": self._page_lifecycle_script()})
            driver.execute_cdp_cmd("Network.enable", {})
            self._network_enabled_handles = {driver.current_window_handle}
        except WebDriverException:
            self._network_enabled_handles = set()
        return driver

    def _find_existing_debugger_address(self, profile_dir: Path) -> str | None:
        """查找仍在运行的受控浏览器调试端口，便于重启桌面端后无损接回。"""
        if sys.platform != "win32":
            return None
        process_name = self._provider.browser_process_name
        script = r"""
param([string]$ProfileDir, [string]$ProcessName)
$escaped = [WildcardPattern]::Escape($ProfileDir)
Get-CimInstance Win32_Process |
  Where-Object {
    $_.Name -eq $ProcessName -and
    $_.CommandLine -like "*$escaped*" -and
    $_.CommandLine -like "*--remote-debugging-port*"
  } |
  Select-Object -First 1 -ExpandProperty CommandLine
"""
        try:
            result = subprocess.run(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", script,
                 "-ProfileDir", str(profile_dir), "-ProcessName", process_name],
                check=False,
                capture_output=True,
                text=True,
                timeout=5,
            )
        except Exception:
            logger.debug("查找已打开受控浏览器调试端口失败。", exc_info=True)
            return None
        return self._debugger_address_from_command_line(result.stdout)

    def _find_any_debugger_address(self) -> str | None:
        """查找任意已打开的(带 --remote-debugging-port 的)浏览器，不限定 profile 目录。

        尝试标准 Chromium 调试端口，直接通过 HTTP 探测 CDP 端点，
        比 PowerShell 进程扫描更可靠。
        """
        import urllib.request

        candidate_ports = [9222, 9223, 9224, 9225]
        for port in candidate_ports:
            url = f"http://127.0.0.1:{port}/json/version"
            try:
                req = urllib.request.Request(url)
                with urllib.request.urlopen(req, timeout=1.5) as resp:
                    data = json.loads(resp.read().decode("utf-8"))
                    browser = data.get("Browser", "")
                    logger.info("检测到已打开浏览器：%s，端口：%s", browser, port)
                    return f"127.0.0.1:{port}"
            except (OSError, ValueError, json.JSONDecodeError):
                continue
        return None

    @staticmethod
    def _debugger_address_from_command_line(command_line: str) -> str | None:
        match = re.search(r"--remote-debugging-port(?:=|\s+)(\d+)", command_line or "")
        if not match:
            return None
        return f"127.0.0.1:{match.group(1)}"

    def _terminate_profile_processes(self, profile_dir: Path) -> None:
        """只结束占用本工具浏览器用户目录的残留进程，不影响用户日常浏览器。"""
        if sys.platform != "win32":
            return
        profile_text = str(profile_dir)
        process_names = f"@('{self._provider.browser_process_name}', '{self._provider.driver_process_name}')"
        script = r"""
param([string]$ProfileDir)
$escaped = [WildcardPattern]::Escape($ProfileDir)
"""
        script += f"$all = Get-CimInstance Win32_Process | Where-Object {{ $_.Name -in {process_names} }}\n"
        script += r"""
$browsers = $all | Where-Object { $_.CommandLine -like "*$escaped*" }
$parentIds = @($browsers | ForEach-Object { $_.ParentProcessId }) | Where-Object { $_ }
$targets = @($browsers.ProcessId)
"""
        script += f"$driverName = '{self._provider.driver_process_name}'\n"
        script += r"""
$targets += @($all | Where-Object { $_.Name -eq $driverName -and $parentIds -contains $_.ProcessId } | ForEach-Object { $_.ProcessId })
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
            logger.debug("清理本工具浏览器残留进程失败。", exc_info=True)

    def _quit_driver_safely(self, driver: webdriver.Remote) -> None:
        """给 driver.quit 增加超时兜底，避免目标页卡死时停止接口被 Selenium 长时间阻塞。"""
        error_holder: list[Exception] = []

        def quit_driver() -> None:
            try:
                driver.quit()
            except Exception as exc:
                error_holder.append(exc)

        thread = threading.Thread(target=quit_driver, name="browser-driver-quit", daemon=True)
        thread.start()
        thread.join(timeout=self.DRIVER_QUIT_TIMEOUT_SECONDS)
        if thread.is_alive():
            logger.warning("浏览器正常关闭超过 %s 秒，改用进程清理兜底。", self.DRIVER_QUIT_TIMEOUT_SECONDS)
            return
        if error_holder:
            logger.debug("浏览器关闭时出现异常，将继续执行进程清理：%s", error_holder[0])

    def _open_target_url(self, url: str) -> None:
        """发起页面导航，不等待目标站完整加载，避免慢页面卡住启动接口。"""
        if self.driver is None:
            return
        try:
            self.driver.get(url)
        except TimeoutException:
            if not self._is_session_alive():
                raise
            logger.warning(
                "目标页面加载超过 %s 秒，已保留浏览器并继续采集：%s",
                self.settings.browser_page_load_timeout,
                url,
            )
            try:
                self.driver.execute_script("window.stop();")
            except WebDriverException:
                logger.debug("页面加载超时后执行 window.stop 失败。", exc_info=True)
        except WebDriverException:
            if not self._is_session_alive():
                raise
            logger.debug("WebDriver 导航失败，尝试 CDP Page.navigate：%s", url, exc_info=True)
            self.driver.execute_cdp_cmd("Page.enable", {})
            self.driver.execute_cdp_cmd("Page.navigate", {"url": url})
        finally:
            self._wait_for_interactive_dom()

    def _open_new_capture_tab(self) -> None:
        """Open a fresh tab for a new capture run so the user's current page stays intact."""
        if self.driver is None:
            return
        try:
            self.driver.switch_to.new_window("tab")
            return
        except WebDriverException:
            logger.debug("new_window 失败，改用 CDP Target.createTarget。", exc_info=True)
        try:
            handles_before = set(self.driver.window_handles)
            self.driver.execute_cdp_cmd("Target.createTarget", {
                "url": "about:blank",
                "newWindow": False,
            })
            time.sleep(0.5)
            handles_after = self.driver.window_handles
            new_handles = [h for h in handles_after if h not in handles_before]
            if new_handles:
                self.driver.switch_to.window(new_handles[-1])
            else:
                logger.debug("CDP 新建标签页未找到对应 handle，将复用当前标签页。")
        except WebDriverException:
            logger.debug("CDP 新建标签页失败，将复用当前标签页。", exc_info=True)

    def _wait_for_interactive_dom(self) -> None:
        """Initial navigation only needs a usable DOM; SPA content may continue loading after this."""
        if self.driver is None:
            return
        try:
            WebDriverWait(self.driver, self.INITIAL_DOM_READY_TIMEOUT_SECONDS).until(
                lambda driver: (
                    driver.execute_script("return document.readyState") in ("interactive", "complete")
                    and driver.execute_script("return document.body && document.body.children.length > 0")
                )
            )
        except (TimeoutException, WebDriverException):
            logger.debug("等待初始 DOM 可交互超时，继续保留浏览器供用户手动操作。", exc_info=True)

    def _page_lifecycle_script(self) -> str:
        """Keep SPA pages interactive when Chrome restores them from history cache."""
        return """
Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined
});
Object.defineProperty(navigator, 'languages', {
  get: () => ['zh-CN', 'zh']
});
Object.defineProperty(navigator, 'plugins', {
  get: () => [1, 2, 3, 4, 5]
});
window.addEventListener('pageshow', (event) => {
  if (event.persisted) {
    window.location.reload();
  }
});
"""

    def _find_free_port(self) -> int:
        """获取本机空闲端口，供 remote debugging 使用。"""
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
        """只使用项目内置或显式配置的浏览器驱动，避免公用版依赖用户本机缓存。"""
        driver_path_setting = self._provider.get_driver_path(self.settings)
        if not driver_path_setting:
            return None
        driver_path = Path(driver_path_setting)
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
        except (WebDriverException, Urllib3HTTPError, OSError):
            self._discard_driver()
            return False

    def _discard_driver(self) -> None:
        """丢弃当前 driver 引用，避免继续复用已失效的浏览器会话。"""
        self.driver = None
        self._network_enabled_handles.clear()
        self._debugger_port = None
        self._debugger_address = None
        self._attached_to_existing = False


browser_service = BrowserService()
