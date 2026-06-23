# NetworkCaptureTool

一款面向接口自动化测试准备阶段的桌面工具。通过内置浏览器驱动启动受控 Chromium 浏览器，自动采集用户真实操作过程中产生的网络请求，在同一浏览器窗口中展示前端面板和采集目标，把请求参数、Cookie、令牌、响应、cURL 和批量导出文件结构化展示。

<img width="1887" height="1053" alt="image" src="https://github.com/user-attachments/assets/37c83651-3558-4d0a-9152-7bd4ebcecb9b" />

## 项目定位

传统接口测试往往需要先打开浏览器开发者工具，手动复制请求、整理 Header、处理 Cookie、清理浏览器噪音参数，再导入 Postman、Apifox 或自动化测试脚本。这个过程重复、容易漏字段，也不适合批量处理。

接口捕获软件的目标是把这条链路变短：

- 从真实浏览器操作中自动采集请求。
- 自动按请求方法、接口类型和请求路径整理数据。
- 提供可视化参数视图，减少手工翻找成本。
- 一键生成精简 cURL，并支持批量导出到 Postman、OpenAPI、Apifox 和 cURL 文本。
- 复用浏览器用户目录，保留 Cookie、LocalStorage 和 SessionStorage，减少反复登录。
- **同一浏览器窗口**内完成前端面板操作和网页采集，不来回切换窗口。

## 核心特点

- **同一浏览器采集**：前端面板和被采集网页在**同一个浏览器窗口**中打开，前端面板先加载，目标网站在新标签页打开，不需要在两个窗口之间切换。
- **多标签页覆盖**：用户在受控浏览器中手动打开新标签页、跳转页面或继续操作，后续请求仍可被采集。
- **多浏览器支持**：支持 Chrome、Edge、Brave 等 Chromium 内核浏览器，以及 Windows 11 内置的 Edge WebView2 Runtime，通过 Provider 模式按需切换。
- **用户浏览器配置复用**：可配置使用你自己的浏览器用户目录，采集时复用日常的登录态、Cookie、书签和扩展。
- **重复请求自动收敛**：同一批次内相同 `method + domain + path` 的请求只保留最新一条，避免列表被轮询请求刷屏。
- **NEW 标记机制**：新采集请求会标记 `NEW`，点击查看详情后立即消失，方便快速识别新增接口。
- **参数可视化**：Query、Body、Headers、Cookie、令牌、响应和 cURL 分页展示，Body 可单独复制为标准 JSON。
- **精简 cURL**：自动剔除常见浏览器噪音 Header，如 `sec-fetch-*`、`sec-ch-ua-*`、`user-agent` 等，只保留接口测试更关注的信息。
- **批量导出**：选中多个请求后，可批量导出 Postman Collection、OpenAPI 3.0、Apifox 项目 JSON 或 cURL 文本。
- **详情页异步加载**：查看请求详情时立即展示参数和 Headers，响应体后台异步加载，不阻塞首屏。
- **桌面即用**：打包后以 exe 运行，普通用户不需要安装 Python、Node、npm 或 MySQL。
- **本地优先**：桌面版默认使用 SQLite，本地存储采集数据；团队部署时也可切换 MySQL。
- **可扩展架构**：后端按 API、Service、Repository、Model、Schema 分层，浏览器引擎通过 Provider 模式抽象（`browser_providers/`），后续扩展导出格式或新增浏览器支持更容易。

## 运行原理

软件本质上由四层组成：

1. **桌面启动层**：用户启动 `NetworkCaptureTool.exe` 后，程序在本机启动一个 FastAPI 服务，自动打开浏览器加载前端面板。
2. **前端交互层**：用户通过 Vue 页面输入目标网址、查看请求列表、查看详情、切换背景、批量导出接口文件。
3. **浏览器采集层**：后端通过 Selenium + ChromeDriver（或 EdgeDriver）启动/接管受控浏览器，开启 Chrome DevTools Protocol 网络监听。
4. **数据处理层**：后端解析 CDP 网络事件，提取请求参数、响应、Cookie、令牌、cURL，并写入 SQLite 或 MySQL。

简化流程如下：

```text
# 用户启动桌面程序
NetworkCaptureTool.exe

# 桌面程序启动本地服务，自动打开浏览器面板
FastAPI Service -> http://127.0.0.1:8710/

# 用户在网页端输入目标网站
Vue UI -> POST /api/capture/start

# 同一浏览器的同一窗口中打开新标签页访问目标网站
Selenium + ChromeDriver + CDP Network

# 用户在浏览器新标签页中登录、点击、跳转
Chrome Network Events -> Request Parser

# 后端结构化保存请求
SQLite / MySQL -> captured_requests

# 前端轮询同步并展示请求
Vue UI -> POST /api/capture/sync
```

## 浏览器引擎选择

工具支持多种 Chromium 内核浏览器，通过 `.env` 文件中的 `BROWSER_TYPE` 配置切换：

| 浏览器 | `BROWSER_TYPE` | 说明 |
|--------|---------------|------|
| Edge WebView2 | `webview2` | Windows 11 预装，零额外安装 |
| Google Chrome | `chrome` | 默认检测系统 Chrome |
| Edge / Brave / Vivaldi 等 | `chrome` + `CHROME_BINARY` | 指定浏览器 exe 路径 |

### 使用你自己的浏览器配置

默认使用独立的浏览器用户目录（`runtime/chrome-profile`），每次都是全新的登录态。如果要复用你日常使用的浏览器配置（Cookie、书签、扩展），在 `.env` 中设置：

