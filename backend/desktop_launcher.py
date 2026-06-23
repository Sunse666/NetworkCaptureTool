import socket
import subprocess
import sys
import time
import traceback
import urllib.error
import urllib.request
from pathlib import Path

from app.core.config import get_settings

_LOG_HANDLE = None
KILL_PROFILE_CHROME_ON_STARTUP = False


def main() -> None:
    """桌面版启动入口：启动后只打印访问地址，由用户自行打开网页。"""
    _prepare_desktop_output()
    try:
        settings = get_settings()
        preferred_url = f"http://{settings.app_host}:{settings.app_port}/"
        if _is_existing_service_healthy(preferred_url):
            _write_launcher_url(preferred_url)
            _show_access_url(preferred_url, reused=True)
            return
        _terminate_stale_instances()
        import uvicorn
        from app.main import app

        port = _available_port(settings.app_host, settings.app_port)
        url = f"http://{settings.app_host}:{port}/"
        _write_launcher_url(url)
        _show_access_url(url)
        uvicorn.run(
            app,
            host=settings.app_host,
            port=port,
            reload=False,
            access_log=False,
            log_config=None,
        )
        _log("Server stopped.")
    except Exception:
        _log(traceback.format_exc())
        raise


def _prepare_desktop_output() -> None:
    """准备启动日志；无控制台运行时兜底把标准输出写入日志。"""
    global _LOG_HANDLE
    runtime_dir = _runtime_dir()
    runtime_dir.mkdir(parents=True, exist_ok=True)
    log_path = runtime_dir / "launcher.log"
    _LOG_HANDLE = open(log_path, "a", encoding="utf-8", buffering=1)
    if sys.stdout is None:
        sys.stdout = _LOG_HANDLE
    if sys.stderr is None:
        sys.stderr = _LOG_HANDLE


def _terminate_stale_instances() -> None:
    """启动前关闭同目录旧实例和残留浏览器，避免端口被旧进程占用后新实例跑到随机端口。"""
    if not getattr(sys, "frozen", False) or sys.platform != "win32":
        return
    app_path = str(Path(sys.executable).resolve())
    current_pid = str(os_getpid())
    runtime_dir = _runtime_dir()
    profile_dirs = [
        str(runtime_dir / "chrome-profile"),
        str(runtime_dir / "edge-profile"),
    ]
    driver_dir = str(Path(sys.executable).resolve().parent / "_internal" / "runtime" / "drivers")
    script = r"""
param(
  [string]$AppPath,
  [string]$CurrentPid,
  [string]$ProfileDirsStr,
  [string]$DriverDir
)
$ProfileDirs = $ProfileDirsStr -split ';'
$profilePatterns = $ProfileDirs | ForEach-Object { [WildcardPattern]::Escape($_) }
$escapedDriver = [WildcardPattern]::Escape($DriverDir)
$killerProcesses = @('NetworkCaptureTool.exe', 'chrome.exe', 'chromedriver.exe', 'msedgewebview2.exe', 'msedgedriver.exe')
$all = Get-CimInstance Win32_Process | Where-Object { $_.Name -in $killerProcesses }
$oldApps = $all | Where-Object {
  $_.Name -eq 'NetworkCaptureTool.exe' -and
  $_.ProcessId -ne [int]$CurrentPid -and
  $_.ExecutablePath -eq $AppPath
}
$toolBrowsers = @()
if ($env:NETWORK_CAPTURE_KILL_PROFILE_CHROME_ON_STARTUP -eq '1') {
  $toolBrowsers = $all | Where-Object {
    $_.Name -in @('chrome.exe', 'msedgewebview2.exe') -and
    ($profilePatterns | ForEach-Object { $_.CommandLine -like "*$_*" }) -contains $true
  }
}
$toolDrivers = $all | Where-Object {
  $_.Name -in @('chromedriver.exe', 'msedgedriver.exe') -and (
    $_.ExecutablePath -like "$escapedDriver*" -or $_.CommandLine -like "*$escapedDriver*"
  )
}
@($oldApps + $toolBrowsers + $toolDrivers) |
  Sort-Object ProcessId -Unique |
  ForEach-Object {
    try { Stop-Process -Id $_.ProcessId -Force -ErrorAction Stop } catch {}
  }
"""
    try:
        env = None
        if KILL_PROFILE_CHROME_ON_STARTUP:
            import os

            env = {**os.environ, "NETWORK_CAPTURE_KILL_PROFILE_CHROME_ON_STARTUP": "1"}
        subprocess.run(
            [
                "powershell",
                "-NoProfile",
                "-ExecutionPolicy",
                "Bypass",
                "-Command",
                script,
                "-AppPath",
                app_path,
                "-CurrentPid",
                current_pid,
                "-ProfileDirsStr", ";".join(profile_dirs),
                "-DriverDir",
                driver_dir,
            ],
            check=False,
            capture_output=True,
            text=True,
            timeout=8,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            env=env,
        )
        # Windows 释放监听端口通常很快，循环等待能减少新实例被迫切到随机端口的概率。
        settings = get_settings()
        _wait_for_port_free(settings.app_host, settings.app_port, timeout_seconds=6)
    except Exception:
        _log(traceback.format_exc())


