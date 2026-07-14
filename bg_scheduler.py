# -*- coding: utf-8 -*-
"""定时调度器 - 后台运行，每天8:00自动执行考勤推送"""
import os, time, subprocess, sys
from datetime import datetime

# 基于脚本自身位置动态推导路径（不再硬编码其他机器路径）
_HERE = os.path.dirname(os.path.abspath(__file__))
PYTHON = sys.executable  # 用启动本脚本的解释器
SCRIPT = os.path.join(_HERE, "main.py")
TARGET_HOUR, TARGET_MINUTE = 8, 0

def main():
    print(f"考勤推送调度器已启动，目标时间窗口: {TARGET_HOUR:02d}:00 ~ {TARGET_HOUR:02d}:05")
    print(f"Python: {PYTHON}")
    print(f"入口脚本: {SCRIPT}")
    last_run_date = ""

    while True:
        now = datetime.now()
        today = now.strftime("%Y-%m-%d")

        in_window = (now.hour == TARGET_HOUR and now.minute <= 5 and today != last_run_date)
        missed_first = (last_run_date == "" and now.hour >= TARGET_HOUR and today != last_run_date)

        if in_window or missed_first:
            print(f"[{now}] 执行考勤推送...")
            try:
                subprocess.run([PYTHON, SCRIPT, "--full-send"],
                             capture_output=True, text=True, timeout=300)
                last_run_date = today
                print(f"[{now}] 推送完成")
            except Exception as e:
                print(f"[{now}] 推送失败: {e}")

        time.sleep(30)

if __name__ == "__main__":
    main()
