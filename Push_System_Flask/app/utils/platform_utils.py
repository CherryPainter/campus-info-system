#!/usr/bin/env python3
"""
平台适配工具模块

提供跨平台兼容的工具函数，支持 Windows 和 Linux/macOS。
"""

import os
import platform
import signal
import subprocess
import sys


class PlatformUtils:
    """平台适配工具类（全静态方法）"""

    # 当前平台
    IS_WINDOWS = platform.system() == "Windows"
    IS_LINUX = platform.system() == "Linux"
    IS_MACOS = platform.system() == "Darwin"

    @staticmethod
    def get_platform() -> str:
        """
        获取当前平台名称

        Returns:
            'windows', 'linux', 'macos' 或 'unknown'
        """
        system = platform.system()
        return {
            "Windows": "windows",
            "Linux": "linux",
            "Darwin": "macos",
        }.get(system, "unknown")

    @staticmethod
    def kill_process(pid: int, force: bool = False) -> tuple[bool, str]:
        """
        终止指定 PID 的进程（跨平台）

        Args:
            pid: 进程 ID
            force: 是否强制终止（Windows 使用 taskkill /F，Linux 使用 SIGKILL）

        Returns:
            (success, message) 元组
        """
        if not pid:
            return False, "PID 无效"

        try:
            if PlatformUtils.IS_WINDOWS:
                # Windows: 使用 taskkill 命令
                cmd = ["taskkill", "/PID", str(pid)]
                if force:
                    cmd.append("/F")

                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=10,
                    encoding="gbk",
                    errors="replace",
                )

                if result.returncode == 0:
                    return True, f"进程 {pid} 已终止"
                elif "not found" in result.stderr.lower() or "找不到" in result.stderr:
                    return False, f"进程 {pid} 不存在"
                else:
                    return False, f"终止失败: {result.stderr.strip()}"
            else:
                # Linux/macOS: 使用 os.kill
                sig = signal.SIGKILL if force else signal.SIGTERM
                os.kill(pid, sig)
                return True, f"进程 {pid} 已发送终止信号"

        except ProcessLookupError:
            return False, f"进程 {pid} 不存在"
        except OSError as e:
            # Windows 上进程不存在可能抛出 OSError
            if hasattr(e, "winerror") and e.winerror == 87:
                return False, f"进程 {pid} 不存在"
            return False, f"终止进程时出错: {e}"
        except subprocess.TimeoutExpired:
            return False, "终止进程超时"
        except Exception as e:
            return False, f"终止进程时出错: {e}"

    @staticmethod
    def process_exists(pid: int) -> bool:
        """
        检查进程是否存在（跨平台）

        Args:
            pid: 进程 ID

        Returns:
            进程是否存在
        """
        if not pid:
            return False

        try:
            if PlatformUtils.IS_WINDOWS:
                # Windows: 使用 tasklist 检查
                result = subprocess.run(
                    ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                    capture_output=True,
                    text=True,
                    timeout=5,
                    encoding="gbk",
                    errors="replace",
                )
                # 如果进程存在，输出会包含 PID
                return str(pid) in result.stdout
            else:
                # Linux/macOS: 使用 os.kill(pid, 0)
                os.kill(pid, 0)
                return True
        except ProcessLookupError:
            return False
        except OSError:
            return False
        except Exception:
            return False

    @staticmethod
    def get_python_executable() -> str:
        """
        获取当前 Python 解释器路径

        Returns:
            Python 解释器绝对路径
        """
        return sys.executable

    @staticmethod
    def get_python_command() -> str:
        """
        获取 Python 命令（用于 subprocess）

        Returns:
            'python' 或 'python3' 或完整路径
        """
        # 优先使用当前解释器
        return sys.executable

    @staticmethod
    def make_executable(filepath: str) -> bool:
        """
        使文件可执行（仅 Linux/macOS 有效）

        Args:
            filepath: 文件路径

        Returns:
            是否成功
        """
        if PlatformUtils.IS_WINDOWS:
            return True  # Windows 不需要

        try:
            os.chmod(filepath, os.stat(filepath).st_mode | 0o111)
            return True
        except Exception:
            return False

    @staticmethod
    def get_shell_command() -> str | None:
        """
        获取默认 shell 命令

        Returns:
            shell 命令路径或 None
        """
        if PlatformUtils.IS_WINDOWS:
            return None  # Windows 使用默认 cmd
        else:
            return "/bin/bash"

    @staticmethod
    def normalize_path(path: str) -> str:
        """
        规范化路径（处理分隔符）

        Args:
            path: 原始路径

        Returns:
            规范化后的路径
        """
        # os.path.normpath 会自动处理分隔符
        return os.path.normpath(path)

    @staticmethod
    def get_env_separator() -> str:
        """
        获取环境变量分隔符

        Returns:
            ';' (Windows) 或 ':' (Linux/macOS)
        """
        return ";" if PlatformUtils.IS_WINDOWS else ":"

    @staticmethod
    def get_line_ending() -> str:
        """
        获取换行符

        Returns:
            '\\r\\n' (Windows) 或 '\\n' (Linux/macOS)
        """
        return "\r\n" if PlatformUtils.IS_WINDOWS else "\n"


# 便捷函数
def kill_process(pid: int, force: bool = False) -> tuple[bool, str]:
    """终止进程（便捷函数）"""
    return PlatformUtils.kill_process(pid, force)


def process_exists(pid: int) -> bool:
    """检查进程是否存在（便捷函数）"""
    return PlatformUtils.process_exists(pid)


def get_python_command() -> str:
    """获取 Python 命令（便捷函数）"""
    return PlatformUtils.get_python_command()
