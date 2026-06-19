"""
统一数据根目录管理。

打包模式（PyInstaller onefile）下，代码解压到临时目录 _MEIxxxxxx，
退出即丢。所有持久化数据必须写到用户目录。

开发模式下返回 backend/workspace/，行为与改造前完全一致。
"""
import os
import sys


def get_data_root() -> str:
    """获取数据根目录。

    优先级：
    1. 打包模式 → %APPDATA%/NovelWorkspace（Windows）或 ~/NovelWorkspace
    2. 环境变量 NOVEL_WORKSPACE_HOME 覆盖（开发/调试用）
    3. 开发模式 → backend/workspace/（保持现状）
    """
    # 1. 打包模式
    if getattr(sys, 'frozen', False):
        base = os.environ.get('LOCALAPPDATA') or os.environ.get('APPDATA') or os.path.expanduser('~')
        root = os.path.join(base, 'NovelWorkspace')
        _ensure_dir(root)
        return root

    # 2. 环境变量覆盖
    env = os.environ.get('NOVEL_WORKSPACE_HOME')
    if env:
        return env

    # 3. 开发模式：源码下的 workspace/
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), 'workspace')


def _ensure_dir(path: str) -> None:
    """安全创建目录，处理权限问题。"""
    try:
        os.makedirs(path, exist_ok=True)
    except PermissionError:
        # 杀毒软件可能拦截 PyInstaller 进程的目录创建
        # 尝试降级到用户主目录
        alt = os.path.join(os.path.expanduser('~'), 'NovelWorkspace')
        if alt != path:
            try:
                os.makedirs(alt, exist_ok=True)
            except PermissionError:
                pass  # 目录可能已存在，或确实无权限，后续写入时会报错


def get_config_path() -> str:
    """获取全局 config.json 路径。"""
    return os.path.join(get_data_root(), 'config.json')


def get_logs_dir() -> str:
    """获取日志目录。"""
    return os.path.join(get_data_root(), 'logs')
