# -*- coding: utf-8 -*-
r"""看门狗 - 监控并自动重启考勤推送调度器
注册在 HKCU\Run，登录时启动，每60秒检查一次调度器是否存活
使用 Windows Mutex 确保单实例
"""
import os
import sys
import time
import subprocess
import logging
import ctypes
import psutil

HERE = os.path.dirname(os.path.abspath(__file__))
PYTHONW = sys.executable
SCHEDULER = os.path.join(HERE, "bg_scheduler.py")
LOG_DIR = os.path.join(HERE, "logs")
os.makedirs(LOG_DIR, exist_ok=True)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "watchdog.log"), encoding="utf-8"),
    ],
)

# Windows Mutex 常量
ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Global\\YzwReportWatchdog_Mutex"


def acquire_mutex():
    """尝试获取 Windows 互斥锁，如果已存在则返回 None"""
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return mutex


def is_scheduler_running():
    """检查 bg_scheduler.py 是否在运行（使用 psutil）"""
    for proc in psutil.process_iter(["pid", "name", "cmdline"]):
        try:
            if proc.info["name"] and "pythonw" in proc.info["name"].lower():
                cmdline = proc.info["cmdline"] or []
                if any("bg_scheduler" in arg for arg in cmdline):
                    return True
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return False


def start_scheduler():
    """启动调度器"""
    subprocess.Popen(
        [PYTHONW, SCHEDULER],
        stdin=subprocess.DEVNULL,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        cwd=HERE,
    )


def main():
    mutex = acquire_mutex()
    if mutex is None:
        logging.info("已有看门狗实例运行，本进程退出")
        sys.exit(0)

    logging.info(f"看门狗启动 (PID={os.getpid()})，监控目标: {SCHEDULER}")

    while True:
        try:
            if not is_scheduler_running():
                logging.info("调度器未运行，正在启动...")
                start_scheduler()
                logging.info("调度器已启动")
                time.sleep(10)
        except Exception as e:
            logging.error(f"看门狗异常: {e}")

        time.sleep(60)


if __name__ == "__main__":
    main()
