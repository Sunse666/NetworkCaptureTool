from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any


class BrowserProvider(ABC):
    """Abstract interface for browser-specific operations.

    Each concrete subclass encapsulates the differences between browser
    engines (Chrome vs Edge/WebView2) so that BrowserService can remain
    agnostic of the underlying browser.
    """

    @property
    @abstractmethod
    def browser_type(self) -> str:
        """Short identifier, e.g. 'chrome' or 'webview2'."""

    @property
    @abstractmethod
    def browser_display_name(self) -> str:
        """Human-readable name, e.g. 'Google Chrome' or 'Edge WebView2'."""

    @abstractmethod
    def create_options(self) -> Any:
        """Return a browser-specific Options instance."""

    @abstractmethod
    def create_service(self, executable_path: str) -> Any:
        """Return a browser-specific Service instance."""

    @abstractmethod
    def create_driver(self, service: Any, options: Any) -> Any:
        """Create a WebDriver instance."""

    @abstractmethod
    def get_binary_location(self, settings) -> str | None:
        """Return the path to the browser executable, or None for default."""

    @abstractmethod
    def get_driver_path(self, settings) -> str | None:
        """Return the configured driver path for this browser."""

    @abstractmethod
    def get_user_data_dir(self, settings) -> Path:
        """Return the profile directory Path for this browser type."""

    @property
    @abstractmethod
    def browser_process_name(self) -> str:
        """e.g. 'chrome.exe' or 'msedgewebview2.exe'."""

    @property
    @abstractmethod
    def driver_process_name(self) -> str:
        """e.g. 'chromedriver.exe' or 'msedgedriver.exe'."""

    @abstractmethod
    def apply_lifecycle_options(self, options: Any) -> None:
        """Apply detach / lifecycle options so the browser outlives the driver."""

    @property
    @abstractmethod
    def logging_prefs_key(self) -> str:
        """Capability key for performance logging, e.g. 'goog:loggingPrefs' or 'ms:loggingPrefs'."""

    def auto_detect_binary(self) -> str | None:
        """Override for browsers whose install path can be auto-detected."""
        return None
