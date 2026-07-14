# -*- coding: utf-8 -*-
"""
scheduler.py - 定时调度器（基于 APScheduler）

用法:
    from scheduler import Scheduler
    sch = Scheduler(config, func, timezone="Asia/Shanghai")
    sch.start()   # 阻塞运行，按配置定时执行 func

配置格式（config.yaml 的 schedule 段）:
    schedule:
      rule: "daily:08:00"     # 每天 08:00
      timezone: "Asia/Shanghai"
也支持:
      rule: "interval:30s"     # 每 30 秒
      rule: "cron:0 8 * * *"   # 标准 cron 表达式
"""

import logging
import re
from typing import Callable, Dict, Any

logger = logging.getLogger(__name__)


class Scheduler:
    """定时调度器，封装 APScheduler，解析 config.yaml 中的 rule 字段。"""

    def __init__(self, config: Dict[str, Any], func: Callable, timezone: str = "Asia/Shanghai"):
        self.config = config or {}
        self.func = func
        self.timezone = timezone
        self.rule = self.config.get("rule", "daily:08:00")
        self._scheduler = None

    def _build_trigger(self):
        from apscheduler.triggers.cron import CronTrigger
        from apscheduler.triggers.interval import IntervalTrigger

        rule = str(self.rule).strip()

        # daily:HH:MM  -> 每天 HH:MM
        m = re.match(r"^daily:(\d{1,2}):(\d{2})$", rule)
        if m:
            hour, minute = int(m.group(1)), int(m.group(2))
            return CronTrigger(hour=hour, minute=minute, timezone=self.timezone)

        # cron:表达式
        if rule.startswith("cron:"):
            expr = rule[len("cron:"):].strip()
            fields = expr.split()
            if len(fields) == 5:
                return CronTrigger(
                    minute=fields[0], hour=fields[1], day=fields[2],
                    month=fields[3], day_of_week=fields[4], timezone=self.timezone,
                )

        # interval:Ns / interval:Nm  -> 间隔执行
        m = re.match(r"^interval:(\d+)([smh])$", rule)
        if m:
            value, unit = int(m.group(1)), m.group(2)
            seconds = {"s": 1, "m": 60, "h": 3600}[unit] * value
            return IntervalTrigger(seconds=seconds, timezone=self.timezone)

        # 兜底：默认每天 08:00
        logger.warning(f"无法解析调度规则 '{rule}'，回退为 daily:08:00")
        return CronTrigger(hour=8, minute=0, timezone=self.timezone)

    def start(self):
        from apscheduler.schedulers.blocking import BlockingScheduler

        trigger = self._build_trigger()
        self._scheduler = BlockingScheduler(timezone=self.timezone)
        self._scheduler.add_job(self.func, trigger, id="fetch_task", max_instances=1,
                                coalesce=True, misfire_grace_time=300)

        logger.info(f"调度器已启动，规则: {self.rule} (时区: {self.timezone})")
        try:
            self._scheduler.start()
        except (KeyboardInterrupt, SystemExit):
            logger.info("调度器已停止")
