import sys, json, os, re, glob
from datetime import datetime
from collections import OrderedDict

OUTPUT_DIR = r"C:\Users\Yuan\Documents\云筑网劳务实名制数据抓取\data"
SITE_PACKAGES = r"C:\Users\Yuan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages"
sys.path.insert(0, SITE_PACKAGES)


def status_style(val):
    if not val or str(val).strip() in ("", "--"):
        return ("✗", "#e74c3c", "未打卡")
    v = str(val).strip()
    if v == "请假":
        return ("休", "#f39c12", "请假")
    if v in ("0.00", "0"):
        return ("△", "#e67e22", "缺卡(单向打卡)")
    try:
        h = float(v)
        if h <= 0:
            return ("△", "#e67e22", "缺卡(单向打卡)")
        return (f"{h:.1f}", "#27ae60", f"出勤{h:.1f}h")
    except ValueError:
        return (v, "#95a5a6", v)


def load_latest_data(data_dir=None):
    data_dir = data_dir or OUTPUT_DIR
    files = sorted(glob.glob(os.path.join(data_dir, "云筑网考勤统计_*.json")))
    if not files:
        return None
    with open(files[-1], "r") as f:
        raw = json.load(f)
    return raw["data"]


def get_day_labels(data):
    """从数据字段名解析天数列，支持 每日工时_2日 和 每日工时_7月2日 两种格式"""
    keys = [k for k in (data[0].keys() if data else []) if k.startswith("每日工时_")]
    # 排序：提取字段名中所有数字，取最后一个（日）排序
    def sort_key(k):
        nums = re.findall(r'\d+', k)
        return int(nums[-1]) if nums else 0
    keys.sort(key=sort_key)
    days = []
    day_keys = []
    for k in keys:
        # 匹配 "每日工时_07月2日" 或 "每日工时_2日"
        m = re.search(r'每日工时_(?:\d+月)?(\d+)日', k)
        if m:
            d = int(m.group(1))
            # 提取月份部分
            month_m = re.search(r'每日工时_(\d+月)', k)
            month_part = month_m.group(1) if month_m else ""
            days.append(f"{month_part}{d}日")
            day_keys.append(k)
    return days, day_keys
    return days, day_keys


def generate_group_html(gname, members, days, day_keys):
    rows_html = ""
    for w in members:
        cells_html = ""
        for i, dk in enumerate(day_keys):
            s, color, tip = status_style(w.get(dk, ""))
            cells_html += (
                f'<td style="text-align:center;padding:3px 5px;'
                f'color:{color};font-weight:bold;font-size:13px" '
                f'title="{days[i]}: {tip}">{s}</td>'
            )
        rows_html += f"""<tr>
            <td style="padding:3px 10px;white-space:nowrap;font-weight:bold">{w.get("姓名","")}</td>
            <td style="padding:3px 10px;font-size:12px;color:#666">{w.get("工种","")}</td>
            <td style="text-align:center;padding:3px 8px">{w.get("出勤天数","")}天</td>
            <td style="text-align:center;padding:3px 8px;font-weight:bold">{w.get("总工时","")}</td>
            {cells_html}
        </tr>"""

    total_attend = sum(
        int(d.get("出勤天数", 0) or 0) for d in members
        if str(d.get("出勤天数", "")).isdigit()
    )
    total_hours = sum(
        float(d.get("总工时", 0) or 0) for d in members
        if str(d.get("总工时", "")).replace(".", "").isdigit()
    )
    defect_counts = []
    for dk in day_keys:
        missing = sum(1 for w in members if status_style(w.get(dk, ""))[0] in ("✗", "△"))
        defect_counts.append(missing)

    defect_bar = " | ".join(
        f'<span style="color:{"#e74c3c" if c > 0 else "#b2bec3"};font-weight:bold">{c}</span>'
        for c in defect_counts
    )

    html = f"""
<div style="margin-bottom:0">
    <div style="display:flex;justify-content:space-between;align-items:center;
                background:linear-gradient(135deg,#667eea,#764ba2);color:white;
                padding:10px 14px;border-radius:6px 6px 0 0">
        <div>
            <span style="font-size:15px;font-weight:bold">{gname}</span>
            <span style="font-size:12px;opacity:0.85;margin-left:8px">{len(members)}人</span>
        </div>
        <div style="font-size:12px;opacity:0.9">
            出勤 {total_attend}天 | 工时 {total_hours:.1f}h
        </div>
    </div>
    <table style="width:100%;border-collapse:collapse;font-size:13px;border:1px solid #dee2e6">
        <thead>
            <tr style="background:#f8f9fa;border-bottom:2px solid #dee2e6">
                <th style="padding:5px 10px;text-align:left">姓名</th>
                <th style="padding:5px 10px;text-align:left">工种</th>
                <th style="padding:5px 8px;text-align:center">出勤</th>
                <th style="padding:5px 8px;text-align:center">工时</th>
                {"".join(f'<th style="padding:4px 4px;text-align:center;font-size:12px;color:#666">{d}</th>' for d in days)}
            </tr>
        </thead>
        <tbody>
            {rows_html}
        </tbody>
    </table>
    <div style="background:#f1f2f6;padding:5px 10px;font-size:11px;color:#636e72;
                border:1px solid #dee2e6;border-top:none;border-radius:0 0 6px 6px">
        每日异常人数: {defect_bar}
    </div>
</div>"""
    return html


