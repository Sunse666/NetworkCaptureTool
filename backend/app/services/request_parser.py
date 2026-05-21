import json
from datetime import datetime
from typing import Any

from app.services.curl_service import CurlService
from app.services.dynamic_param_service import DynamicParamService
from app.utils.url_tools import split_url


class RequestParser:
    """请求解析服务：把浏览器性能日志转换成系统内部结构。"""

    API_RESOURCE_TYPES = {"XHR", "Fetch"}
    IGNORED_URL_PREFIXES = ("data:", "blob:", "about:", "chrome:", "devtools:")

    def __init__(self) -> None:
        self.dynamic_service = DynamicParamService()
        self.curl_service = CurlService()
        self._active_records: dict[str, dict[str, Any]] = {}
        self._pending_request_extras: dict[str, dict[str, Any]] = {}
        self._raw_request_scopes: dict[str, str] = {}

    def reset(self) -> None:
        """开始新采集批次前清空未完成请求缓存，避免上一批次的事件串入新批次。"""
        self._active_records.clear()
        self._pending_request_extras.clear()
        self._raw_request_scopes.clear()

    def parse_performance_events(self, events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """把 Chrome DevTools 性能日志合并为请求记录。"""
        changed_records: dict[str, dict[str, Any]] = {}
        completed_request_ids: set[str] = set()
        for event in events:
            # Selenium performance log 和浏览器级 CDP 监听器的事件结构不同，这里统一成 method/params。
            message = event.get("message", event)
            method = message.get("method")
            params = message.get("params", {})
            request_id = self._scoped_request_id(event, params)
            if not request_id:
                continue
            if method == "Network.requestWillBeSent":
                self._active_records[request_id] = self._parse_request_event(request_id, params)
                self._merge_pending_request_extra(request_id)
                changed_records[request_id] = self._active_records[request_id]
            elif method == "Network.requestWillBeSentExtraInfo":
                self._merge_request_extra_event(request_id, params)
                if request_id in self._active_records:
                    changed_records[request_id] = self._active_records[request_id]
            elif method == "Network.responseReceived" and request_id in self._active_records:
                self._merge_response_event(self._active_records[request_id], params)
                changed_records[request_id] = self._active_records[request_id]
            elif method == "Network.loadingFinished" and request_id in self._active_records:
                self._merge_finished_event(self._active_records[request_id], params)
                changed_records[request_id] = self._active_records[request_id]
                completed_request_ids.add(request_id)
            elif method == "Network.loadingFailed" and request_id in self._active_records:
                changed_records[request_id] = self._active_records[request_id]
                completed_request_ids.add(request_id)

        records = [item for item in changed_records.values() if item.get("url") and not self._should_ignore_url(item["url"])]
        for request_id in completed_request_ids:
            self._active_records.pop(request_id, None)
        return records

    def _scoped_request_id(self, event: dict[str, Any], params: dict[str, Any]) -> str | None:
        """拼接标签页上下文和浏览器请求 ID，避免多标签页 requestId 冲突。"""
        raw_request_id = params.get("requestId")
        if not raw_request_id:
            return None
        webview = event.get("webview") or params.get("frameId")
        if webview:
            scoped_request_id = f"{webview}|{raw_request_id}"
            self._raw_request_scopes[str(raw_request_id)] = scoped_request_id
            return scoped_request_id
        return self._raw_request_scopes.get(str(raw_request_id), f"default|{raw_request_id}")

    def _parse_request_event(self, request_id: str, params: dict[str, Any]) -> dict[str, Any]:
        """解析请求发起事件，提取 URL、方法、请求头和请求体。"""
        request = params.get("request", {})
        url = request.get("url", "")
        domain, path, query_params = split_url(url)
        headers = request.get("headers", {}) or {}
        cookies = self._parse_cookie_header(headers.get("Cookie") or headers.get("cookie"))
        post_data = request.get("postData")
        body = self._parse_body(post_data)
        resource_type = params.get("type", "Other")
        dynamic_marks = self.dynamic_service.mark_params(query_params)
        if isinstance(body, dict):
            dynamic_marks.extend(self.dynamic_service.mark_params(body))
        dynamic_marks.extend(self.dynamic_service.mark_params(headers))
        dynamic_marks.extend(self.dynamic_service.mark_params(cookies))
        return {
            "request_id": request_id,
            "method": request.get("method", "GET").upper(),
            "url": url,
            "domain": domain,
            "path": path,
            "resource_type": resource_type,
            "status_code": None,
            "start_time": datetime.fromtimestamp(params.get("wallTime", datetime.now().timestamp())),
            "duration_ms": None,
            "request_size": len(post_data or ""),
            "response_size": None,
            "is_api": resource_type in self.API_RESOURCE_TYPES,
            "query_params": query_params,
            "request_headers": headers,
            "cookies": cookies,
            "request_body": body,
            "response_headers": {},
            "response_body": None,
            "dynamic_marks": dynamic_marks,
        }

    def _should_ignore_url(self, url: str) -> bool:
        """过滤 data/blob/about 等非网络接口资源，避免超长内联资源污染接口采集。"""
        return url.startswith(self.IGNORED_URL_PREFIXES)

    def _merge_response_event(self, record: dict[str, Any], params: dict[str, Any]) -> None:
        """合并响应事件，补充状态码、响应头和耗时。"""
        response = params.get("response", {})
        record["status_code"] = response.get("status")
        record["response_headers"] = response.get("headers", {}) or {}
        timing = response.get("timing") or {}
        receive_headers_end = timing.get("receiveHeadersEnd")
        if isinstance(receive_headers_end, (int, float)) and receive_headers_end >= 0:
            record["duration_ms"] = int(receive_headers_end)

    def _merge_request_extra_event(self, request_id: str, params: dict[str, Any]) -> None:
        """合并 ExtraInfo 请求头，补齐 Chrome 未放在普通请求事件里的 Cookie。"""
        headers = params.get("headers", {}) or {}
        associated_cookies = params.get("associatedCookies", []) or []
        extra = {
            "headers": headers,
            "cookies": self._parse_extra_cookies(headers, associated_cookies),
        }
        if request_id not in self._active_records:
            self._pending_request_extras[request_id] = extra
            return
        self._apply_request_extra(self._active_records[request_id], extra)

    def _merge_pending_request_extra(self, request_id: str) -> None:
        """请求主事件晚于 ExtraInfo 到达时，把暂存的 Cookie 信息补回记录。"""
        raw_request_id = request_id.rsplit("|", 1)[-1]
        extra = self._pending_request_extras.pop(request_id, None) or self._pending_request_extras.pop(f"default|{raw_request_id}", None)
        if extra and request_id in self._active_records:
            self._apply_request_extra(self._active_records[request_id], extra)

    def _apply_request_extra(self, record: dict[str, Any], extra: dict[str, Any]) -> None:
        """把 ExtraInfo 中的请求头和 Cookie 合并到当前请求记录。"""
        headers = extra.get("headers") or {}
        cookies = extra.get("cookies") or {}
        if headers:
            record["request_headers"] = {**record.get("request_headers", {}), **headers}
        if cookies:
            record["cookies"] = {**record.get("cookies", {}), **cookies}
        record["dynamic_marks"] = self._unique_marks(
            [
                *record.get("dynamic_marks", []),
                *self.dynamic_service.mark_params(headers),
                *self.dynamic_service.mark_params(cookies),
            ],
        )

    def _parse_extra_cookies(self, headers: dict[str, Any], associated_cookies: list[dict[str, Any]]) -> dict[str, str]:
        """从 ExtraInfo 的 Cookie 头和 associatedCookies 双通道提取 Cookie。"""
        cookies = self._parse_cookie_header(headers.get("Cookie") or headers.get("cookie"))
        for item in associated_cookies:
            cookie = item.get("cookie") or {}
            name = cookie.get("name")
            value = cookie.get("value")
            if name and value is not None:
                cookies[str(name)] = str(value)
        return cookies

    def _merge_finished_event(self, record: dict[str, Any], params: dict[str, Any]) -> None:
        """合并加载完成事件，补充响应体大小。"""
        encoded_length = params.get("encodedDataLength")
        if isinstance(encoded_length, (int, float)):
            record["response_size"] = int(encoded_length)

    def finalize_record(self, record: dict[str, Any]) -> dict[str, Any]:
        """生成 cURL 字段，确保保存前的数据完整。"""
        finalized = dict(record)
        finalized["raw_curl"] = self.curl_service.build_curl(
            finalized["method"],
            finalized["url"],
            finalized["request_headers"],
            finalized["cookies"],
            finalized["request_body"],
            clean=False,
        )
        finalized["clean_curl"] = self.curl_service.build_curl(
            finalized["method"],
            finalized["url"],
            finalized["request_headers"],
            finalized["cookies"],
            finalized["request_body"],
            clean=True,
        )
        return finalized

    def parse_response_body(self, body: Any, headers: dict[str, Any] | None = None) -> Any:
        """尽量把响应体解析为 JSON；非文本或解析失败时保留可读摘要。"""
        if body in (None, ""):
            return None
        if isinstance(body, dict):
            return body
        content_type = ""
        for key, value in (headers or {}).items():
            if key.lower() == "content-type":
                content_type = str(value).lower()
                break
        if "application/json" in content_type or str(body).lstrip().startswith(("{", "[")):
            try:
                return json.loads(body)
            except json.JSONDecodeError:
                return body
        if "text/" in content_type or "javascript" in content_type:
            return body
        return {
            "__hidden_payload__": True,
            "reason": f"响应类型 {content_type or '未知'} 不适合直接展示。",
            "size": len(str(body)),
        }

    def _parse_cookie_header(self, cookie_header: str | None) -> dict[str, str]:
        """把 Cookie 字符串拆成 key-value，便于表格化展示。"""
        if not cookie_header:
            return {}
        cookies: dict[str, str] = {}
        for item in cookie_header.split(";"):
            if "=" not in item:
                continue
            key, value = item.split("=", 1)
            cookies[key.strip()] = value.strip()
        return cookies

    def _unique_marks(self, marks: list[dict[str, Any]]) -> list[dict[str, Any]]:
        """按参数名和标记类型去重，避免 ExtraInfo 多次到达导致标签重复。"""
        result: list[dict[str, Any]] = []
        seen: set[tuple[str, str]] = set()
        for mark in marks:
            key = (str(mark.get("key")), str(mark.get("type")))
            if key in seen:
                continue
            seen.add(key)
            result.append(mark)
        return result

    def _parse_body(self, post_data: str | None) -> Any:
        """尽量把请求体解析为 JSON；失败时保留原始文本。"""
        if not post_data:
            return None
        try:
            return json.loads(post_data)
        except json.JSONDecodeError:
            return post_data