def _runtime_dir() -> Path:
    """返回 exe 同级 runtime 目录；源码运行时使用当前目录下的 runtime。"""
    base_dir = Path(sys.executable).resolve().parent if getattr(sys, "frozen", False) else Path.cwd()
    return base_dir / "runtime"


def os_getpid() -> int:
    """延迟导入 os，避免桌面启动器全局导入过多无关模块。"""
    import os

    return os.getpid()


def _write_launcher_url(url: str) -> None:
    """记录实际启动地址，端口被占用自动切换时也方便定位。"""
    (_runtime_dir() / "launcher.url").write_text(url, encoding="utf-8")


def _log(message: str) -> None:
    """写入启动器日志。"""
    if _LOG_HANDLE:
        _LOG_HANDLE.write(f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {message}\n")


def _print(message: str = "") -> None:
    """向终端输出信息；静默运行时退回到启动日志，避免丢失关键端口号。"""
    try:
        print(message, flush=True)
    except Exception:
        _log(message)


def _show_access_url(url: str, reused: bool = False) -> None:
    """在终端展示访问地址，不主动打开浏览器。"""
    status = "检测到服务已在运行" if reused else "接口捕获服务已启动"
    _log(f"{status}: {url}")
    _print("")
    _print("=" * 64)
    _print(status)
    _print(f"访问地址：{url}")
    _print("请在浏览器中手动打开以上地址；关闭此窗口会停止当前服务。")
    _print("=" * 64)
    _print("")


def _available_port(host: str, preferred_port: int) -> int:
    """优先使用配置端口；如被占用则自动寻找临近空闲端口，避免用户看到启动失败。"""
    if _wait_for_port_free(host, preferred_port, timeout_seconds=3):
        return preferred_port
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as server:
        server.bind((host, 0))
        fallback_port = int(server.getsockname()[1])
    _log(f"Preferred port {preferred_port} is busy, fallback to {fallback_port}.")
    return fallback_port


def _is_port_free(host: str, port: int) -> bool:
    """检查端口是否空闲。"""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as client:
        client.settimeout(0.2)
        return client.connect_ex((host, port)) != 0


def _wait_for_port_free(host: str, port: int, timeout_seconds: float) -> bool:
    """等待端口释放，避免刚结束旧进程时立刻重启失败。"""
    deadline = time.time() + timeout_seconds
    while time.time() < deadline:
        if _is_port_free(host, port):
            return True
        time.sleep(0.2)
    return _is_port_free(host, port)


def _is_existing_service_healthy(base_url: str) -> bool:
    """检查固定入口是否已经有可用服务，重复双击时直接复用已有网页。"""
    health_url = f"{base_url.rstrip('/')}/api/health"
    try:
        with urllib.request.urlopen(health_url, timeout=0.6) as response:
            body = response.read(2048).decode("utf-8", errors="ignore")
            return response.status == 200 and '"status"' in body and '"ok"' in body
    except (OSError, urllib.error.URLError, TimeoutError):
        return False


if __name__ == "__main__":
    main()
