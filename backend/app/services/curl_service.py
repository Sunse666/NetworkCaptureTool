import json
import shlex
from typing import Any


DEFAULT_REMOVABLE_HEADERS = {
    "accept-language",
    "connection",
    "user-agent",
    "sec-fetch-dest",
    "sec-fetch-mode",
    "sec-fetch-site",
    "sec-ch-ua",
    "sec-ch-ua-mobile",
    "sec-ch-ua-platform",
    "cache-control",
    "pragma",
    "upgrade-insecure-requests",
}

DEFAULT_KEEP_HEADERS = {
    "content-type",
    "authorization",
    "cookie",
    "origin",
    "referer",
}


class CurlService:
    """cURL 生成服务：负责输出完整 cURL 和精简 cURL。"""

    def clean_headers(self, headers: dict[str, Any] | None) -> dict[str, str]:
        """移除浏览器无关请求头，仅保留接口调用必要信息。"""
        cleaned: dict[str, str] = {}
        for key, value in (headers or {}).items():
            normalized = key.lower()
            is_business_header = normalized.startswith(("x-", "trace", "tenant", "csrf"))
            if normalized in DEFAULT_REMOVABLE_HEADERS and normalized not in DEFAULT_KEEP_HEADERS:
                continue
            if normalized in DEFAULT_KEEP_HEADERS or is_business_header:
                cleaned[key] = str(value)
        return cleaned

    def build_curl(
        self,
        method: str,
        url: str,
        headers: dict[str, Any] | None,
        cookies: dict[str, Any] | None,
        body: Any = None,
        mode: str = "bash",
        clean: bool = True,
    ) -> str:
        """生成 cURL 字符串，mode 可扩展为 bash/powershell/cmd。"""
        selected_headers = self.clean_headers(headers) if clean else {k: str(v) for k, v in (headers or {}).items()}
        parts = ["curl"]
        if method.upper() not in {"GET", "HEAD"}:
            parts.append(f"-X {method.upper()}")
        parts.append(self._quote(url, mode))
        for key, value in selected_headers.items():
            if key.lower() == "cookie":
                continue
            parts.append(f"-H {self._quote(f'{key}: {value}', mode)}")
        cookie_text = self._cookie_string(cookies)
        if cookie_text:
            parts.append(f"-b {self._quote(cookie_text, mode)}")
        if body not in (None, "", {}):
            parts.append(f"--data-raw {self._quote(self._body_to_text(body), mode)}")
        return self._join(parts, mode)

    def _cookie_string(self, cookies: dict[str, Any] | None) -> str:
        """把 Cookie 字典拼接成浏览器兼容的 Cookie 字符串。"""
        if not cookies:
            return ""
        return "; ".join(f"{key}={value}" for key, value in cookies.items())

    def _body_to_text(self, body: Any) -> str:
        """统一把请求体转换成可粘贴到 cURL 的文本。"""
        if isinstance(body, str):
            return body
        return json.dumps(body, ensure_ascii=False, separators=(",", ":"))

    def _quote(self, value: str, mode: str) -> str:
        """根据目标命令行风格转义参数，默认使用 Bash 风格。"""
        if mode == "powershell":
            return "'" + value.replace("'", "''") + "'"
        if mode == "cmd":
            return '"' + value.replace('"', '\\"') + '"'
        return shlex.quote(value)

    def _join(self, parts: list[str], mode: str) -> str:
        """按不同命令行习惯拼接多行 cURL。"""
        separator = " `\n  " if mode == "powershell" else " \\\n  "
        return separator.join(parts)
