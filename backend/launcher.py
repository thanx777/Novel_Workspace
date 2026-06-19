"""
Novel Workspace 启动器 — PyInstaller 入口点

双击 exe 后：
1. 设置 AUTH_DISABLED（单机无需登录）
2. 找可用端口（8000-8010）
3. 后台线程启动 uvicorn
4. 打开 pywebview 原生窗口（WebView2 不可用时降级为系统浏览器）
5. 关窗口 → 主线程结束 → daemon 线程带走 uvicorn
"""
import os
import sys
import threading
import time


def _find_free_port(start=8000, end=8010):
    """在 start~end 范围内找可用端口。"""
    import socket
    for port in range(start, end + 1):
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.3):
                continue  # 端口被占用，试下一个
        except OSError:
            return port
    return None


def _wait_for_port(port, timeout=15):
    """等待端口可连接。"""
    import socket
    deadline = time.time() + timeout
    while time.time() < deadline:
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return True
        except OSError:
            time.sleep(0.2)
    return False


def main():
    # 单机软件无需登录
    os.environ['AUTH_DISABLED'] = 'true'

    # 找可用端口
    port = _find_free_port()
    if port is None:
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "端口 8000-8010 均被占用，请关闭占用程序后重试",
            "Novel Workspace", 0x10)
        return

    # 后台线程启动 uvicorn
    from main import app
    import uvicorn
    # console=False 时 sys.stdout/isatty 不可用，必须用 log_config=None 避免 uvicorn 日志崩溃
    server = uvicorn.Server(
        uvicorn.Config(app, host="127.0.0.1", port=port, log_level="warning",
                       log_config=None))
    threading.Thread(target=server.run, daemon=True).start()

    if not _wait_for_port(port):
        import ctypes
        ctypes.windll.user32.MessageBoxW(
            0, "服务启动失败，请稍后重试", "Novel Workspace", 0x10)
        return

    url = f"http://127.0.0.1:{port}"

    # 尝试打开原生窗口，WebView2 不可用时降级为系统浏览器
    try:
        import webview
        webview.create_window("Novel Workspace", url,
                              width=1400, height=900, min_size=(1000, 700))
        webview.start()
    except Exception:
        import webbrowser
        import ctypes
        webbrowser.open(url)
        # 无窗口事件循环可阻塞，改为等待用户手动关闭
        ctypes.windll.user32.MessageBoxW(
            0,
            f"已用浏览器打开 Novel Workspace\n\n关闭此对话框将退出程序\n地址: {url}",
            "Novel Workspace",
            0x40  # MB_ICONINFORMATION
        )


if __name__ == "__main__":
    main()
