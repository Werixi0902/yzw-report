# -*- coding: utf-8 -*-
"""定时调度器 - 后台运行，每天8:00自动执行考勤推送"""
import os, time, subprocess, sys, logging, ctypes
from datetime import datetime

_HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable.replace("pythonw.exe", "python.exe") if "pythonw.exe" in sys.executable else sys.executable
SCRIPT = os.path.join(_HERE, "main.py")
LOG_DIR = os.path.join(_HERE, "logs")
TARGET_HOUR, TARGET_MINUTE = 8, 0

os.makedirs(LOG_DIR, exist_ok=True)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
    handlers=[
        logging.FileHandler(os.path.join(LOG_DIR, "scheduler.log"), encoding="utf-8"),
    ]
)
log = logging.getLogger("scheduler")

ERROR_ALREADY_EXISTS = 183
MUTEX_NAME = "Global\\YzwReportScheduler_Mutex"


def acquire_mutex():
    """尝试获取 Windows 互斥锁"""
    mutex = ctypes.windll.kernel32.CreateMutexW(None, False, MUTEX_NAME)
    if ctypes.windll.kernel32.GetLastError() == ERROR_ALREADY_EXISTS:
        return None
    return mutex


def main():
    mutex = acquire_mutex()
    if mutex is None:
        log.info("已有调度器实例运行，本进程退出")
        sys.exit(0)

    log.info(f"调度器启动 (PID={os.getpid()})，目标时间: {TARGET_HOUR:02d}:00，Python: {PYTHON}")
    last_run_date = ""

    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        in_window = (now.hour == TARGET_HOUR and now.minute <= 5 and today != last_run_date)
        missed_first = (last_run_date == "" and now.hour >= TARGET_HOUR and today != last_run_date)

        if in_window or missed_first:
            log.info(f"执行考勤推送 (in_window={in_window}, missed_first={missed_first})")
            try:
                result = subprocess.run(
                    [PYTHON, SCRIPT, "--full-send"],
                    capture_output=True, text=True, timeout=300,
                    stdin=subprocess.DEVNULL
                )
                last_run_date = today
                log.info(f"推送完成，exit_code={result.returncode}")
                if result.returncode != 0:
                    log.error(f"stderr: {result.stderr[-500:] if result.stderr else 'empty'}")
            except Exception as e:
                log.error(f"推送失败: {e}")

        time.sleep(30)


if __name__ == "__main__":
    main()
