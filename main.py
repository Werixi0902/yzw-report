"""
main.py - 定时数据抓取系统主入口

用法:
    # 正常启动（按配置定时执行）
    python main.py

    # 立即执行一次抓取
    python main.py --now

    # 列出配置的站点
    python main.py --list

    # 生成 Cookie 模板
    python main.py --cookie-template

    # 测试通知推送
    python main.py --test-notify

    # 仅运行一次后退出
    python main.py --once
"""

import os
import sys
import json
import logging
import argparse
from datetime import datetime
from typing import Dict, Any, List

import yaml

from scraper_engine import ScraperEngine
import gen_image
from notifier import Notifier, format_data_summary
from scheduler import Scheduler

logger = logging.getLogger(__name__)


# -------------------- 日志配置 --------------------

def setup_logging(log_dir: str = "./logs", level: str = "INFO") -> None:
    os.makedirs(log_dir, exist_ok=True)
    log_file = os.path.join(
        log_dir,
        f"fetch_{datetime.now().strftime('%Y%m%d')}.log"
    )
    logging.basicConfig(
        level=getattr(logging, level.upper(), logging.INFO),
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        handlers=[
            logging.FileHandler(log_file, encoding="utf-8"),
            logging.StreamHandler(sys.stdout),
        ],
    )


# -------------------- 配置管理 --------------------

def load_config(config_path: str = "config.yaml") -> Dict[str, Any]:
    if not os.path.exists(config_path):
        logger.error(f"配置文件不存在: {config_path}")
        logger.error("请复制 config.yaml 并根据需要修改配置")
        sys.exit(1)
    with open(config_path, "r", encoding="utf-8") as f:
        config = yaml.safe_load(f)
    logger.info(f"配置文件已加载: {config_path}")
    return config


# -------------------- 核心抓取任务 --------------------

