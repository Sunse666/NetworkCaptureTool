from typing import Any

from pydantic import BaseModel, Field


class BackgroundSetting(BaseModel):
    """背景设置：支持预设背景、自定义颜色和用户选择的图片数据。"""

    mode: str = Field(default="preset", description="preset/color/image")
    preset: str = "aurora"
    color: str | None = None
    image_path: str | None = None
    blur: int = 18
    opacity: float = 0.52


class SettingUpdateRequest(BaseModel):
    """通用设置更新入参。"""

    key: str
    value: dict[str, Any]
    description: str | None = None
