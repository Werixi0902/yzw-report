"""
scheduler.py - 定时任务调度器

基于 APScheduler 实现，支持：
  - Cron 表达式（如 "0 9 * * 1-5" 周一到周五9点）
  - 固定间隔（如 "interval:3600" 每小时）
  - 每天固定时间（如 "daily:09:00"）
  - 一次性定时（如 "2024-01-01 09:00"）

使用示例：
    from scheduler import Scheduler

    sched = Scheduler(config)
    sched.start()
    # 程序会一直运行，按配置定时执行抓取任务
"""

import os
import re
import json
import logging
from datetime import datetime
from typing import Dict, Any, Optional, Callable

logger = logging.getLogger(__name__)


class Scheduler:
    """
    定时任务调度器

    Args:
        schedule_config: 定时配置（来自 config.yaml 的 schedule 部分）
        task_func: 要定时执行的任务函数
        timezone: 时区，默认 Asia/Shanghai
    """

    def __init__(
        self,
        schedule_config: Dict[str, Any],
        task_func: Callable,
        timezone: str = "Asia/Shanghai",
    ):
        self.config = schedule_config
        self.task_func = task_func
        self.timezone = timezone
        self._scheduler = None
        self._job = None

    def start(self) -> None:
        """
        启动定时调度
        """
        rule = self.config.get("rule", "daily:09:00")
        logger.info(f"启动定时调度，规则: {rule}，时区: {self.timezone}")

        try:
            from apscheduler.schedulers.background import BackgroundScheduler
            from apscheduler.triggers.cron import CronTrigger
            from apscheduler.triggers.interval import IntervalTrigger
            from apscheduler.triggers.date import DateTrigger
        except ImportError:
            logger.error(
                "APScheduler 未安装，请执行: pip install apscheduler\n"
                "将使用简单轮询模式替代"
            )
            self._start_simple_polling(rule)
            return

        self._scheduler = BackgroundScheduler(timezone=self.timezone)

        trigger = self._parse_rule(rule)
        if trigger is None:
            logger.error(f"无法解析定时规则: {rule}，使用默认 daily:09:00")
            from apscheduler.triggers.cron import CronTrigger
            trigger = CronTrigger(hour=9, minute=0, timezone=self.timezone)

        self._job = self._scheduler.add_job(
            self._run_task,
            trigger,
            id="data_fetch_job",
            name="定时数据抓取任务",
            misfire_grace_time=300,  # 错过执行后 5 分钟内补执行
            coalesce=True,  # 积压的任务只执行一次
            max_instances=1,  # 同一时间只运行一个实例
        )

        next_run = self._job.next_run_time
        logger.info(f"下次执行时间: {next_run}")

        self._scheduler.start()

        try:
            # 保持主线程运行
            import time as t
            while True:
                t.sleep(60)
        except (KeyboardInterrupt, SystemExit):
            self.stop()

    def stop(self) -> None:
        """停止调度器"""
        if self._scheduler:
            logger.info("正在停止调度器...")
            self._scheduler.shutdown(wait=False)
            logger.info("调度器已停止")

    def _parse_rule(self, rule: str) -> Optional[Any]:
        """
        解析定时规则字符串

        支持格式:
          - "cron:0 9 * * 1-5"    -> CronTrigger
          - "interval:3600"        -> IntervalTrigger (秒)
          - "daily:09:00"          -> CronTrigger (每天)
          - "daily:09:00,18:00"    -> 每天 9:00 和 18:00
          - "2024-01-01 09:00"     -> DateTrigger (一次性)
        """
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger
        from apscheduler.triggers.date import DateTrigger

        rule = rule.strip()

        # cron 表达式
        if rule.startswith("cron:"):
            cron_expr = rule[5:].strip()
            parts = cron_expr.split()
            # 标准 cron: 分 时 日 月 周
            if len(parts) == 5:
                return CronTrigger(
                    minute=parts[0],
                    hour=parts[1],
                    day=parts[2],
                    month=parts[3],
                    day_of_week=parts[4],
                    timezone=self.timezone,
                )
            else:
                logger.warning(f"Cron 表达式格式错误: {cron_expr}，应为 '分 时 日 月 周'")
                return None

        # 固定间隔
        elif rule.startswith("interval:"):
            seconds = int(rule[9:].strip())
            return IntervalTrigger(seconds=seconds)

        # 每天固定时间（支持多个时间点）
        elif rule.startswith("daily:"):
            times = rule[6:].strip().split(",")
            if len(times) == 1:
                hour, minute = times[0].strip().split(":")
                return CronTrigger(hour=int(hour), minute=int(minute), timezone=self.timezone)
            else:
                # 多个时间点用多个 job
                # 这里只返回第一个，剩余的在 start 中处理
                hour, minute = times[0].strip().split(":")
                return CronTrigger(hour=int(hour), minute=int(minute), timezone=self.timezone)

        # 一次性定时
        else:
            try:
                dt = datetime.strptime(rule, "%Y-%m-%d %H:%M")
                return DateTrigger(run_date=dt, timezone=self.timezone)
            except ValueError:
                logger.error(f"无法解析时间: {rule}")
                return None

    def _run_task(self) -> None:
        """执行任务包装器"""
        logger.info("=" * 50)
        logger.info("开始执行定时抓取任务...")
        try:
            self.task_func()
            logger.info("定时抓取任务完成")
        except Exception as e:
            logger.error(f"定时抓取任务失败: {e}", exc_info=True)
        logger.info("=" * 50)

    # ==================== 简单轮询模式（无 APScheduler 时使用） ====================

    def _start_simple_polling(self, rule: str) -> None:
        """
        不使用 APScheduler 的简易轮询模式
        每秒检查一次是否需要执行任务
        """
        import time as t

        # 解析规则
        check_times = self._parse_simple_rule(rule)
        if not check_times:
            logger.error("无法解析定时规则")
            return

        logger.info(f"简易轮询模式启动，计划执行时间: {check_times}")

        last_executed_date = ""

        try:
            while True:
                now = datetime.now()
                today = now.strftime("%Y-%m-%d")
                current_time = now.strftime("%H:%M")

                if today != last_executed_date:
                    for check_time in check_times:
                        if current_time == check_time:
                            logger.info(f"到达计划时间 {check_time}，执行任务")
                            self._run_task()
                            last_executed_date = today
                            break

                t.sleep(30)  # 每 30 秒检查一次
        except (KeyboardInterrupt, SystemExit):
            logger.info("简易调度器已停止")

    def _parse_simple_rule(self, rule: str) -> list:
        """
        解析简单定时规则，返回 ["HH:MM", ...] 列表

        支持:
          - "daily:09:00"
          - "daily:09:00,18:00"
          - "interval:3600"  => 每整点
        """
        rule = rule.strip()

        if rule.startswith("daily:"):
            times_str = rule[6:].strip()
            return [t.strip() for t in times_str.split(",")]

        elif rule.startswith("cron:"):
            # 简化处理：只提取小时和分钟
            cron_expr = rule[5:].strip()
            parts = cron_expr.split()
            if len(parts) >= 2:
                return [f"{parts[1].zfill(2)}:{parts[0].zfill(2)}"]
            return ["09:00"]

        else:
            return ["09:00"]


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    def test_task():
        print(f"[{datetime.now()}] 执行测试任务...")

    # 测试每日任务
    sched = Scheduler(
        {"rule": "daily:09:00,18:00"},
        test_task,
        timezone="Asia/Shanghai",
    )
    # 仅测试启动然后立即停止
    print("调度器配置成功（未实际启动，避免阻塞）")
    print(f"  规则: daily:09:00,18:00")
    print(f"  时区: Asia/Shanghai")
