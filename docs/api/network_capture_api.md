# 接口捕获软件接口文档

## 通用响应

所有业务接口统一返回：

```json
{
  "success": true,
  "code": "OK",
  "message": "操作成功",
  "data": {}
}
```

异常响应示例：

```json
{
  "success": false,
  "code": "URL_EMPTY",
  "message": "请输入目标网站地址。",
  "data": null
}
```

## 健康检查

### GET `/api/health`

检查后端服务和数据库状态。

响应示例：

```json
{
  "success": true,
  "code": "OK",
  "message": "服务运行正常。",
  "data": {
    "status": "ok",
    "database": {
      "ready": true,
      "message": "数据库连接正常。",
      "detail": ""
    }
  }
}
```

## 当前采集

### POST `/api/capture/start`

启动受控浏览器并创建新采集批次。启动新批次时，历史请求的 `NEW` 标记会自动移除。

请求体：

```json
{
  "url": "https://www.baidu.com/"
}
```

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `batch_no` | string | 采集批次编号 |
| `target_url` | string | 目标网址 |
| `status` | string | 批次状态 |
| `started_at` | string | 开始时间 |
| `ended_at` | string/null | 结束时间 |
| `total_count` | number | 请求总数 |
| `api_count` | number | 接口请求数 |

### POST `/api/capture/sync`

同步受控浏览器中新产生的网络请求。

说明：

- 不传 `batch_no` 时使用当前批次。
- 同一批次内相同 `method + domain + path` 的重复请求会保留最新一条。
- 返回本次新增或更新的请求摘要列表。

Query 参数：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `batch_no` | 否 | 指定采集批次 |

### POST `/api/capture/reset-profile`

关闭当前浏览器并清理内置 Chrome 用户目录。

适用场景：

- 目标站反复提示 token 无效。
- 登录态过期。
- Cookie、LocalStorage 或 SessionStorage 被污染。

### POST `/api/capture/stop-browser`

关闭当前受控浏览器并结束当前采集批次。当前前端不展示独立按钮，接口保留给调试、桌面关闭兜底或外部自动化调用。

### DELETE `/api/capture/current`

清空当前批次的请求列表，不删除历史批次。

请求体：

```json
{
  "batch_no": "20260521153021"
}
```

## 请求记录

### GET `/api/requests`

查询请求列表。

Query 参数：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `batch_no` | 否 | 批次编号 |
| `method` | 否 | 请求方法，如 `GET`、`POST`、`ALL` |
| `keyword` | 否 | URL 关键字 |
| `only_api` | 否 | 是否只看接口请求，默认 `true` |
| `limit` | 否 | 返回条数，范围 1 到 1000，默认 `200` |

列表响应项关键字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `id` | number | 数据库主键 |
| `request_id` | string | 浏览器请求 ID |
| `batch_no` | string | 批次编号 |
| `method` | string | 请求方法 |
| `url` | string | 完整 URL |
| `domain` | string | 域名 |
| `path` | string | 请求路径 |
| `status_code` | number/null | HTTP 状态码 |
| `is_new` | boolean | 是否为当前批次新增且未查看 |
| `is_api` | boolean | 是否识别为接口请求 |
| `dynamic_marks` | array | 动态参数标记 |

### GET `/api/requests/{request_id}`

查询单条请求详情。查询详情后，该请求的 `NEW` 标记会被清除。

详情响应关键字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `query_params` | object | Query 参数 |
| `request_headers` | object | 原始请求头 |
| `cookies` | object | 原始 Cookie |
| `request_body` | object/string/null | 请求体 |
| `response_headers` | object | 响应头 |
| `response_body` | object/string/null | 响应体 |
| `raw_curl` | string/null | 完整 cURL |
| `clean_curl` | string/null | 精简 cURL |
| `auth_tokens` | array | 从 Header、Cookie、Query、Body 中识别出的令牌字段 |

### POST `/api/requests/export`

把用户勾选的多条请求批量导出为指定格式文件。

支持格式：

| format | 文件内容 | 使用场景 |
| --- | --- | --- |
| `postman` | Postman Collection v2.1 JSON | 直接导入 Postman |
| `openapi` | OpenAPI 3.0 JSON | 导入 Swagger、Apifox 或其它接口平台 |
| `curl` | 多条精简 cURL 文本 | 命令行回放或粘贴到接口平台 |
| `apifox` | Apifox 项目格式 JSON | 通过 Apifox 数据导入入口导入 |

请求体：

```json
{
  "request_ids": [12, 18, 21],
  "format": "postman"
}
```

响应字段：

| 字段 | 类型 | 说明 |
| --- | --- | --- |
| `filename` | string | 建议下载文件名 |
| `content_type` | string | 文件 MIME 类型 |
| `format` | string | 实际导出格式 |
| `data` | object/string | 文件内容，JSON 格式返回 object，cURL 返回 string |

响应示例：

```json
{
  "success": true,
  "code": "OK",
  "message": "批量导出文件已生成。",
  "data": {
    "filename": "postman_collection_20260521153021.json",
    "content_type": "application/json;charset=utf-8",
    "format": "postman",
    "data": {
      "info": {
        "name": "接口捕获 - Postman 批量导出 20260521153021",
        "schema": "https://schema.getpostman.com/json/collection/v2.1.0/collection.json"
      },
      "item": []
    }
  }
}
```

## 历史采集

### GET `/api/history/batches`

查询历史采集批次。

Query 参数：

| 字段 | 必填 | 说明 |
| --- | --- | --- |
| `keyword` | 否 | 按目标网址模糊查询 |

## 设置管理

### GET `/api/settings/{key}`

读取指定设置，例如 `background`。

### PUT `/api/settings`

保存指定设置。

请求体示例：

```json
{
  "key": "background",
  "value": {
    "mode": "image",
    "preset": "aurora",
    "image_path": "data:image/png;base64,...",
    "blur": 18,
    "opacity": 0.52
  },
  "description": "用户界面背景设置"
}
```
