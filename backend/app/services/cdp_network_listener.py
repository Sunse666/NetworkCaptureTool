import json
import logging
import threading
import urllib.request
from collections import deque
from typing import Any

import websocket

logger = logging.getLogger(__name__)


class CdpNetworkListener:
    """Chrome DevTools Protocol 网络监听器：监听受控浏览器内所有标签页的网络事件。"""

    TRACKED_RESOURCE_TYPES = {"XHR", "Fetch"}
    CAPTURED_NETWORK_METHODS = {
        "Network.requestWillBeSent",
        "Network.requestWillBeSentExtraInfo",
        "Network.responseReceived",
        "Network.loadingFinished",
        "Network.loadingFailed",
    }
    TARGET_METHODS = {
        "Target.attachedToTarget",
        "Target.detachedFromTarget",
        "Target.targetCreated",
    }
    INTERESTING_METHODS = CAPTURED_NETWORK_METHODS | TARGET_METHODS
    MAX_BUFFERED_EVENTS = 5000
    MAX_PENDING_EXTRA_EVENTS = 1000
    WEBDRIVER_STEALTH_SCRIPT = """
Object.defineProperty(navigator, 'webdriver', {
  get: () => undefined
});
"""
    NETWORK_ENABLE_PARAMS = {
        "maxTotalBufferSize": 4 * 1024 * 1024,
        "maxResourceBufferSize": 512 * 1024,
        "maxPostDataSize": 1024 * 1024,
    }

    def __init__(self) -> None:
        self._ws: websocket.WebSocketApp | None = None
        self._thread: threading.Thread | None = None
        self._opened = threading.Event()
        self._closed = threading.Event()
        self._events: deque[dict[str, Any]] = deque(maxlen=self.MAX_BUFFERED_EVENTS)
        self._events_lock = threading.Lock()
        self._send_lock = threading.Lock()
        self._pending_lock = threading.Lock()
        self._pending: dict[int, dict[str, Any]] = {}
        self._command_names: dict[int, str] = {}
        self._command_id = 0
        self._attached_targets: set[str] = set()
        self._sessions: dict[str, dict[str, Any]] = {}
        self._tracked_request_ids: set[str] = set()
        self._pending_extra_events: dict[str, dict[str, Any]] = {}
        self._running = False

    @property
    def is_running(self) -> bool:
        """返回监听器是否已连接并处于运行状态。"""
        return self._running and self._opened.is_set()

    def start(self, debugger_address: str | None) -> None:
        """连接 Chrome 浏览器级调试端口，并开启自动附着所有页面。"""
        self.stop()
        if not debugger_address:
            logger.warning("Chrome 未返回调试端口，无法启用多标签页 CDP 监听。")
            return
        browser_ws_url = self._resolve_browser_ws_url(debugger_address)
        if not browser_ws_url:
            logger.warning("无法解析 Chrome 调试 WebSocket 地址，调试端口：%s", debugger_address)
            return

        self._opened.clear()
        self._closed.clear()
        self._running = True
        self._ws = websocket.WebSocketApp(
            browser_ws_url,
            on_open=self._on_open,
            on_message=self._on_message,
            on_error=self._on_error,
            on_close=self._on_close,
        )
        self._thread = threading.Thread(target=self._ws.run_forever, name="cdp-network-listener", daemon=True)
        self._thread.start()
        if not self._opened.wait(timeout=3):
            logger.warning("CDP 网络监听器连接超时，后续将回退到 Selenium performance log。")
            self.stop()

    def stop(self) -> None:
        """停止 CDP 监听并清理缓存事件。"""
        self._running = False
        if self._ws:
            try:
                self._ws.close()
            except Exception:
                logger.debug("关闭 CDP WebSocket 失败。", exc_info=True)
        if self._thread and self._thread.is_alive():
            self._closed.wait(timeout=2)
        self._ws = None
        self._thread = None
        self._opened.clear()
        self._closed.set()
        self._attached_targets.clear()
        self._sessions.clear()
        self._tracked_request_ids.clear()
        self._pending_extra_events.clear()
        self.clear_events()
        with self._pending_lock:
            self._pending.clear()
            self._command_names.clear()

    def clear_events(self) -> None:
        """清空已缓存网络事件，用于新批次开始前隔离旧请求。"""
        with self._events_lock:
            self._events.clear()
            self._tracked_request_ids.clear()
            self._pending_extra_events.clear()

    def poll_events(self) -> list[dict[str, Any]]:
        """取出并清空当前累计的网络事件。"""
        with self._events_lock:
            events = list(self._events)
            self._events.clear()
        return events

    def get_response_body(self, request_id: str) -> Any:
        """按带 session 作用域的请求 ID 读取响应体。"""
        session_id, raw_request_id = self._split_request_id(request_id)
        if not session_id:
            return None
        response = self._send_command(
            "Network.getResponseBody",
            {"requestId": raw_request_id},
            session_id=session_id,
            wait=True,
            timeout=2.5,
        )
        return (response or {}).get("result")

    def _resolve_browser_ws_url(self, debugger_address: str) -> str | None:
        """通过 Chrome 调试端口查询浏览器级 WebSocket 地址。"""
        try:
            with urllib.request.urlopen(f"http://{debugger_address}/json/version", timeout=2) as response:
                version_info = json.loads(response.read().decode("utf-8"))
        except Exception as exc:
            logger.warning("查询 Chrome 调试端口失败：%s", exc)
            return None
        return version_info.get("webSocketDebuggerUrl")

    def _on_open(self, _: websocket.WebSocketApp) -> None:
        """WebSocket 连接建立后，开启目标发现和自动附着。"""
        self._opened.set()
        self._send_command("Target.setDiscoverTargets", {"discover": True})
        self._send_command(
            "Target.setAutoAttach",
            {
                "autoAttach": True,
                "waitForDebuggerOnStart": False,
                "flatten": True,
            },
        )
        self._send_command("Target.getTargets", {}, wait=False)
        logger.info("CDP 网络监听器已启动，正在监听浏览器内所有页面标签。")

    def _on_message(self, _: websocket.WebSocketApp, message: str) -> None:
        """处理 CDP 响应和事件。"""
        if not self._should_parse_message(message):
            return
        try:
            payload = json.loads(message)
        except json.JSONDecodeError:
            return
        if "id" in payload:
            self._handle_command_response(payload)
            return

        method = payload.get("method")
        params = payload.get("params") or {}
        if method == "Target.attachedToTarget":
            self._handle_attached_to_target(params)
        elif method == "Target.detachedFromTarget":
            self._handle_detached_from_target(params)
        elif method == "Target.targetCreated":
            self._handle_target_created(params)
        elif method in self.CAPTURED_NETWORK_METHODS:
            self._cache_network_event(payload)

    def _should_parse_message(self, message: str) -> bool:
        """先用字符串快速过滤无关 CDP 消息，减少高频网络事件下的 JSON 解析压力。"""
        if '"id":' in message:
            return True
        if '"method":"Network.requestWillBeSent"' in message:
            return '"type":"Fetch"' in message or '"type":"XHR"' in message
        return any(method in message for method in self.INTERESTING_METHODS)

    def _on_error(self, _: websocket.WebSocketApp, error: Any) -> None:
        """记录 CDP 监听错误，避免影响主采集流程。"""
        if self._running:
            logger.debug("CDP 网络监听器异常：%s", error)

    def _on_close(self, *_: Any) -> None:
        """标记监听连接已关闭。"""
        self._running = False
        self._closed.set()

    def _handle_command_response(self, payload: dict[str, Any]) -> None:
        """处理命令响应，唤醒等待响应的调用方。"""
        command_id = payload.get("id")
        command_name = self._command_names.pop(command_id, "")
        if command_name == "Target.getTargets":
            for target_info in payload.get("result", {}).get("targetInfos", []):
                self._attach_target(target_info)
        with self._pending_lock:
            pending = self._pending.get(command_id)
            if pending is not None:
                pending["response"] = payload
                pending["event"].set()

    def _handle_attached_to_target(self, params: dict[str, Any]) -> None:
        """标签页附着成功后开启 Network 域。"""
        session_id = params.get("sessionId")
        target_info = params.get("targetInfo") or {}
        target_id = target_info.get("targetId")
        if target_id:
            self._attached_targets.add(target_id)
        if not session_id:
            return
        self._sessions[session_id] = target_info
        self._send_command(
            "Page.addScriptToEvaluateOnNewDocument",
            {"source": self.WEBDRIVER_STEALTH_SCRIPT},
            session_id=session_id,
        )
        self._send_command("Network.enable", self.NETWORK_ENABLE_PARAMS, session_id=session_id)
        logger.debug("CDP 已附着页面标签：%s，session：%s", target_info.get("url") or target_id, session_id)

    def _handle_detached_from_target(self, params: dict[str, Any]) -> None:
        """标签页关闭或脱离时清理 session 映射。"""
        session_id = params.get("sessionId")
        if session_id:
            self._sessions.pop(session_id, None)
            self._tracked_request_ids = {
                request_id for request_id in self._tracked_request_ids if not request_id.startswith(f"{session_id}|")
            }
            self._pending_extra_events = {
                request_id: event
                for request_id, event in self._pending_extra_events.items()
                if not request_id.startswith(f"{session_id}|")
            }

    def _handle_target_created(self, params: dict[str, Any]) -> None:
        """发现新标签页后主动附着，避免首批请求落在监听盲区。"""
        self._attach_target(params.get("targetInfo") or {})

    def _attach_target(self, target_info: dict[str, Any]) -> None:
        """主动附着 page 类型目标，过滤 devtools、扩展等非页面目标。"""
        if target_info.get("type") != "page":
            return
        target_id = target_info.get("targetId")
        if not target_id or target_id in self._attached_targets:
            return
        self._attached_targets.add(target_id)
        self._send_command("Target.attachToTarget", {"targetId": target_id, "flatten": True})

    def _cache_network_event(self, payload: dict[str, Any]) -> None:
        """把 CDP Network 事件转换成解析器可消费的结构。"""
        session_id = payload.get("sessionId") or "browser"
        method = payload.get("method")
        params = payload.get("params") or {}
        raw_request_id = str(params.get("requestId") or "")
        if not raw_request_id:
            return
        tracked_request_id = f"{session_id}|{raw_request_id}" if raw_request_id else ""
        if method == "Network.requestWillBeSent":
            # 只跟踪接口类请求，避免图片、字体、脚本等静态资源事件挤占浏览器和后端处理时间。
            if params.get("type") not in self.TRACKED_RESOURCE_TYPES:
                self._pending_extra_events.pop(tracked_request_id, None)
                return
            self._tracked_request_ids.add(tracked_request_id)
            pending_extra_event = self._pending_extra_events.pop(tracked_request_id, None)
            if pending_extra_event:
                self._append_event(pending_extra_event)
        elif method == "Network.requestWillBeSentExtraInfo" and tracked_request_id not in self._tracked_request_ids:
            # ExtraInfo 有时早于主请求事件到达，先短暂暂存，等确认是接口请求后再补入队列。
            self._pending_extra_events[tracked_request_id] = self._build_event(method, params, session_id)
            if len(self._pending_extra_events) > self.MAX_PENDING_EXTRA_EVENTS:
                oldest_key = next(iter(self._pending_extra_events))
                self._pending_extra_events.pop(oldest_key, None)
            return
        elif tracked_request_id not in self._tracked_request_ids:
            return
        self._append_event(self._build_event(method, params, session_id))
        if method in {"Network.loadingFinished", "Network.loadingFailed"}:
            self._tracked_request_ids.discard(tracked_request_id)

    def _build_event(self, method: str | None, params: dict[str, Any], session_id: str) -> dict[str, Any]:
        """生成解析器统一消费的 CDP 事件结构。"""
        event = {
            "method": method,
            "params": params,
            "sessionId": session_id,
            "webview": session_id,
            "source": "cdp",
        }
        return event

    def _append_event(self, event: dict[str, Any]) -> None:
        """把已确认需要的网络事件写入有限队列，防止异常页面撑爆内存。"""
        with self._events_lock:
            # deque 自带上限，异常页面制造海量事件时会自动丢弃最旧数据，避免列表搬移造成卡顿。
            self._events.append(event)

    def _send_command(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        session_id: str | None = None,
        wait: bool = False,
        timeout: float = 2,
    ) -> dict[str, Any] | None:
        """发送 CDP 命令；需要结果时阻塞等待响应。"""
        if not self._ws or not self._running:
            return None
        command_id = self._next_command_id()
        payload: dict[str, Any] = {"id": command_id, "method": method, "params": params or {}}
        if session_id:
            payload["sessionId"] = session_id
        pending: dict[str, Any] | None = None
        if wait:
            pending = {"event": threading.Event(), "response": None}
            with self._pending_lock:
                self._pending[command_id] = pending
        self._command_names[command_id] = method
        try:
            with self._send_lock:
                self._ws.send(json.dumps(payload))
        except Exception as exc:
            logger.debug("发送 CDP 命令失败：%s，原因：%s", method, exc)
            if wait:
                with self._pending_lock:
                    self._pending.pop(command_id, None)
            return None
        if not wait or pending is None:
            return None
        pending["event"].wait(timeout=timeout)
        with self._pending_lock:
            self._pending.pop(command_id, None)
        return pending.get("response")

    def _next_command_id(self) -> int:
        """生成递增命令 ID。"""
        with self._send_lock:
            self._command_id += 1
            return self._command_id

    def _split_request_id(self, request_id: str) -> tuple[str | None, str]:
        """拆分 session 作用域请求 ID。"""
        if "|" not in request_id:
            return None, request_id
        session_id, raw_request_id = request_id.rsplit("|", 1)
        return session_id or None, raw_request_id
