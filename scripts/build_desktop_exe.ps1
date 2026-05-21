param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

Set-Location $ProjectRoot

Write-Host "1/4 Build frontend dist..."
# 先构建前端静态资源，PyInstaller 会把 dist 目录打进桌面版运行包。
Push-Location (Join-Path $ProjectRoot "frontend")
npm run build
Pop-Location

Write-Host "2/4 Prepare desktop runtime resources..."
$backendDir = Join-Path $ProjectRoot "backend"
$runtimeDriverDir = Join-Path $backendDir "runtime\drivers"
$driverPath = Join-Path $runtimeDriverDir "chromedriver.exe"
New-Item -ItemType Directory -Path $runtimeDriverDir -Force | Out-Null
if (-not (Test-Path $driverPath)) {
  throw "Bundled chromedriver is missing: $driverPath"
}

# 桌面版默认使用 SQLite 和内置驱动，避免用户机器必须安装 MySQL 或手动配置环境。
$desktopEnv = Join-Path $ProjectRoot "config\desktop.env.example"
$backendEnv = Join-Path $backendDir ".env"
Copy-Item $desktopEnv $backendEnv -Force

Write-Host "3/4 Install PyInstaller..."
# 打包机需要 PyInstaller；普通用户运行 exe 时不需要 Python 环境。
python -m pip install pyinstaller

Write-Host "4/4 Package desktop launcher exe..."
Push-Location $backendDir
python -m PyInstaller `
  --noconfirm `
  --clean `
  --name "NetworkCaptureTool" `
  --console `
  --add-data "app;app" `
  --add-data "..\frontend\dist;frontend\dist" `
  --add-data "runtime\drivers;runtime\drivers" `
  --add-data ".env;." `
  --hidden-import "pymysql" `
  --hidden-import "sqlite3" `
  --hidden-import "fastapi" `
  --hidden-import "starlette" `
  --hidden-import "sqlalchemy" `
  --hidden-import "pydantic_settings" `
  --hidden-import "selenium" `
  --hidden-import "selenium.webdriver.chrome.webdriver" `
  --hidden-import "websocket" `
  --hidden-import "uvicorn.logging" `
  --hidden-import "uvicorn.loops.auto" `
  --hidden-import "uvicorn.protocols.http.auto" `
  --hidden-import "uvicorn.protocols.websockets.auto" `
  desktop_launcher.py
Pop-Location

# 只保留最终可运行目录，清理 PyInstaller 中间产物，避免项目目录越来越乱。
$exePath = Join-Path $backendDir "dist\NetworkCaptureTool\NetworkCaptureTool.exe"
$buildDir = Join-Path $backendDir "build"
$specFile = Join-Path $backendDir "NetworkCaptureTool.spec"
if (Test-Path $buildDir) {
  Remove-Item -LiteralPath $buildDir -Recurse -Force
}
if (Test-Path $specFile) {
  Remove-Item -LiteralPath $specFile -Force
}
Write-Host "Build completed: $exePath"
