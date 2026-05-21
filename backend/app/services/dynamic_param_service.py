import re
from typing import Any


class DynamicParamService:
    """动态参数识别服务：标记时间戳、Token、签名、业务 ID、分页等字段。"""

    TIMESTAMP_KEYS = {"timestamp", "time", "ts", "start_time", "end_time"}
    RANDOM_KEYS = {"nonce", "random", "uuid", "guid"}
    SIGN_KEYS = {"sign", "signature", "hash"}
    TOKEN_KEYS = {"token", "access_token", "refresh_token", "csrf_token", "authorization"}
    PAGE_KEYS = {"page", "page_size", "size", "limit", "offset"}

    def mark_params(self, params: dict[str, Any] | None) -> list[dict[str, Any]]:
        """返回参数标记列表，前端据此展示“动态/鉴权/分页”等标签。"""
        marks: list[dict[str, Any]] = []
        if not params:
            return marks
        for key, value in params.items():
            normalized = key.lower()
            mark_type = self._detect_type(normalized, value)
            if mark_type:
                marks.append({"key": key, "type": mark_type, "reason": self._reason(mark_type)})
        return marks

    def _detect_type(self, key: str, value: Any) -> str | None:
        """根据字段名和值综合判断参数类型。"""
        if key in self.TOKEN_KEYS or "token" in key:
            return "auth"
        if key in self.SIGN_KEYS:
            return "signature"
        if key in self.TIMESTAMP_KEYS or self._looks_like_timestamp(value):
            return "dynamic"
        if key in self.RANDOM_KEYS:
            return "dynamic"
        if key in self.PAGE_KEYS:
            return "pagination"
        if key.endswith("_id") or key == "id":
            return "business_id"
        return None

    def _looks_like_timestamp(self, value: Any) -> bool:
        """识别 10 位或 13 位时间戳，减少用户手工判断成本。"""
        text = str(value)
        return bool(re.fullmatch(r"\d{10}|\d{13}", text))

    def _reason(self, mark_type: str) -> str:
        """给前端展示可理解的中文说明。"""
        reasons = {
            "auth": "疑似鉴权参数，复制或自动化时需要关注有效期。",
            "signature": "疑似签名参数，通常需要由算法动态生成。",
            "dynamic": "疑似动态参数，可能随时间或会话变化。",
            "pagination": "分页参数，可在接口自动化中参数化。",
            "business_id": "疑似业务 ID，建议替换为测试数据变量。",
        }
        return reasons.get(mark_type, "需要关注的参数。")
