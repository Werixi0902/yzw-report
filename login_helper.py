"""
login_helper.py - 云筑网登录助手（自动打开浏览器版本）
"""

import os, sys, json, time, argparse, subprocess
from datetime import datetime
sys.path.insert(0, r'C:\Users\Yuan\.cache\codex-runtimes\codex-primary-runtime\dependencies\python\Lib\site-packages')

COOKIE_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "configs", "yzw_cookies.json")


def cmd_login():
    """自动打开浏览器让用户登录，30秒后自动导出Cookie"""
    from playwright.sync_api import sync_playwright
    
    os.makedirs(os.path.dirname(COOKIE_FILE), exist_ok=True)
    
    print("="*60)
    print("  云筑网登录助手")
    print("="*60)
    print()
    print("  浏览器已自动打开，请在浏览器中完成以下操作：")
    print("  1. 输入账号: 青塔改造项目")
    print("  2. 输入密码: qingta123*")
    print("  3. 完成验证码验证")
    print("  4. 登录成功后等待自动导出Cookie")
    print("  (等待时间: 最长120秒)")
    print()
    
    with sync_playwright() as p:
        browser = p.chromium.launch(
            headless=False,
            args=["--start-maximized"]
        )
        context = browser.new_context(
            viewport={"width": 1920, "height": 980},
            locale="zh-CN",
            timezone_id="Asia/Shanghai",
            user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        )
        page = context.new_page()
        page.goto("https://lw.yzw.cn/portal", wait_until="networkidle")
        
        print("  ⏳ 等待您登录...（最长120秒）")
        
        # 轮询检查是否登录成功（每2秒检查一次URL变化）
        start_time = time.time()
        logged_in = False
        while time.time() - start_time < 120:
            time.sleep(2)
            current_url = page.url
            # 如果URL不再是portal，说明可能跳转了
            if "portal" not in current_url and "lw.yzw.cn" in current_url:
                logged_in = True
                print(f"  检测到页面跳转: {current_url}")
                break
            # 同时也检查是否有Cookie（某些登录不会跳转）
            cookies = context.cookies()
            has_session = any("session" in c["name"].lower() or "token" in c["name"].lower() for c in cookies)
            if has_session and len(cookies) > 5:
                logged_in = True
                print("  检测到登录Cookie")
                break
        
        if logged_in:
            time.sleep(1)
            cookies = context.cookies()
            with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            print(f"\n  ✅ Cookie 已保存! 共 {len(cookies)} 个")
            
            # 验证
            page.goto("https://lw.yzw.cn/ProjectAttendance/Statistic", wait_until="networkidle", timeout=30000)
            time.sleep(2)
            cur_url = page.url
            if "ProjectAttendance" in cur_url or "Statistic" in cur_url:
                print(f"  ✅ 登录验证成功！")
            else:
                print(f"  ⚠️ 可能未登录成功, URL: {cur_url}")
        else:
            print("\n  ⏰ 等待超时，但Cookie仍会保存当前状态")
            cookies = context.cookies()
            if cookies:
                with open(COOKIE_FILE, "w", encoding="utf-8") as f:
                    json.dump(cookies, f, ensure_ascii=False, indent=2)
                print(f"  已保存 {len(cookies)} 个 Cookie（可能未登录）")
            else:
                print("  未获取到任何Cookie")
        
        browser.close()
    
    print("\n  后续步骤：")
    print("    验证Cookie: python login_helper.py --validate")
    print("    测试抓取:   python main.py --once")
    print()


def cmd_validate():
    """验证Cookie是否有效"""
    from playwright.sync_api import sync_playwright
    
    if not os.path.exists(COOKIE_FILE):
        print(f"Cookie文件不存在: {COOKIE_FILE}")
        print("请先运行 python login_helper.py")
        return
    
    with open(COOKIE_FILE, "r", encoding="utf-8") as f:
        cookies = json.load(f)
    print(f"共 {len(cookies)} 个 Cookie，正在验证...")
    
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1920, "height": 1080}, locale="zh-CN")
        context.add_cookies(cookies)
        page = context.new_page()
        page.goto("https://lw.yzw.cn/ProjectAttendance/Statistic", wait_until="networkidle", timeout=30000)
        time.sleep(2)
        cur_url = page.url
        print(f"当前URL: {cur_url}")
        if "ProjectAttendance" in cur_url:
            print("✅ Cookie 有效！可以正常抓取")
            # 截个图
            os.makedirs("data", exist_ok=True)
            page.screenshot(path=os.path.join("data", "validate_result.png"), full_page=True)
            print("📷 页面截图已保存到 data/validate_result.png")
        elif "portal" in cur_url:
            print("❌ Cookie 已过期，请重新运行 python login_helper.py")
        else:
            print(f"⚠️ 未知重定向: {cur_url}")
        browser.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--validate", action="store_true", help="验证Cookie")
    args = parser.parse_args()
    if args.validate:
        cmd_validate()
    else:
        cmd_login()
