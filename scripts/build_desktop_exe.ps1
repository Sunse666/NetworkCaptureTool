param(
  [string]$ProjectRoot = (Resolve-Path (Join-Path $PSScriptRoot "..")).Path
)

$ErrorActionPreference = "Stop"

Set-Location $ProjectRoot

Write-Host "1/4 Build frontend dist..."
# Build frontend static assets before packaging them into the desktop bundle.
Push-Location (Join-Path $ProjectRoot "frontend")
npm run build
Pop-Location

Write-Host "2/4 Prepare desktop runtime resources..."
$backendDir = Join-Path $ProjectRoot "backend"
$runtimeDriverDir = Join-Path $backendDir "runtime\drivers"
$chromeDriverPath = Join-Path $runtimeDriverDir "chromedriver.exe"
$edgeDriverPath = Join-Path $runtimeDriverDir "msedgedriver.exe"
New-Item -ItemType Directory -Path $runtimeDriverDir -Force | Out-Null
$hasChromeDriver = Test-Path $chromeDriverPath
$hasEdgeDriver = Test-Path $edgeDriverPath
if (-not $hasChromeDriver -and -not $hasEdgeDriver) {
  throw "No bundled browser driver found. At least one of chromedriver.exe or msedgedriver.exe must exist in $runtimeDriverDir"
}
if (-not $hasChromeDriver) {
  Write-Host "Warning: chromedriver.exe missing, Chrome browser support unavailable." -ForegroundColor Yellow
}
if (-not $hasEdgeDriver) {
  Write-Host "Warning: msedgedriver.exe missing, WebView2 browser support unavailable." -ForegroundColor Yellow
}

# Desktop defaults use SQLite and the bundled driver.
$desktopEnv = Join-Path $ProjectRoot "config\desktop.env.example"
$backendEnv = Join-Path $backendDir ".env"
Copy-Item $desktopEnv $backendEnv -Force

Write-Host "3/4 Install PyInstaller..."
# PyInstaller is only needed on the build machine.
python -m pip install pyinstaller

Write-Host "4/4 Package desktop launcher exe..."
$packageDistDir = Join-Path $backendDir "dist\.package"
if (Test-Path $packageDistDir) {
  Remove-Item -LiteralPath $packageDistDir -Recurse -Force
}

Push-Location $backendDir
python -m PyInstaller `
  --noconfirm `
  --clean `
  --name "NetworkCaptureTool" `
  --console `
  --distpath "$packageDistDir" `
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
  --hidden-import "selenium.webdriver.edge.webdriver" `
  --hidden-import "uvicorn.logging" `
  --hidden-import "uvicorn.loops.auto" `
  --hidden-import "uvicorn.protocols.http.auto" `
  --hidden-import "uvicorn.protocols.websockets.auto" `
  desktop_launcher.py
Pop-Location

# Replace only program files and keep runtime data, so active Chrome profile tabs are not touched.
$exePath = Join-Path $backendDir "dist\NetworkCaptureTool\NetworkCaptureTool.exe"
$targetDir = Split-Path $exePath
$targetInternalDir = Join-Path $targetDir "_internal"
$packagedDir = Join-Path $packageDistDir "NetworkCaptureTool"
$packagedExePath = Join-Path $packagedDir "NetworkCaptureTool.exe"
$packagedInternalDir = Join-Path $packagedDir "_internal"

if (-not (Test-Path $packagedExePath) -or -not (Test-Path $packagedInternalDir)) {
  throw "Packaged app is incomplete: $packagedDir"
}

if (Test-Path $exePath) {
  $resolvedExePath = (Resolve-Path $exePath).Path
  Get-CimInstance Win32_Process |
    Where-Object { $_.Name -eq "NetworkCaptureTool.exe" -and $_.ExecutablePath -eq $resolvedExePath } |
    ForEach-Object {
      try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
    }
  $deadline = (Get-Date).AddSeconds(10)
  while ((Get-Date) -lt $deadline) {
    $stillRunning = Get-CimInstance Win32_Process |
      Where-Object { $_.Name -eq "NetworkCaptureTool.exe" -and $_.ExecutablePath -eq $resolvedExePath } |
      Select-Object -First 1
    if (-not $stillRunning) { break }
    Start-Sleep -Milliseconds 200
  }
}
if (Test-Path $targetInternalDir) {
  $resolvedInternalDir = (Resolve-Path $targetInternalDir).Path
  Get-CimInstance Win32_Process |
    Where-Object {
      $_.Name -eq "chromedriver.exe" -and
      ($_.ExecutablePath -like "$resolvedInternalDir*" -or $_.CommandLine -like "*$resolvedInternalDir*")
    } |
    ForEach-Object {
      try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
    }
  Start-Sleep -Milliseconds 500
}

New-Item -ItemType Directory -Path $targetDir -Force | Out-Null
if (Test-Path $exePath) {
  Remove-Item -LiteralPath $exePath -Force
}
if (Test-Path $targetInternalDir) {
  Remove-Item -LiteralPath $targetInternalDir -Recurse -Force
}
Copy-Item -LiteralPath $packagedExePath -Destination $exePath -Force
Copy-Item -LiteralPath $packagedInternalDir -Destination $targetInternalDir -Recurse -Force

$buildDir = Join-Path $backendDir "build"
$specFile = Join-Path $backendDir "NetworkCaptureTool.spec"
if (Test-Path $buildDir) {
  Remove-Item -LiteralPath $buildDir -Recurse -Force
}
if (Test-Path $specFile) {
  Remove-Item -LiteralPath $specFile -Force
}
if (Test-Path $packageDistDir) {
  Remove-Item -LiteralPath $packageDistDir -Recurse -Force
}
Write-Host "Build completed: $exePath"
