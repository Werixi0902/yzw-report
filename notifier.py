"""
notifier.py - 多通道消息推送模块

支持的推送方式：
  - console: 控制台输出（默认，开发调试用）
  - email: 通过 SMTP 发送邮件
  - wecom: 企业微信机器人 webhook
  - dingtalk: 钉钉机器人 webhook

使用示例：
    from notifier import Notifier

    notifier = Notifier(config["notifier"])
    notifier.send("标题", "消息内容", {"site": "云筑网", "count": 15})
"""

import os
import re
import json
import smtplib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email.mime.image import MIMEImage
from email.encoders import encode_base64
from datetime import datetime
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)


class Notifier:
    """
    消息推送器

    Args:
        notifier_config: 推送配置字典（来自 config.yaml 的 notifier 部分）
    """

    def __init__(self, notifier_config: Dict[str, Any]):
        self.config = notifier_config
        self.method = notifier_config.get("method", "console").lower()

    def send(
        self,
        title: str,
        content: str = "",
        context: Optional[Dict[str, Any]] = None,
        attachments: Optional[list] = None,
    ) -> bool:
        """
        发送通知

        Args:
            title: 消息标题
            content: 消息正文（纯文本或 HTML）
            context: 额外上下文数据（用于模板渲染）
            attachments: 附件文件路径列表

        Returns:
            是否成功
        """
        context = context or {}
        context.setdefault("title", title)
        context.setdefault("content", content)
        context.setdefault("timestamp", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))

        logger.info(f"发送通知 [{self.method}]: {title}")

        method_map = {
            "console": self._send_console,
            "email": self._send_email,
            "wecom": self._send_wecom,
            "dingtalk": self._send_dingtalk,
        }

        sender = method_map.get(self.method)
        if sender is None:
            logger.error(f"不支持的推送方式: {self.method}，可用: {list(method_map.keys())}")
            return False

        try:
            return sender(title, content, context, attachments or [])
        except Exception as e:
            logger.error(f"通知发送失败: {e}")
            return False

    # ==================== 控制台输出 ====================

    def _send_console(self, title: str, content: str, context: dict, attachments: list) -> bool:
        """控制台输出（调试用）"""
        separator = "=" * 60
        msg = (
            f"\n{separator}\n"
            f"  📋 {title}\n"
            f"  🕐 {context.get('timestamp', '')}\n"
            f"{separator}\n"
        )
        if content:
            msg += f"\n{content}\n"

        if context:
            extra = {k: v for k, v in context.items() if k not in ("title", "content", "timestamp")}
            if extra:
                msg += "\n【附加信息】\n"
                for k, v in extra.items():
                    msg += f"  {k}: {v}\n"

        if attachments:
            msg += f"\n【附件】{len(attachments)} 个文件\n"
            for f in attachments:
                msg += f"  - {f}\n"

        msg += f"{separator}\n"
        print(msg)
        return True

    # ==================== 邮件推送 ====================

    def _send_email(self, title: str, content: str, context: dict, attachments: list) -> bool:
        """通过 SMTP 发送邮件"""
        email_cfg = self.config.get("email", {})
        smtp_server = email_cfg.get("smtp_server", "")
        smtp_port = email_cfg.get("smtp_port", 465)
        use_ssl = email_cfg.get("use_ssl", True)
        sender = email_cfg.get("sender", "")
        password = email_cfg.get("password", "")
        recipients = email_cfg.get("recipients", [])

        if not sender or not password or not recipients:
            logger.error("邮件配置不完整: 缺少 sender/password/recipients")
            return False

        # 构建邮件（混合类型：正文+附件）
        msg = MIMEMultipart("mixed")
        msg["From"] = sender
        msg["To"] = ", ".join(recipients)
        subject_tpl = email_cfg.get("subject_template", "【数据报告】{title}")
        # 只取模板中实际用到的变量，避免 context 中多余参数冲突
        fmt_ctx = {"title": title, "date": datetime.now().strftime("%Y-%m-%d"), "date_range": context.get("date_range", "")}
        if "site_name" in subject_tpl:
            fmt_ctx["site_name"] = context.get("site_name", "")
        for k in ["count", "date", "site_name", "title"]:
            if "{" + k + "}" in subject_tpl and k not in fmt_ctx:
                fmt_ctx[k] = context.get(k, "")
        msg["Subject"] = subject_tpl.format(**fmt_ctx)

        # 构建正文部分（alternative 内包含 HTML 和纯文本）
        body = MIMEMultipart("alternative")

        # 构建 HTML 正文
        html_parts = [f"<h2>{title}</h2>", f"<p>时间: {context.get('timestamp', '')}</p>"]
        if content:
            html_content = content.replace("\n", "<br>")
            html_parts.append(f"<pre style='font-size:14px;'>{html_content}</pre>")

        # 附加数据表格
        data = context.get("data", [])
        if data and isinstance(data, list):
            fields = context.get("fields", data[0].keys() if data else [])
            html_parts.append("<h3>数据摘要</h3><table border='1' cellpadding='5' style='border-collapse:collapse;'>")
            html_parts.append("<tr>" + "".join(f"<th>{f}</th>" for f in fields) + "</tr>")
            for row in data[:20]:
                html_parts.append(
                    "<tr>" + "".join(f"<td>{str(row.get(f, ''))}</td>" for f in fields) + "</tr>"
                )
            if len(data) > 20:
                html_parts.append(f"<tr><td colspan='{len(fields)}'>... 共 {len(data)} 条</td></tr>")
            html_parts.append("</table>")

        body.attach(MIMEText("\n".join(html_parts), "html", "utf-8"))
        msg.attach(body)

        # 添加附件 - 使用 MIMEImage 确保 QQ邮箱正确识别图片
        for filepath in attachments:
            if os.path.exists(filepath):
                ext = os.path.splitext(filepath)[1].lower()
                filename = os.path.basename(filepath)
                with open(filepath, "rb") as f:
                    payload = f.read()

                if ext in (".png", ".jpg", ".jpeg", ".gif", ".bmp"):
                    subtype = {"png": "png", "jpg": "jpeg", "jpeg": "jpeg", "gif": "gif", "bmp": "bmp"}.get(ext.lstrip("."), "png")
                    part = MIMEImage(payload, _subtype=subtype)
                else:
                    ct_map = {
                        ".pdf": ("application", "pdf"),
                        ".xlsx": ("application", "vnd.openxmlformats-officedocument.spreadsheetml.sheet"),
                        ".csv": ("text", "csv"),
                        ".txt": ("text", "plain"),
                    }
                    maintype, subtype = ct_map.get(ext, ("application", "octet-stream"))
                    part = MIMEBase(maintype, subtype)
                    part.set_payload(payload)
                    encode_base64(part)

                # 用纯英文文件名，避免中文导致QQ邮箱解析异常
                base = os.path.basename(filepath)
                safe_name = "yzw_attendance_" + str(os.path.getsize(filepath)) + os.path.splitext(filepath)[1]
                
                # 不重复添加Content-Type（MIMEImage已自动设置）
                part.add_header("Content-Disposition", 'attachment; filename="' + safe_name + '"')
                # 原始中文名放在Description中
                part.add_header("Content-Description", filename)
                msg.attach(part)

        # 发送
        try:
            if use_ssl:
                with smtplib.SMTP_SSL(smtp_server, smtp_port) as server:
                    server.login(sender, password)
                    server.sendmail(sender, recipients, msg.as_string())
            else:
                with smtplib.SMTP(smtp_server, smtp_port) as server:
                    server.starttls()
                    server.login(sender, password)
                    server.sendmail(sender, recipients, msg.as_string())
            logger.info(f"邮件发送成功 -> {recipients}")
            return True
        except Exception as e:
            logger.error(f"邮件发送失败: {e}")
            return False

    # ==================== 企业微信推送 ====================

    def _send_wecom(self, title: str, content: str, context: dict, attachments: list) -> bool:
        """通过企业微信机器人 webhook 推送消息"""
        import requests

        wecom_cfg = self.config.get("wecom", {})
        webhook_url = wecom_cfg.get("webhook_url", "")

        if not webhook_url:
            logger.error("企业微信配置不完整: 缺少 webhook_url")
            return False

        # 构建消息（支持 markdown）
        md_content = f"## {title}\n"
        md_content += f"> 🕐 {context.get('timestamp', '')}\n\n"
        if content:
            md_content += f"{content}\n\n"

        extra = {k: v for k, v in context.items() if k not in ("title", "content", "timestamp", "data", "fields")}
        for k, v in extra.items():
            md_content += f"**{k}**: {v}\n"

        # 数据概览
        data = context.get("data", [])
        if data and isinstance(data, list):
            md_content += f"\n共抓取 **{len(data)}** 条数据\n"
            if len(data) > 0:
                fields = context.get("fields", list(data[0].keys()) if data else [])
                header = " | ".join(str(f) for f in fields)
                md_content += f"| {header} |\n"
                md_content += "| " + " | ".join("---" for _ in fields) + " |\n"
                for row in data[:10]:
                    row_vals = [str(row.get(f, "")).replace("|", "/")[:30] for f in fields]
                    md_content += "| " + " | ".join(row_vals) + " |\n"

        payload = {
            "msgtype": "markdown",
            "markdown": {"content": md_content},
        }

        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("企业微信推送成功")
                return True
            else:
                logger.error(f"企业微信推送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"企业微信请求异常: {e}")
            return False

    # ==================== 钉钉推送 ====================

    def _send_dingtalk(self, title: str, content: str, context: dict, attachments: list) -> bool:
        """通过钉钉机器人 webhook 推送消息"""
        import requests
        import hashlib
        import base64
        import hmac
        import time as time_module

        ding_cfg = self.config.get("dingtalk", {})
        webhook_url = ding_cfg.get("webhook_url", "")
        secret = ding_cfg.get("secret", "")

        if not webhook_url:
            logger.error("钉钉配置不完整: 缺少 webhook_url")
            return False

        # 加签
        if secret:
            timestamp = str(round(time_module.time() * 1000))
            sign_str = f"{timestamp}\n{secret}"
            hmac_code = hmac.new(
                secret.encode("utf-8"),
                sign_str.encode("utf-8"),
                digestmod=hashlib.sha256,
            ).digest()
            sign = base64.b64encode(hmac_code).decode("utf-8")
            separator = "&" if "?" in webhook_url else "?"
            webhook_url = f"{webhook_url}{separator}timestamp={timestamp}&sign={sign}"

        # 构建 Markdown 消息
        md_content = f"## {title}\n"
        md_content += f"---\n🕐 {context.get('timestamp', '')}\n\n"
        if content:
            md_content += f"{content}\n\n"

        data = context.get("data", [])
        if data and isinstance(data, list):
            md_content += f"> 共抓取 **{len(data)}** 条数据\n"

        payload = {
            "msgtype": "markdown",
            "markdown": {
                "title": title,
                "text": md_content,
            },
        }

        try:
            resp = requests.post(webhook_url, json=payload, timeout=10)
            resp.raise_for_status()
            result = resp.json()
            if result.get("errcode") == 0:
                logger.info("钉钉推送成功")
                return True
            else:
                logger.error(f"钉钉推送失败: {result}")
                return False
        except Exception as e:
            logger.error(f"钉钉请求异常: {e}")
            return False


# ==================== 便捷工具函数 ====================



def format_data_summary(data: list, fields: list = None) -> str:
    """
    将考勤数据格式化为可读的文本摘要
    包含：在场工人列表、每日出勤工时、班组分布
    """
    if not data:
        return "（无数据）"

    # 判断在场/退场
    onsite = [d for d in data if d.get("考勤卡状态", "") not in ("已销卡", "停用")]
    offsite = [d for d in data if d.get("考勤卡状态", "") in ("已销卡", "停用")]

    lines = []
    lines.append(f"📊 考勤数据总览")
    lines.append(f"{'─' * 55}")
    lines.append(f"  总人数: {len(data)} 人  |  在场: {len(onsite)} 人  |  退场: {len(offsite)} 人")
    lines.append("")

    # 按班组分组
    groups = {}
    for d in onsite:
        g = d.get("班组", "未分组")
        if g not in groups:
            groups[g] = []
        groups[g].append(d)

    lines.append(f"📋 在场工人出勤详情（按班组）")
    lines.append(f"  图例: 11.6=正常工时  △缺=缺卡(单向打卡)  ✗未=未打卡  请假=请假")
    lines.append(f"{'─' * 55}")

    for g_name in sorted(groups.keys(), key=lambda x: -len(groups[x])):
        members = groups[g_name]
        lines.append(f"\n◆ {g_name}（{len(members)}人）")
        lines.append(f"  {'姓名':<8}{'工种':<10}{'出勤':<6}{'总工时':<8}日期:        4日  5日  6日  7日  8日  9日 10日")
        lines.append(f"  {'─' * 54}")

        for w in members:
            name = w.get("姓名", "")
            work_type = w.get("工种", "")
            attend_days = w.get("出勤天数", "")
            total_hours = w.get("总工时", "")

            # 收集近7天每日工时（区分状态）
            daily_str = ""
            for day in range(4, 11):
                key = f"每日工时_{day}日"
                val = w.get(key, "") or ""
                if val == "--":
                    daily_str += " ✗未"
                elif val == "0.00" or val == "0":
                    daily_str += " △缺"
                elif val == "请假":
                    daily_str += " 请假"
                elif val.replace(".", "").replace("-", "").isdigit():
                    h = float(val)
                    if h > 0:
                        daily_str += f"{h:>5.1f}"
                    else:
                        daily_str += " △缺"
                else:
                    daily_str += f"{str(val):>5}"

            # 考勤卡状态
            card_status = w.get("考勤卡状态", "")
            status_mark = "🟢" if card_status == "正常" else "🟡"

            name_display = f"{name:<7}"
            work_display = f"{work_type[:6]:<8}"
            attend_display = f"{str(attend_days):>3}天" if attend_days and attend_days != "--" else "  --"
            hour_display = f"{str(total_hours):>7}" if total_hours and total_hours != "--" else "     --"

            lines.append(f"  {status_mark} {name_display}{work_display}{attend_display}{hour_display}  {daily_str}")

    # 在场工人合计
    lines.append(f"\n{'─' * 55}")
    all_attend = sum(int(d.get("出勤天数", 0) or 0) for d in onsite if d.get("出勤天数", "").isdigit())
    all_hours = sum(float(d.get("总工时", 0) or 0) for d in onsite if d.get("总工时", "").replace(".", "").isdigit())
    lines.append(f"在场合计: {len(onsite)}人 | 总出勤人天: {all_attend}天 | 总工时: {all_hours:.2f}h")

    # 退场统计
    if offsite:
        off_groups = {}
        for d in offsite:
            g = d.get("班组", "未分组")
            off_groups[g] = off_groups.get(g, 0) + 1
        lines.append(f"\n📋 退场工人统计")
        lines.append(f"{'─' * 55}")
        for g_name, count in sorted(off_groups.items(), key=lambda x: -x[1]):
            lines.append(f"  {g_name}: {count}人")

    return "\n".join(lines)
if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, format="%(asctime)s [%(levelname)s] %(message)s")

    # 测试控制台通知
    notifier = Notifier({"method": "console"})
    notifier.send(
        "测试通知 - 云筑网数据报告",
        "今日抓取完成",
        {
            "site_name": "云筑网劳务实名制",
            "count": 15,
            "fields": ["姓名", "工种", "考勤状态"],
            "data": [
                {"姓名": "张三", "工种": "木工", "考勤状态": "已出勤"},
                {"姓名": "李四", "工种": "电工", "考勤状态": "已出勤"},
                {"姓名": "王五", "工种": "焊工", "考勤状态": "未出勤"},
            ],
        },
    )



