def generate_all(data=None, output_dir=None):
    if data is None:
        data = load_latest_data()
    if not data:
        print("错误: 无数据")
        return {}

    output_dir = output_dir or OUTPUT_DIR
    os.makedirs(output_dir, exist_ok=True)

    onsite = [d for d in data if d.get("考勤卡状态", "") not in ("已销卡", "停用")]
    if not onsite:
        print("错误: 无在场工人")
        return {}

    groups = OrderedDict()
    for d in onsite:
        g = d.get("班组", "未分组")
        groups.setdefault(g, []).append(d)

    days, day_keys = get_day_labels(onsite)

    from playwright.sync_api import sync_playwright

    p_ctx = None
    result = {}

    try:
        p_ctx = sync_playwright()
        p_obj = p_ctx.__enter__()
        browser = p_obj.chromium.launch(headless=True)

        for gname, members in sorted(groups.items(), key=lambda x: -len(x[1])):
            safe_name = re.sub(r'[\\/*?:"<>|]', "_", gname)
            img_path = os.path.join(output_dir, f"班组_{safe_name}.jpg")
            print(f"  生成: {gname} ({len(members)}人) -> {img_path}")

            group_html = generate_group_html(gname, members, days, day_keys)
            legend = """
            <div style="background:#fef9e7;padding:6px 12px;border-radius:4px;font-size:11px;color:#7f8c8d">
                图例: <span style="color:#27ae60;font-weight:bold">11.6</span>=正常出勤
                | <span style="color:#e67e22;font-weight:bold">△</span>=缺卡(单向打卡)
                | <span style="color:#e74c3c;font-weight:bold">✗</span>=未打卡
                | <span style="color:#f39c12;font-weight:bold">休</span>=请假
            </div>"""

            html = f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
<style>
body {{ font-family: "Microsoft YaHei","PingFang SC",sans-serif; margin:0; padding:0; background:#fff; width:760px }}
table {{ font-size:13px }}
td, th {{ border-bottom:1px solid #eee }}
tr:hover {{ background:#f5f6fa }}
</style>
</head><body>
{legend}
{group_html}
<div style="font-size:10px;color:#b2bec3;text-align:center;padding:6px 0">
    云筑网劳务实名制 · 自动生成 {datetime.now().strftime("%Y-%m-%d %H:%M")}
</div>
</body></html>"""

            page = browser.new_page(viewport={"width": 760, "height": 100}, locale="zh-CN")
            page.set_content(html, wait_until="networkidle")
            height = page.evaluate("document.documentElement.scrollHeight")
            page.set_viewport_size({"width": 760, "height": height + 30})
            page.wait_for_timeout(500)
            page.screenshot(path=img_path, full_page=True, type="jpeg", quality=90)
            page.close()
            result[gname] = img_path

        browser.close()
    finally:
        if p_ctx:
            p_ctx.__exit__(None, None, None)

    print(f"\n共生成 {len(result)} 张班组图片")
    return result


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument("--data", help="指定 JSON 数据文件路径")
    parser.add_argument("--output", help="输出目录")
    args = parser.parse_args()

    data = None
    if args.data:
        with open(args.data, "r") as f:
            raw = json.load(f)
        data = raw["data"] if "data" in raw else raw

    result = generate_all(data, output_dir=args.output)

    if result:
        print("\n生成的图片:")
        for gname, path in result.items():
            print(f"  {gname}: {path}")
    else:
        print("未生成任何图片")
        sys.exit(1)

