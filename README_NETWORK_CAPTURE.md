# 接口捕获软件

接口捕获软件用于从受控浏览器真实操作中采集网络请求，并把请求参数、Cookie、令牌、响应、cURL 和批量导出文件结构化展示，方便迁移到接口自动化测试、Postman 或 Apifox。

## 目录结构

- `backend/`：FastAPI 后端，负责浏览器控制、CDP 网络监听、请求解析、数据库读写和导出。
- `frontend/`：Vue 前端，负责请求列表、详情弹窗、背景设置和批量导出交互。
- `database/`：MySQL 部署脚本；桌面版默认使用 SQLite，无需手动导入。
- `docs/api_test_requirements.md`：当前需求文档。
- `docs/api/network_capture_api.md`：接口文档。
- `docs/ui_design/`：当前 UI 图与设计源文件。
- `scripts/build_desktop_exe.ps1`：桌面版 exe 打包脚本。

## 桌面版启动

```powershell
cd "D:\Code\Claude Coding\接口捕获软件"
.\backend\dist\NetworkCaptureTool\NetworkCaptureTool.exe
```

启动后终端会显示访问地址，默认是：

```text
http://127.0.0.1:8710/
```

软件不会自动打开网页，请复制终端中的地址到浏览器自行访问。

## 桌面版运行环境

- 需要 Windows。
- 需要本机安装兼容版本 Chrome。
- 不需要用户安装 Python、Node、npm 或 MySQL。
- 数据默认保存在 `backend/dist/NetworkCaptureTool/runtime/network_capture_studio.db`。
- 公司内网站点需要本机网络或 SASE 能正常访问。

## 源码开发启动

后端：

```powershell
cd "D:\Code\Claude Coding\接口捕获软件\backend"
pip install -r requirements.txt
copy .env.example .env
python run.py
```

前端：

```powershell
cd "D:\Code\Claude Coding\接口捕获软件\frontend"
npm install
npm run dev
```

源码开发默认前端地址：`http://127.0.0.1:5173`

## 当前能力

- 启动受控 Chrome 并访问目标网址。
- 采集受控浏览器所有标签页的网络请求。
- 重复请求路径只保留最新一条。
- 新采集请求显示 `NEW`，点击详情后立即消失。
- 查看 Query、Headers、Cookie、Body、响应、令牌和 cURL。
- Body 参数可单独复制为 JSON。
- 支持一键清空当前采集。
- 支持历史批次查看。
- 支持自定义背景图片和预设背景。
- 支持批量导出 Postman、OpenAPI、cURL、Apifox 文件。
- 记录用户关键操作日志和系统异常日志。

## 打包

```powershell
cd "D:\Code\Claude Coding\接口捕获软件"
powershell -NoProfile -ExecutionPolicy Bypass -File .\scripts\build_desktop_exe.ps1
```

生成文件：

```text
backend\dist\NetworkCaptureTool\NetworkCaptureTool.exe
```

## 注意事项

- 如果浏览器启动失败，请检查 Chrome 是否安装、内置 `chromedriver.exe` 是否存在，以及端口是否被占用。
- 如果目标站反复提示 token 无效，请在页面点击“重置登录态”。
- 如需彻底免 Chrome 环境，可后续把 Chrome for Testing 一并内置。
