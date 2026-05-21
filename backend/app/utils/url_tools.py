from urllib.parse import parse_qsl, urlparse

from app.core.exceptions import AppError


def normalize_url(url: str) -> str:
    """校验并规范化 URL，给用户返回明确的中文错误提示。"""
    value = (url or "").strip()
    if not value:
        raise AppError("请输入目标网站地址。", "URL_EMPTY")
    if not value.startswith(("http://", "https://")):
        value = f"https://{value}"
    parsed = urlparse(value)
    if not parsed.netloc:
        raise AppError("网址格式不正确，请输入类似 https://example.com 的地址。", "URL_INVALID")
    return value


def split_url(url: str) -> tuple[str, str, dict[str, str]]:
    """拆分 URL 为域名、路径和 Query 参数，便于列表展示和参数可视化。"""
    parsed = urlparse(url)
    path = parsed.path or "/"
    query_params = dict(parse_qsl(parsed.query, keep_blank_values=True))
    return parsed.netloc, path, query_params
