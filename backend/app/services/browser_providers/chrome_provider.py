from __future__ import annotations

from pathlib import Path
from typing import Any

from selenium import webdriver
from selenium.webdriver.chrome.service import Service as ChromeService

from app.core.config import resolve_runtime_path
from app.services.browser_providers.base import BrowserProvider


class ChromeBrowserProvider(BrowserProvider):
    """Provider for Google Chrome (Chromium)."""

    @property
    def browser_type(self) -> str:
        return "chrome"

    @property
    def browser_display_name(self) -> str:
        return "Google Chrome"

    @property
    def browser_process_name(self) -> str:
        return "chrome.exe"

    @property
    def driver_process_name(self) -> str:
        return "chromedriver.exe"

    def create_options(self) -> webdriver.ChromeOptions:
        return webdriver.ChromeOptions()

    def create_service(self, executable_path: str) -> ChromeService:
        return ChromeService(executable_path=executable_path)

    def create_driver(self, service: Any, options: Any) -> webdriver.Chrome:
        return webdriver.Chrome(service=service, options=options)

    def get_binary_location(self, settings) -> str | None:
        return settings.chrome_binary

    def get_driver_path(self, settings) -> str | None:
        return settings.chromedriver_path

    def get_user_data_dir(self, settings) -> Path:
        return resolve_runtime_path(settings.browser_user_data_dir)

    @property
    def logging_prefs_key(self) -> str:
        return "goog:loggingPrefs"

    def apply_lifecycle_options(self, options: webdriver.ChromeOptions) -> None:
        options.add_experimental_option("detach", True)
