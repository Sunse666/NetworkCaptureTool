"""Browser provider registry and factory."""

from app.services.browser_providers.base import BrowserProvider
from app.services.browser_providers.chrome_provider import ChromeBrowserProvider
from app.services.browser_providers.edge_provider import EdgeWebView2Provider

_PROVIDERS: dict[str, type[BrowserProvider]] = {
    "chrome": ChromeBrowserProvider,
    "webview2": EdgeWebView2Provider,
}


def get_provider(browser_type: str) -> BrowserProvider:
    """Return a provider instance for the given browser type string."""
    cls = _PROVIDERS.get(browser_type)
    if cls is None:
        raise ValueError(
            f"Unsupported browser type: {browser_type}. "
            f"Supported: {list(_PROVIDERS)}"
        )
    return cls()


def list_supported_browsers() -> list[dict[str, str]]:
    """Return metadata for all supported browsers (used by frontend)."""
    provider = get_provider("webview2")
    webview2_name = provider.browser_display_name
    provider = get_provider("chrome")
    chrome_name = provider.browser_display_name
    return [
        {"type": "webview2", "name": webview2_name},
        {"type": "chrome", "name": chrome_name},
    ]
