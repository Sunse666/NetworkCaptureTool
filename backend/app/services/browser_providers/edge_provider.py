from __future__ import annotations

import glob
import logging
import sys
from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.edge.service import Service as EdgeService

from app.core.config import resolve_runtime_path
from app.services.browser_providers.base import BrowserProvider

logger = logging.getLogger(__name__)

_WEBVIEW2_SEARCH_PATTERNS = [
    r"C:\Program Files (x86)\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe",
    r"C:\Program Files\Microsoft\EdgeWebView\Application\*\msedgewebview2.exe",
]


class EdgeWebView2Provider(BrowserProvider):
    """Provider for Microsoft Edge WebView2 Runtime.

    Uses Selenium's webdriver.Edge (msedgedriver.exe) to drive the
    msedgewebview2.exe runtime. WebView2 Runtime ships pre-installed on
    Windows 11 and uses the same CDP protocol as Chrome.
    """

    @property
    def browser_type(self) -> str:
        return "webview2"

    @property
    def browser_display_name(self) -> str:
        return "Edge WebView2"

    @property
    def browser_process_name(self) -> str:
        return "msedgewebview2.exe"

    @property
    def driver_process_name(self) -> str:
        return "msedgedriver.exe"

    def create_options(self) -> webdriver.EdgeOptions:
        return webdriver.EdgeOptions()

    def create_service(self, executable_path: str) -> EdgeService:
        return EdgeService(executable_path=executable_path)

    def create_driver(self, service: Any, options: Any) -> webdriver.Edge:
        return webdriver.Edge(service=service, options=options)

    def get_binary_location(self, settings) -> str | None:
        """Return configured or auto-detected WebView2 binary path."""
        if settings.edge_binary:
            return settings.edge_binary
        return self.auto_detect_binary()

    def get_driver_path(self, settings) -> str | None:
        return settings.msedgedriver_path

    def get_user_data_dir(self, settings) -> Path:
        return resolve_runtime_path(settings.edge_user_data_dir)

    @property
    def logging_prefs_key(self) -> str:
        return "ms:loggingPrefs"

    def apply_lifecycle_options(self, options: webdriver.EdgeOptions) -> None:
        options.add_experimental_option("detach", True)

    def auto_detect_binary(self) -> str | None:
        """Locate the installed WebView2 Runtime by scanning standard paths."""
        if sys.platform != "win32":
            logger.debug("WebView2 auto-detect skipped (not Windows).")
            return None
        for pattern in _WEBVIEW2_SEARCH_PATTERNS:
            matches = sorted(glob.glob(pattern))
            if matches:
                latest = matches[-1]
                logger.info("Auto-detected WebView2 Runtime: %s", latest)
                return latest
        logger.warning(
            "WebView2 Runtime not found. Install it or set edge_binary in .env"
        )
        return None