def run_fetch_task(config: Dict[str, Any]) -> List[Dict[str, Any]]:
    global_config = config.get("global", {})
    sites = config.get("sites", [])
    notifier_config = config.get("notifier", {})

    if not sites:
        logger.warning("配置中没有站点，请先在 config.yaml 中配置 sites")
        return []

    notifier = Notifier(notifier_config)
    results = []

    for site_cfg in sites:
        site_name = site_cfg.get("name", "未知站点")
        logger.info(f"\n{'='*50}")
        logger.info(f"开始抓取: {site_name}")
        logger.info(f"{'='*50}")

        site_cfg["retry_times"] = site_cfg.get("retry_times", global_config.get("retry_times", 3))
        site_cfg["timeout"] = site_cfg.get("timeout", global_config.get("timeout", 30))

        engine = ScraperEngine(
            site_cfg,
            data_dir=global_config.get("data_dir", "./data"),
        )
        data = engine.run()

        result = {
            "site_name": site_name,
            "data": data,
            "fields": list(site_cfg.get("fields", {}).keys()),
            "count": len(data),
            "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        }
        results.append(result)

        summary = format_data_summary(data, list(site_cfg.get("fields", {}).keys()))
        notifier.send(
            title=f"【数据报告】{site_name} - {datetime.now().strftime('%Y-%m-%d')}",
            content=summary if data else "本次抓取未获取到数据",
            context={
                "site_name": site_name,
                "count": len(data),
                "date": datetime.now().strftime("%Y-%m-%d"),
                "data": data,
                "fields": list(site_cfg.get("fields", {}).keys()),
            },
        )

    return results


# -------------------- 子命令 --------------------


def run_full_send(config: Dict[str, Any]) -> bool:
    """完整流程：抓取 -> 生成班组图片 -> 发送邮件(带图片附件)"""
    import gen_image
    from notifier import Notifier
    import json
    from datetime import datetime
    
    sites = config.get("sites", [])
    notifier_config = config.get("notifier", {})
    global_config = config.get("global", {})
    
    if not sites:
        logger.warning("配置中没有站点")
        return False
    
    notifier = Notifier(notifier_config)
    data_dir = global_config.get("data_dir", "./data")
    os.makedirs(data_dir, exist_ok=True)
    all_data = []
    
    for site_cfg in sites:
        site_name = site_cfg.get("name", "未知站点")
        logger.info(f"开始抓取: {site_name}")
        
        engine = ScraperEngine(site_cfg, data_dir=data_dir)
        data = engine.run()
        
        if not data:
            logger.warning(f"{site_name} 未获取到数据")
            continue
        all_data.extend(data)
    
    if not all_data:
        logger.error("未获取到任何数据")
        return False
    
    # 生成班组图片
    logger.info("生成班组考勤图片...")
    img_paths = gen_image.generate_all(data=all_data, output_dir=data_dir)
    
    if not img_paths:
        logger.error("班组图片生成失败")
        return False
    
    # 统计在场人数
    onsite = [d for d in all_data if d.get("考勤卡状态", "") not in ("已销卡", "停用")]
    stats = {}
    for d in onsite:
        g = d.get("班组", "未分组")
        stats.setdefault(g, []).append(d)
    
    # 构建HTML正文
    # 获取日期范围
    days, _ = gen_image.get_day_labels(all_data)
    date_range = f"{days[0]} ~ {days[-1]}" if days else datetime.now().strftime("%m月%d日")
    month_str = ""
    # 尝试从保存的JSON读取table_meta
    import glob
    json_files = sorted(glob.glob(os.path.join(data_dir, "云筑网考勤统计_*.json")))
    if json_files:
        with open(json_files[-1], "r", encoding="utf-8") as f:
            saved = json.load(f)
        meta = saved.get("table_meta")
        if meta:
            month_str = meta.get("month", "")

    # 构建HTML正文
    today = datetime.now().strftime("%Y-%m-%d")
    summary = f"<h2>📋 丰台区青塔项目 - 考勤日报</h2>"
    summary += f"<p>📅 报告日期: <b>{today}</b> | 考勤区间: <b>{date_range}</b> ({month_str})</p>"
    summary += f"<p>👷 在场总人数: <b>{len(onsite)}</b> 人 | 班组: <b>{len(stats)}</b> 个</p><hr>"
    for gname, members in sorted(stats.items(), key=lambda x: -len(x[1])):
        summary += f"<p>📎 <b>{gname}</b>: {len(members)} 人 &nbsp;（详见附件图片）</p>"
    summary += "<hr><p style='color:#666;font-size:12px'>📌 附件中包含各班组每日考勤详情图表</p>"

    # 发送邮件（带所有附件）
    success = notifier.send(
        title=f"【考勤报告】丰台区青塔项目 - {date_range}",
        content=summary,
        context={
            "site_name": "云筑网",
            "count": len(onsite),
            "date": today,
            "date_range": date_range,
        },
        attachments=list(img_paths.values()),
    )
    
    if success:
        logger.info(f"完整流程执行成功，已发送 {len(img_paths)} 张班组图片")
    else:
        logger.error("邮件发送失败")
    

    # ========== 企业微信推送（企微机器人webhook） ==========
    wecom_cfg = notifier_config.get("wecom", {})
    if wecom_cfg.get("webhook_url"):
        logger.info("开始企业微信推送...")
        try:
            wecom_notifier = Notifier({"method": "wecom", "wecom": wecom_cfg})
            title_msg2 = f"【考勤报告】丰台区青塔项目 - {date_range}"
            summary_text = f"丰台区青塔项目考勤报告\n日期: {today}\n区间: {date_range}\n在场: {len(onsite)}人 / {len(stats)}个班组"
            wecom_notifier.send(
                title=title_msg2,
                content=summary_text,
                context={
                    "date_range": date_range,
                    "count": len(onsite),
                    "timestamp": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
                    "data": all_data,
                },
                attachments=list(img_paths.values()),
            )
            logger.info("企业微信推送完成")
        except Exception as e:
            logger.error(f"企业微信推送异常: {e}")
    else:
        logger.info("未配置企业微信 webhook，跳过企微推送")
    return success

def cmd_list_sites(config: Dict[str, Any]) -> None:
    sites = config.get("sites", [])
    if not sites:
        print("未配置任何站点，请编辑 config.yaml 添加目标站点")
        return
    print(f"\n已配置 {len(sites)} 个站点:\n")
    for i, site in enumerate(sites, 1):
        print(f"  {i}. {site.get('name', '未命名')}")
        print(f"     URL: {site.get('data_url', '未设置')}")
        print(f"     抓取方式: {site.get('method', 'requests')}")
        print(f"     登录方式: {site.get('login_method', 'none')}")
        fields = site.get("fields", {})
        print(f"     数据字段 ({len(fields)} 个):")
        for fn in fields.keys():
            print(f"       - {fn}")
        print()


def cmd_cookie_template(config: Dict[str, Any]) -> None:
    sites = config.get("sites", [])
    cookie_sites = [s for s in sites if s.get("login_method") == "cookie"]
    if not cookie_sites:
        print("没有站点配置了 cookie 登录方式")
        return
    for site in cookie_sites:
        cookie_file = site.get("cookie_file", "")
        if not cookie_file:
            continue
        domain = site.get("base_url", "").replace("https://", "").replace("http://", "")
        template = [
            {"name": "token", "value": "YOUR_TOKEN_VALUE", "domain": domain,
             "path": "/", "httpOnly": False, "secure": True, "sameSite": "Lax"},
            {"name": "session_id", "value": "YOUR_SESSION_ID", "domain": domain,
             "path": "/", "httpOnly": True, "secure": True, "sameSite": "Lax"},
        ]
        os.makedirs(os.path.dirname(cookie_file) or ".", exist_ok=True)
        with open(cookie_file, "w", encoding="utf-8") as f:
            json.dump(template, f, ensure_ascii=False, indent=2)
        print(f"Cookie 模板已生成: {cookie_file}")
        print(f"请将实际的 Cookie 值填入该文件")


def cmd_test_notify(config: Dict[str, Any]) -> None:
    notifier_config = config.get("notifier", {})
    method = notifier_config.get("method", "console")
    print(f"\n测试通知推送 (方式: {method})...")

    test_data = [
        {"姓名": "张三", "工种": "木工", "考勤状态": "已出勤", "当日工时": "8"},
        {"姓名": "李四", "工种": "电工", "考勤状态": "已出勤", "当日工时": "8"},
        {"姓名": "王五", "工种": "焊工", "考勤状态": "未出勤", "当日工时": "0"},
    ]

    notifier = Notifier(notifier_config)
    success = notifier.send(
        title="【测试】数据抓取系统",
        content="这是一条测试消息，确认推送通道正常工作。",
        context={
            "site_name": "测试站点", "count": 3,
            "date": datetime.now().strftime("%Y-%m-%d"),
            "data": test_data,
            "fields": ["姓名", "工种", "考勤状态", "当日工时"],
        },
    )
    print("测试通知发送成功!" if success else "测试通知发送失败，请检查配置")


# -------------------- 主程序 --------------------

def main():
    parser = argparse.ArgumentParser(
        description="定时数据抓取系统",
        epilog="""示例:
    python main.py               # 正常启动，按配置定时
    python main.py --now         # 立即执行一次并继续定时
    python main.py --once        # 执行一次后退出
    python main.py --full-send   # 完整流程（抓取+图片+发邮件）
    python main.py --list        # 查看已配置的站点
    python main.py --test-notify # 测试推送通知
    python main.py --cookie-template # 生成 Cookie 模板
        """,
    )
    parser.add_argument("--config", default="config.yaml", help="配置文件路径")
    parser.add_argument("--now", action="store_true", help="启动后立即执行一次")
    parser.add_argument("--once", action="store_true", help="仅执行一次后退出")
    parser.add_argument("--full-send", action="store_true", help="完整流程：抓取+生成图片+发邮件（用于定时任务）")
    parser.add_argument("--list", action="store_true", help="列出已配置站点")
    parser.add_argument("--test-notify", action="store_true", help="测试通知推送")
    parser.add_argument("--cookie-template", action="store_true", help="生成 Cookie 模板")
    parser.add_argument("--log-level", default="INFO", help="日志级别")
    args = parser.parse_args()

    setup_logging(level=args.log_level)
    config = load_config(args.config)

    if args.list:
        cmd_list_sites(config)
        return
    if args.cookie_template:
        cmd_cookie_template(config)
        return
    if args.test_notify:
        cmd_test_notify(config)
        return

    if args.full_send:
        run_full_send(config)
        return

    if args.once:
        run_fetch_task(config)
        return

    if args.now:
        run_fetch_task(config)

    schedule_config = config.get("schedule", {})
    scheduler = Scheduler(
        schedule_config,
        lambda: run_fetch_task(config),
        timezone=schedule_config.get("timezone", "Asia/Shanghai"),
    )
    scheduler.start()


if __name__ == "__main__":
    main()