```ini
# 浏览器引擎（chrome / webview2）
BROWSER_TYPE=chrome

# 浏览器可执行文件路径（Chromium 系浏览器均可）
CHROME_BINARY=D:\tools\baifen\chrome.exe

# 使用你自己的浏览器用户目录（关闭浏览器后启动工具）
BROWSER_USER_DATA_DIR=D:\tools\baifen\User Data

# 自动打开浏览器面板（启动工具时自动打开前端）
AUTO_LAUNCH_BROWSER=true
```

> **注意**：Chrome/Chromium 会锁定用户目录。如果要使用你自己的浏览器配置，需要**先关闭**正在运行的浏览器，再启动工具。

### 同一浏览器窗口工作流

启动工具后：
1. 浏览器自动打开，Tab 1 显示前端面板
2. 输入目标网址 → 点击「启动采集」
3. Tab 2 在**同一窗口**中打开目标网站
4. 在目标网站操作（登录、点击、跳转）
5. 切回 Tab 1 查看采集到的请求

## 和同类工具相比的优势

### 对比 Charles / Fiddler

Charles 和 Fiddler 更偏通用网络代理与抓包调试，能力强，但使用门槛也更高，尤其是 HTTPS 证书、代理配置、移动端抓包、复杂过滤规则等。

本软件的优势是：

- 不以代理为核心，不强依赖证书配置，更适合桌面网页接口采集。
- 直接从受控浏览器真实操作中采集请求，测试人员使用路径更接近日常网页操作。
- 自动面向接口自动化整理参数，而不是停留在原始网络包视角。
- 自带批量导出 Postman、OpenAPI、Apifox 和 cURL，更贴近接口测试落地。
- 对重复路径请求自动保留最新，减少广告、轮询、埋点请求带来的干扰。

### 对比浏览器 DevTools Network

浏览器开发者工具适合临时排查，但不适合长期整理接口资产。

本软件的优势是：

- 可持久化保存采集记录，支持历史批次查看。
- 可视化详情更聚焦接口参数，而不是浏览器内部网络面板。
- 支持批量选择和批量导出，减少逐条复制。
- 支持精简 cURL，自动过滤接口测试不需要的浏览器 Header。
- 支持点击后清除 `NEW` 标记，便于连续操作时追踪新增接口。

### 对比 Postman / Apifox

Postman 和 Apifox 是优秀的接口管理与调试工具，但它们更适合"已有接口"后的管理、调试、断言和团队协作。

本软件更适合做前置采集：

- 先从真实网页操作中批量捕获接口。
- 再把整理后的接口批量导入 Postman 或 Apifox。
- 适合从零梳理目标网站接口，或把手工测试流程转换为接口自动化素材。

## 快速启动

### 源码开发启动

```powershell
# 启动后端服务
cd backend
pip install -r requirements.txt
copy ..\config\desktop.env.example .env
python run.py
```

```powershell
# 启动前端开发服务（可选，后端已内置前端构建产物）
cd frontend
npm install
npm run dev
```

### 桌面版打包

```powershell
# 构建前端并打包桌面 exe
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop_exe.ps1

# 启动桌面版
.\backend\dist\NetworkCaptureTool\NetworkCaptureTool.exe
```

### 环境变量配置

| 变量 | 默认值 | 说明 |
|------|--------|------|
| `APP_HOST` | `127.0.0.1` | 服务监听地址 |
| `APP_PORT` | `8710` | 服务端口 |
| `DATABASE_ENGINE` | `sqlite` | 数据库引擎（sqlite / mysql） |
| `BROWSER_TYPE` | `webview2` | 浏览器类型（chrome / webview2） |
| `CHROME_BINARY` | — | Chromium 浏览器 exe 路径 |
| `CHROMEDRIVER_PATH` | `runtime/drivers/chromedriver.exe` | ChromeDriver 路径 |
| `MSEDGEDRIVER_PATH` | `runtime/drivers/msedgedriver.exe` | Edge WebDriver 路径 |
| `BROWSER_USER_DATA_DIR` | `runtime/chrome-profile` | 浏览器用户目录（设为日常使用的目录可复用登录态） |
| `EDGE_USER_DATA_DIR` | `runtime/edge-profile` | WebView2 用户目录 |
| `AUTO_LAUNCH_BROWSER` | `true` | 启动时自动打开浏览器面板 |
| `BROWSER_HEADLESS` | `false` | 无头模式 |

## 当前导出格式

| 格式 | 用途 |
| --- | --- |
| Postman Collection v2.1 | 直接导入 Postman 进行调试和集合管理 |
| OpenAPI 3.0 | 导入 Swagger、Apifox 或其它接口平台 |
| Apifox 项目 JSON | 面向 Apifox 导入结构做了适配 |
| cURL 文本 | 适合命令行复现、脚本改造或快速粘贴 |

## 项目结构

```text
# 后端服务、浏览器控制、请求解析、数据库写入、批量导出
backend/
  app/
    api/routes/         # FastAPI 路由
    core/               # 配置、数据库、异常处理
    models/             # SQLAlchemy 数据模型
    repositories/       # 数据访问层
    schemas/            # Pydantic 入参/出参 Schema
    services/           # 业务逻辑层
      browser_providers/  # 浏览器引擎抽象（Chrome / WebView2 Provider）
      batch_export_service.py  # 批量导出（Postman/OpenAPI/Apifox/cURL）
      browser_service.py       # 浏览器控制
      capture_service.py       # 采集主控
      curl_service.py          # cURL 生成与清洗
      request_parser.py        # CDP 事件解析
  desktop_launcher.py  # 桌面版启动入口
  run.py                # 源码开发启动入口

# 前端页面、请求列表、详情弹窗、设置面板、批量导出交互
frontend/

# MySQL 初始化与补丁脚本，桌面版默认使用 SQLite
database/

# 桌面版打包脚本
scripts/

# 桌面版环境变量示例
config/
```
