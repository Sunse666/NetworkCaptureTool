# NetworkCaptureTool 接口捕获软件

NetworkCaptureTool 是一款面向接口自动化测试准备阶段的桌面工具。它通过内置浏览器驱动启动受控 Chrome，自动采集用户真实操作过程中产生的网络请求，并把请求参数、Cookie、令牌、响应、cURL 和批量导出文件结构化展示，帮助测试人员更快把网页操作沉淀为接口测试资产。

![界面预览](docs/ui_design/network_capture_dashboard.png)

## 核心能力

- 通过受控 Chrome 采集真实网页操作产生的接口请求。
- 支持多标签页请求捕获，用户在浏览器中继续跳转或打开新页面也可采集。
- 同一批次内相同 `method + domain + path` 的请求只保留最新一条。
- 新增请求显示 `NEW`，点击详情后自动清除标记。
- 可视化查看 Query、Body、Headers、Cookie、令牌、响应和精简 cURL。
- Body 参数可单独复制为标准 JSON。
- 支持自定义背景图片、历史批次查看和当前采集一键清空。
- 支持批量导出 Postman Collection、OpenAPI 3.0、Apifox 项目 JSON 和 cURL 文本。
- 桌面版默认使用 SQLite，本地保存数据；团队部署时也可切换 MySQL。

## 运行原理

```text
用户启动桌面程序
        |
        v
本机启动 FastAPI 服务
        |
        v
Vue 页面输入目标网站
        |
        v
Selenium + ChromeDriver 启动受控 Chrome
        |
        v
Chrome DevTools Protocol 监听网络请求
        |
        v
后端解析请求参数、响应、Cookie、令牌与 cURL
        |
        v
SQLite / MySQL 持久化，前端可视化展示与批量导出
```

## 项目结构

```text
backend/      后端服务、浏览器控制、请求解析、数据库读写、批量导出
frontend/     前端页面、请求列表、详情表单、设置面板、导出交互
database/     MySQL 初始化与补丁脚本，桌面版默认使用 SQLite
docs/         需求文档、接口文档、UI 图
scripts/      桌面版 exe 打包脚本
```

## 桌面版启动

```powershell
cd "D:\Code\Claude Coding\接口捕获软件"
.\backend\dist\NetworkCaptureTool\NetworkCaptureTool.exe
```

启动后终端会显示本地访问地址，默认是：

```text
http://127.0.0.1:8710/
```

软件不会自动打开网页，请复制终端中的地址到浏览器访问。

## 源码开发启动

后端：

```powershell
# 启动后端服务
cd "...\NetworkCaptureTool\backend"
pip install -r requirements.txt
copy .env.example .env
python run.py
```

前端：

```powershell
# 启动前端开发服务
cd "..\NetworkCaptureTool\frontend"
npm install
npm run dev
```

源码开发默认前端地址：

```text
http://127.0.0.1:5173/
```

## 打包桌面版

```powershell
# 构建前端并打包桌面 exe
cd "...\NetworkCaptureTool"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop_exe.ps1
```

生成文件：

```text
backend\dist\NetworkCaptureTool\NetworkCaptureTool.exe
```

## 与同类工具相比

Charles、Fiddler 更偏通用代理抓包，能力强但配置门槛较高；NetworkCaptureTool 更聚焦“从网页真实操作到接口自动化资产”的中间环节，不强依赖代理证书配置，并且内置参数可视化、精简 cURL、重复请求收敛和批量导出能力。

Postman、Apifox 更适合已有接口后的管理、调试和团队协作；NetworkCaptureTool 更适合在前置阶段从真实页面行为中批量捕获接口，再导入这些平台继续维护。

## 注意事项

- 桌面版需要 Windows 和本机已安装兼容版本 Chrome。
- 公司内网站点需要本机网络或 SASE 能正常访问。
- 如果目标站反复提示 token 无效，可在页面点击“重置登录态”后重新登录。
- 仓库不会提交运行数据库、浏览器缓存、Cookie、日志、虚拟环境、依赖目录和打包产物。
