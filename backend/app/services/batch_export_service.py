import json
import re
import uuid
from datetime import datetime
from typing import Any
from urllib.parse import parse_qsl, unquote, urlparse

from app.models.capture import CapturedRequest
from app.services.curl_service import CurlService


class BatchExportService:
    """批量导出服务：把选中的接口请求转换为 Postman、OpenAPI、cURL 和 Apifox 可导入文件。"""

    POSTMAN_SCHEMA_URL = "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
    OPENAPI_VERSION = "3.0.3"

    def __init__(self) -> None:
        self.curl_service = CurlService()

    def build_payload(self, requests: list[CapturedRequest], export_format: str) -> dict[str, Any]:
        """根据导出格式生成统一下载响应，前端只需要按 content_type 保存文件。"""
        normalized_format = export_format.lower()
        if normalized_format == "postman":
            return self.build_postman_payload(requests)
        if normalized_format == "openapi":
            return self.build_openapi_payload(requests)
        if normalized_format == "curl":
            return self.build_curl_payload(requests)
        if normalized_format == "apifox":
            return self.build_apifox_payload(requests)
        raise ValueError(f"不支持的导出格式：{export_format}")

    def build_postman_payload(self, requests: list[CapturedRequest]) -> dict[str, Any]:
        """生成 Postman Collection v2.1 JSON，Postman 和 Apifox 都可直接导入。"""
        batch_no = self._batch_no(requests)
        items = [
            {
                "name": self._item_name(request),
                "request": self._postman_request_item(request),
                "response": [],
            }
            for request in requests
        ]
        collection = {
            "info": {
                "_postman_id": str(uuid.uuid4()),
                "name": f"接口捕获 - Postman 批量导出 {batch_no}",
                "description": "由接口捕获工具根据浏览器网络请求生成。",
                "schema": self.POSTMAN_SCHEMA_URL,
            },
            "item": items,
        }
        return {
            "filename": self._safe_filename("postman_collection", batch_no, "json"),
            "content_type": "application/json;charset=utf-8",
            "format": "postman",
            "data": collection,
        }

    def build_openapi_payload(self, requests: list[CapturedRequest]) -> dict[str, Any]:
        """生成 OpenAPI 3.0 JSON，适合导入 Swagger、Apifox 或其它接口平台。"""
        batch_no = self._batch_no(requests)
        spec = self._openapi_document(
            requests,
            title=f"接口捕获 - OpenAPI 批量导出 {batch_no}",
            description="由接口捕获工具根据浏览器网络请求生成。",
        )
        return {
            "filename": self._safe_filename("openapi", batch_no, "json"),
            "content_type": "application/json;charset=utf-8",
            "format": "openapi",
            "data": spec,
        }

    def build_apifox_payload(self, requests: list[CapturedRequest]) -> dict[str, Any]:
        """生成 Apifox 项目格式 JSON，便于通过 Apifox 数据导入入口批量导入。"""
        batch_no = self._batch_no(requests)
        project = self._apifox_project(requests, batch_no)
        return {
            "filename": self._safe_filename("apifox_project", batch_no, "json"),
            "content_type": "application/json;charset=utf-8",
            "format": "apifox",
            "data": project,
        }

    def build_curl_payload(self, requests: list[CapturedRequest]) -> dict[str, Any]:
        """生成批量 cURL 文本文件，适合命令行回放或粘贴到接口平台导入。"""
        batch_no = self._batch_no(requests)
        lines: list[str] = []
        for index, request in enumerate(requests, start=1):
            lines.append(f"# {index}. {self._item_name(request)}")
            lines.append(request.clean_curl or request.raw_curl or self._build_curl_from_request(request))
            lines.append("")
        return {
            "filename": self._safe_filename("curl_batch", batch_no, "sh"),
            "content_type": "text/plain;charset=utf-8",
            "format": "curl",
            "data": "\n".join(lines).strip() + "\n",
        }

    def _openapi_document(self, requests: list[CapturedRequest], title: str, description: str) -> dict[str, Any]:
        """按请求域名、路径和方法组装 OpenAPI 文档。"""
        servers = self._openapi_servers(requests)
        paths: dict[str, Any] = {}
        for request in requests:
            path = request.path or urlparse(request.url).path or "/"
            method = request.method.lower()
            path_item = paths.setdefault(path, {})
            path_item[method] = self._openapi_operation(request)
        return {
            "openapi": self.OPENAPI_VERSION,
            "info": {
                "title": title,
                "version": "1.0.0",
                "description": description,
            },
            "servers": servers,
            "paths": paths,
        }

    def _openapi_servers(self, requests: list[CapturedRequest]) -> list[dict[str, str]]:
        """从采集请求中提取服务地址，OpenAPI 导入后可直接选择环境。"""
        servers: list[dict[str, str]] = []
        seen: set[str] = set()
        for request in requests:
            parsed = urlparse(request.url)
            if not parsed.scheme or not parsed.netloc:
                continue
            server_url = f"{parsed.scheme}://{parsed.netloc}"
            if server_url in seen:
                continue
            seen.add(server_url)
            servers.append({"url": server_url, "description": request.domain or parsed.netloc})
        return servers or [{"url": "https://example.com", "description": "请导入后替换为目标服务地址"}]

    def _openapi_operation(self, request: CapturedRequest) -> dict[str, Any]:
        """把单条采集请求转换为 OpenAPI operation。"""
        headers = self._cleaned_headers(request)
        parameters = [
            *self._openapi_query_parameters(request),
            *self._openapi_header_parameters(headers),
        ]
        operation: dict[str, Any] = {
            "summary": self._item_name(request),
            "operationId": self._operation_id(request),
            "tags": [request.domain or "default"],
            "parameters": parameters,
            "responses": self._openapi_responses(request),
            "x-captured-request-id": request.request_id,
            "x-apifox-folder": request.domain or "default",
        }
        request_body = self._openapi_request_body(request, headers)
        if request_body:
            operation["requestBody"] = request_body
        return operation

    def _openapi_query_parameters(self, request: CapturedRequest) -> list[dict[str, Any]]:
        """把 query 参数转换为 OpenAPI parameters。"""
        params = request.query_params or dict(parse_qsl(urlparse(request.url).query, keep_blank_values=True))
        return [
            {
                "name": str(key),
                "in": "query",
                "required": False,
                "schema": self._schema_from_value(value),
                "example": value,
            }
            for key, value in params.items()
        ]

    def _openapi_header_parameters(self, headers: dict[str, Any]) -> list[dict[str, Any]]:
        """把业务 Header 转换为 OpenAPI parameters，跳过 Cookie 和 Content-Type 这类专用字段。"""
        ignored_headers = {"cookie", "content-type", "content-length"}
        parameters: list[dict[str, Any]] = []
        for key, value in headers.items():
            if key.lower() in ignored_headers:
                continue
            parameters.append(
                {
                    "name": key,
                    "in": "header",
                    "required": False,
                    "schema": self._schema_from_value(value),
                    "example": value,
                },
            )
        return parameters

    def _openapi_request_body(self, request: CapturedRequest, headers: dict[str, Any]) -> dict[str, Any] | None:
        """按请求体类型生成 OpenAPI requestBody。"""
        body = request.request_body
        if body in (None, "", {}):
            return None
        content_type = self._header_value(headers, "content-type") or "application/json"
        schema = self._schema_from_value(body)
        return {
            "required": True,
            "content": {
                content_type: {
                    "schema": schema,
                    "example": body,
                },
            },
        }

    def _openapi_responses(self, request: CapturedRequest) -> dict[str, Any]:
        """根据已采集响应生成基础 OpenAPI responses。"""
        status = str(request.status_code or 200)
        content_type = self._first_content_type(request.response_headers) or "application/json"
        response: dict[str, Any] = {
            "description": "浏览器采集到的响应示例。",
        }
        if request.response_body not in (None, "", {}):
            response["content"] = {
                content_type: {
                    "schema": self._schema_from_value(request.response_body),
                    "example": request.response_body,
                },
            }
        return {status: response}

    def _schema_from_value(self, value: Any) -> dict[str, Any]:
        """根据示例值推断简单 JSON Schema，方便导入后生成参数类型。"""
        if isinstance(value, bool):
            return {"type": "boolean"}
        if isinstance(value, int) and not isinstance(value, bool):
            return {"type": "integer"}
        if isinstance(value, float):
            return {"type": "number"}
        if isinstance(value, list):
            item_schema = self._schema_from_value(value[0]) if value else {}
            return {"type": "array", "items": item_schema}
        if isinstance(value, dict):
            return {
                "type": "object",
                "properties": {str(key): self._schema_from_value(item) for key, item in value.items()},
                "x-apifox-orders": [str(key) for key in value.keys()],
            }
        return {"type": "string"}

    def _apifox_project(self, requests: list[CapturedRequest], batch_no: str) -> dict[str, Any]:
        """组装 Apifox 项目导入文件，保留请求参数、响应示例和精简 cURL。"""
        project_name = f"接口捕获 - Apifox 批量导出 {batch_no}"
        root_id = self._stable_number_id("folder", batch_no)
        api_items = [self._apifox_api_item(request, index) for index, request in enumerate(requests, start=1)]
        return {
            "apifoxProject": "1.0.0",
            "$schema": {
                "app": "apifox",
                "type": "project",
                "version": "1.2.0",
            },
            "info": {
                "name": project_name,
                "description": "由接口捕获工具根据浏览器网络请求生成。",
                "mockRule": {
                    "rules": [],
                    "enableSystemRule": True,
                },
            },
            "apiCollection": [
                {
                    "name": "接口捕获",
                    "id": root_id,
                    "auth": {},
                    "parentId": 0,
                    "serverId": "default",
                    "description": "",
                    "identityPattern": {
                        "httpApi": {
                            "type": "methodAndPath",
                            "bodyType": "",
                            "fields": [],
                        },
                    },
                    "preProcessors": [self._apifox_inherit_processor("inheritProcessors")],
                    "postProcessors": [self._apifox_inherit_processor("inheritProcessors")],
                    "inheritPostProcessors": {},
                    "inheritPreProcessors": {},
                    "items": api_items,
                },
            ],
            "socketCollection": [],
            "docCollection": [],
            "responseCollection": [self._apifox_empty_collection("根目录")],
            "schemaCollection": [{"name": "根目录", "items": []}],
            "apiTestCaseCollection": [self._apifox_empty_collection("根目录")],
            "testCaseReferences": [],
            "environments": [],
            "commonScripts": [],
            "databaseConnections": [],
            "globalVariables": [],
            "commonParameters": None,
            "projectSetting": self._apifox_project_setting(requests),
        }

    def _apifox_api_item(self, request: CapturedRequest, index: int) -> dict[str, Any]:
        """把单条请求转换为 Apifox apiCollection 中的接口节点。"""
        api_id = self._stable_number_id("api", request.request_id)
        response_id = self._stable_number_id("response", request.request_id)
        status_code = int(request.status_code or 200)
        response_content_type = self._first_content_type(request.response_headers) or "application/json"
        api = {
            "id": api_id,
            "method": request.method.lower(),
            "path": request.path or urlparse(request.url).path or "/",
            "parameters": {},
            "auth": {},
            "commonParameters": {
                "query": self._apifox_parameters(request.query_params, "query"),
                "body": [],
                "cookie": self._apifox_parameters(request.cookies, "cookie"),
                "header": self._apifox_parameters(self._cleaned_headers(request), "header"),
            },
            "responses": [
                {
                    "id": response_id,
                    "name": "成功",
                    "code": status_code,
                    "contentType": self._apifox_content_type(response_content_type),
                    "jsonSchema": self._schema_from_value(request.response_body or {}),
                },
            ],
            "responseExamples": self._apifox_response_examples(request, response_id),
            "requestBody": self._apifox_request_body(request),
            "description": f"来源 URL：{request.url}",
            "tags": [request.domain] if request.domain else [],
            "status": "released",
            "serverId": "default",
            "operationId": self._operation_id(request),
            "sourceUrl": request.url,
            "ordering": index * 10,
            "cases": [],
            "mocks": [],
            "customApiFields": "{}",
            "advancedSettings": {
                "disabledSystemHeaders": {},
            },
            "mockScript": {},
            "codeSamples": self._apifox_code_samples(request),
            "commonResponseStatus": {},
            "responseChildren": [f"BLANK.{response_id}"],
            "preProcessors": [],
            "postProcessors": [],
            "inheritPostProcessors": {},
            "inheritPreProcessors": {},
        }
        return {
            "name": self._item_name(request),
            "api": api,
        }

    def _apifox_parameters(self, values: dict[str, Any] | None, location: str) -> list[dict[str, Any]]:
        """把 Query、Header、Cookie 参数转换为 Apifox 参数结构。"""
        parameters: list[dict[str, Any]] = []
        for key, value in (values or {}).items():
            if value in (None, ""):
                continue
            parameters.append(
                {
                    "name": str(key),
                    "type": self._apifox_value_type(value),
                    "required": False,
                    "description": f"采集自 {location}",
                    "example": str(value),
                    "value": str(value),
                },
            )
        return parameters

    def _apifox_request_body(self, request: CapturedRequest) -> dict[str, Any]:
        """生成 Apifox 请求体结构，JSON 请求保留可编辑 Schema 和示例。"""
        body = request.request_body
        if body in (None, "", {}):
            return {
                "type": "none",
                "parameters": [],
                "jsonSchema": {
                    "type": "object",
                    "properties": {},
                    "x-apifox-orders": [],
                },
            }
        content_type = self._header_value(self._cleaned_headers(request), "content-type") or "application/json"
        if isinstance(body, dict):
            return {
                "type": "application/json",
                "parameters": [],
                "jsonSchema": self._schema_from_value(body),
                "example": json.dumps(body, ensure_ascii=False, indent=2),
            }
        if isinstance(body, list):
            return {
                "type": "application/json",
                "parameters": [],
                "jsonSchema": self._schema_from_value(body),
                "example": json.dumps(body, ensure_ascii=False, indent=2),
            }
        if "application/x-www-form-urlencoded" in content_type:
            return {
                "type": "application/x-www-form-urlencoded",
                "parameters": [
                    {"name": key, "type": "string", "required": False, "value": value, "example": value}
                    for key, value in parse_qsl(str(body), keep_blank_values=True)
                ],
            }
        return {
            "type": content_type,
            "parameters": [],
            "example": str(body),
        }

    def _apifox_response_examples(self, request: CapturedRequest, response_id: str) -> list[dict[str, Any]]:
        """生成响应示例，导入后可在 Apifox 中直接查看采集结果样例。"""
        if request.response_body in (None, "", {}):
            return []
        body = request.response_body
        example_text = json.dumps(body, ensure_ascii=False, indent=2) if isinstance(body, (dict, list)) else str(body)
        return [
            {
                "id": self._stable_number_id("response-example", request.request_id),
                "name": "采集响应示例",
                "responseId": response_id,
                "data": example_text,
            },
        ]

    def _apifox_code_samples(self, request: CapturedRequest) -> list[dict[str, str]]:
        """把精简 cURL 放入代码示例，方便导入后继续复制调试。"""
        curl = request.clean_curl or request.raw_curl or self._build_curl_from_request(request)
        if not curl:
            return []
        return [
            {
                "name": "cURL",
                "language": "curl",
                "code": curl,
            },
        ]

    def _apifox_project_setting(self, requests: list[CapturedRequest]) -> dict[str, Any]:
        """生成 Apifox 项目设置，包含默认服务地址。"""
        servers = [
            {
                "id": "default",
                "name": "默认服务",
                "url": self._openapi_servers(requests)[0]["url"],
            },
        ]
        return {
            "id": self._stable_number_id("project", self._batch_no(requests)),
            "auth": {},
            "servers": servers,
            "gateway": [],
            "language": "zh-CN",
            "apiStatuses": ["developing", "testing", "released", "deprecated"],
            "mockSettings": {},
            "preProcessors": [],
            "postProcessors": [],
            "advancedSettings": {},
            "initialDisabledMockIds": [],
            "cloudMock": {
                "security": "free",
                "enable": False,
                "tokenKey": "apifoxToken",
            },
        }

    def _apifox_empty_collection(self, name: str) -> dict[str, Any]:
        """生成 Apifox 空集合节点。"""
        return {
            "name": name,
            "children": [],
            "items": [],
        }

    def _apifox_inherit_processor(self, processor_id: str) -> dict[str, Any]:
        """生成 Apifox 继承处理器占位，保持导入结构完整。"""
        return {
            "id": processor_id,
            "type": processor_id,
            "data": {},
        }

    def _apifox_content_type(self, content_type: str) -> str:
        """把响应 Content-Type 规整为 Apifox 常见类型。"""
        normalized = content_type.lower()
        if "json" in normalized:
            return "json"
        if "xml" in normalized:
            return "xml"
        if "html" in normalized:
            return "html"
        return "raw"

    def _apifox_value_type(self, value: Any) -> str:
        """把 Python 值类型转换为 Apifox 参数类型。"""
        schema_type = self._schema_from_value(value).get("type")
        if schema_type in {"integer", "number", "boolean", "array", "object"}:
            return str(schema_type)
        return "string"

    def _stable_number_id(self, prefix: str, value: str) -> str:
        """根据内容生成稳定数字 ID，避免每次导出同一接口都完全变化。"""
        raw = uuid.uuid5(uuid.NAMESPACE_URL, f"{prefix}:{value}").int
        return str(raw % 900000000 + 100000000)

    def _postman_request_item(self, request: CapturedRequest) -> dict[str, Any]:
        """按 Postman Collection v2.1 request 结构组装 method、url、headers 和 body。"""
        headers = self._postman_headers(request)
        item: dict[str, Any] = {
            "method": request.method.upper(),
            "header": headers,
            "url": self._postman_url(request),
        }
        body = self._postman_body(request.request_body, headers)
        if body:
            item["body"] = body
        return item

    def _postman_headers(self, request: CapturedRequest) -> list[dict[str, str]]:
        """复用 cURL 清洗规则，去掉浏览器噪音 Header，保留接口调试必要 Header。"""
        cleaned_headers = self._cleaned_headers(request)
        headers: list[dict[str, str]] = []
        has_cookie_header = False
        for key, value in cleaned_headers.items():
            if value in (None, ""):
                continue
            if key.lower() == "cookie":
                has_cookie_header = True
            headers.append({"key": key, "value": str(value), "type": "text"})

        cookie_text = self._cookie_string(request.cookies)
        if cookie_text and not has_cookie_header:
            headers.append({"key": "Cookie", "value": cookie_text, "type": "text"})

        if request.request_body not in (None, "", {}) and not self._header_value(cleaned_headers, "content-type"):
            headers.append({"key": "Content-Type", "value": "application/json", "type": "text"})
        return headers

    def _postman_url(self, request: CapturedRequest) -> dict[str, Any]:
        """把原始 URL 拆成 Postman 可识别的 protocol、host、path 和 query。"""
        parsed = urlparse(request.url)
        query_items = self._query_items(parsed.query, request.query_params)
        return {
            "raw": request.url,
            "protocol": parsed.scheme,
            "host": [part for part in parsed.netloc.split(".") if part],
            "path": [unquote(part) for part in parsed.path.split("/") if part],
            "query": query_items,
        }

    def _postman_body(self, body: Any, headers: list[dict[str, str]]) -> dict[str, Any] | None:
        """根据请求体类型生成 Postman body，JSON 对象会直接作为 raw JSON 导入。"""
        if body in (None, "", {}):
            return None
        content_type = self._header_value_from_items(headers, "content-type").lower()
        if "application/x-www-form-urlencoded" in content_type and isinstance(body, str):
            return {
                "mode": "urlencoded",
                "urlencoded": [
                    {"key": key, "value": value, "type": "text"}
                    for key, value in parse_qsl(body, keep_blank_values=True)
                ],
            }
        if isinstance(body, (dict, list)):
            return self._postman_raw_body(json.dumps(body, ensure_ascii=False, indent=2), "json")

        body_text = str(body)
        language = "json" if self._can_parse_json(body_text) else "text"
        return self._postman_raw_body(body_text, language)

    def _postman_raw_body(self, raw: str, language: str) -> dict[str, Any]:
        """生成 Postman raw body，并指定语言方便 Postman 高亮展示。"""
        return {
            "mode": "raw",
            "raw": raw,
            "options": {
                "raw": {
                    "language": language,
                },
            },
        }

    def _query_items(self, raw_query: str, fallback_params: dict[str, Any] | None) -> list[dict[str, str]]:
        """优先使用 URL 原始 query，缺失时再使用系统解析出的 query_params。"""
        pairs = parse_qsl(raw_query, keep_blank_values=True)
        if not pairs and fallback_params:
            for key, value in fallback_params.items():
                if isinstance(value, list):
                    pairs.extend((str(key), str(item)) for item in value)
                else:
                    pairs.append((str(key), str(value)))
        return [{"key": key, "value": value} for key, value in pairs]

    def _cleaned_headers(self, request: CapturedRequest) -> dict[str, Any]:
        """统一清洗浏览器 Header，避免导出文件夹带 sec-fetch、ua 等噪音字段。"""
        return self.curl_service.clean_headers(request.request_headers)

    def _build_curl_from_request(self, request: CapturedRequest) -> str:
        """当历史数据缺少 cURL 字段时，按当前请求结构补生成精简 cURL。"""
        return self.curl_service.build_curl(
            request.method,
            request.url,
            request.request_headers,
            request.cookies,
            request.request_body,
            clean=True,
        )

    def _header_value(self, headers: dict[str, Any], target_key: str) -> str:
        """按不区分大小写的方式读取 Header 字典值。"""
        for key, value in headers.items():
            if key.lower() == target_key:
                return str(value)
        return ""

    def _header_value_from_items(self, headers: list[dict[str, str]], target_key: str) -> str:
        """按不区分大小写的方式读取 Postman Header 列表值。"""
        for header in headers:
            if header["key"].lower() == target_key:
                return header["value"]
        return ""

    def _first_content_type(self, headers: dict[str, Any] | None) -> str:
        """从响应头中提取 Content-Type，缺失时由调用方使用默认值。"""
        for key, value in (headers or {}).items():
            if key.lower() == "content-type":
                return str(value).split(";")[0]
        return ""

    def _cookie_string(self, cookies: dict[str, Any] | None) -> str:
        """把 Cookie 字典拼成可导入的 Cookie Header。"""
        if not cookies:
            return ""
        return "; ".join(f"{key}={value}" for key, value in cookies.items())

    def _can_parse_json(self, value: str) -> bool:
        """判断字符串是否为 JSON，用于决定 Postman raw body 的高亮语言。"""
        try:
            json.loads(value)
            return True
        except json.JSONDecodeError:
            return False

    def _operation_id(self, request: CapturedRequest) -> str:
        """生成 OpenAPI operationId，避免中文或特殊字符影响导入。"""
        raw = f"{request.method.lower()}_{request.domain}_{request.path}".strip("_")
        safe = re.sub(r"[^A-Za-z0-9_]+", "_", raw).strip("_")
        return safe[:120] or f"request_{request.id}"

    def _item_name(self, request: CapturedRequest) -> str:
        """用方法和路径命名请求，导入工具后更容易识别。"""
        return f"{request.method.upper()} {request.path or request.url}"

    def _batch_no(self, requests: list[CapturedRequest]) -> str:
        """提取批次号；空导出时使用当前时间保证文件名唯一。"""
        if requests and requests[0].batch:
            return requests[0].batch.batch_no
        return datetime.now().strftime("%Y%m%d%H%M%S")

    def _safe_filename(self, prefix: str, batch_no: str, extension: str) -> str:
        """生成安全文件名，避免特殊字符影响下载。"""
        raw_name = f"{prefix}_{batch_no}.{extension}"
        safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", raw_name).strip("_")
        return safe_name or f"{prefix}.{extension}"
