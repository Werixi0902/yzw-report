"""
scraper_engine.py - 通用网页数据抓取引擎

支持两种抓取方式：
  1. requests 模式：适用于静态 HTML 页面
  2. browser 模式：适用于需要 JavaScript 渲染的动态页面（使用 Playwright）

使用示例：
    from scraper_engine import ScraperEngine
    
    engine = ScraperEngine(site_config)
    data = engine.run()
"""

import os
import re
import json
import time
import logging
from datetime import datetime
from typing import Dict, List, Any, Optional

logger = logging.getLogger(__name__)


def _import_requests():
    try:
        import requests
        return requests
    except ImportError:
        logger.error("requests 库未安装，请执行: pip install requests")
        return None


def _import_bs4():
    try:
        from bs4 import BeautifulSoup
        return BeautifulSoup
    except ImportError:
        logger.error("beautifulsoup4 库未安装，请执行: pip install beautifulsoup4")
        return None


def _import_playwright():
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError:
        logger.error("playwright 库未安装，请执行: pip install playwright && playwright install")
        return None


class ScraperEngine:
    """
    通用数据抓取引擎

    Args:
        site_config: 站点配置字典
        data_dir: 数据存储目录
    """

    def __init__(self, site_config: Dict[str, Any], data_dir: str = "./data"):
        self.config = site_config
        self.data_dir = data_dir
        self.name = site_config.get("name", "未知站点")
        self.base_url = site_config.get("base_url", "")
        self.login_url = site_config.get("login_url", "")
        self.data_url = site_config.get("data_url", "")
        self.method = site_config.get("method", "requests")
        self.login_method = site_config.get("login_method", "none")
        self.cookie_file = site_config.get("cookie_file", "")
        self.fields = site_config.get("fields", {})
        self.pagination = site_config.get("pagination", {"enabled": False})
        self.request_interval = site_config.get("request_interval", 2)
        self.timeout = site_config.get("timeout", 30)
        self.browser_config = site_config.get("browser_config", {})

    def run(self) -> List[Dict[str, str]]:
        logger.info(f"开始抓取 [{self.name}] -> {self.data_url}")

        if self.method == "browser":
            return self._scrape_with_browser()
        else:
            return self._scrape_with_requests()

    # ==================== requests 抓取方式 ====================

    def _scrape_with_requests(self) -> List[Dict[str, str]]:
        requests = _import_requests()
        BeautifulSoup = _import_bs4()
        if requests is None or BeautifulSoup is None:
            return []

        session = requests.Session()
        session.headers.update({
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
            "Accept-Language": "zh-CN,zh;q=0.9,en;q=0.8",
        })

        if self.login_method == "cookie" and self.cookie_file:
            self._load_cookies(session)
        elif self.login_method == "form":
            self._form_login(session)

        all_data = []
        max_pages = self.pagination.get("max_pages", 1) if self.pagination.get("enabled") else 1

        for page in range(1, max_pages + 1):
            url = self._build_page_url(page)
            logger.info(f"  请求页面 {page}: {url}")
            resp = self._safe_request(session, "GET", url)
            if resp is None:
                break
            soup = BeautifulSoup(resp.text, "html.parser")
            page_data = self._parse_page(soup)
            all_data.extend(page_data)
            logger.info(f"  页面 {page} 提取到 {len(page_data)} 条数据")
            if not self._has_next_page(soup):
                break
            time.sleep(self.request_interval)

        self._save_results(all_data)
        return all_data

    def _load_cookies(self, session) -> None:
        if not os.path.exists(self.cookie_file):
            logger.warning(f"Cookie 文件不存在: {self.cookie_file}")
            logger.warning("请先运行 python login_helper.py 进行登录")
            return
        try:
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                cookies = json.load(f)
            for cookie in cookies:
                if isinstance(cookie, dict):
                    session.cookies.set(
                        cookie.get("name", ""),
                        cookie.get("value", ""),
                        domain=cookie.get("domain", self.base_url)
                    )
            logger.info(f"已加载 {len(cookies)} 个 Cookie")
        except Exception as e:
            logger.error(f"加载 Cookie 失败: {e}")

    def _form_login(self, session) -> bool:
        requests = _import_requests()
        if requests is None:
            return False
        login_fields = self.config.get("login_fields", {})
        if not login_fields:
            logger.warning("未配置登录字段")
            return False
        try:
            resp = self._safe_request(session, "POST", self.login_url, data=login_fields)
            if resp and resp.status_code == 200:
                logger.info("表单登录成功")
                return True
            else:
                logger.warning("表单登录失败")
                return False
        except Exception as e:
            logger.error(f"登录异常: {e}")
            return False

    def _build_page_url(self, page: int) -> str:
        pagination_type = self.pagination.get("type", "url_param")
        if pagination_type == "url_param":
            param = self.pagination.get("param_name", "page")
            if "?" in self.data_url:
                return f"{self.data_url}&{param}={page}"
            else:
                return f"{self.data_url}?{param}={page}"
        return self.data_url

    def _safe_request(self, session, method: str, url: str, **kwargs) -> Optional[Any]:
        requests = _import_requests()
        if requests is None:
            return None
        retry_times = self.config.get("retry_times", 3)
        for attempt in range(retry_times):
            try:
                resp = session.request(method, url, timeout=self.timeout, **kwargs)
                resp.raise_for_status()
                return resp
            except requests.exceptions.RequestException as e:
                logger.warning(f"  请求失败 (第{attempt + 1}次): {e}")
                if attempt < retry_times - 1:
                    time.sleep(2 ** attempt)
        return None

    def _parse_page(self, soup) -> List[Dict[str, str]]:
        results = []
        first_selector = list(self.fields.values())[0] if self.fields else ""
        rows = soup.select(first_selector) if first_selector else []
        if not rows:
            row_data = {}
            for field_name, selector in self.fields.items():
                elements = soup.select(selector)
                row_data[field_name] = elements[0].get_text(strip=True) if elements else ""
            if any(row_data.values()):
                results.append(row_data)
            return results
        for row in rows:
            row_data = {}
            for field_name, selector in self.fields.items():
                elem = row.select_one(selector)
                row_data[field_name] = elem.get_text(strip=True) if elem else ""
            results.append(row_data)
        return results

    def _has_next_page(self, soup) -> bool:
        pagination_type = self.pagination.get("type", "url_param")
        if pagination_type != "click":
            return True
        next_btn = soup.select_one(".next, .pagination-next, a:contains('下一页')")
        if next_btn:
            classes = next_btn.get("class", [])
            return not ("disabled" in classes)
        return False

    # ==================== Playwright 浏览器抓取方式 ====================

    def _scrape_with_browser(self) -> List[Dict[str, str]]:
        """
        使用 Playwright 浏览器自动化抓取动态页面
        支持自动翻页获取全部数据
        """
        sync_playwright = _import_playwright()
        if sync_playwright is None:
            logger.warning("Playwright 不可用，降级为 requests 模式")
            return self._scrape_with_requests()

        all_data = []
        bc = self.browser_config

        with sync_playwright() as pw:
            browser = pw.chromium.launch(
                headless=bc.get("headless", True),
                args=["--disable-blink-features=AutomationControlled"]
            )
            context = browser.new_context(
                viewport={"width": bc.get("viewport_width", 1920), "height": bc.get("viewport_height", 1080)},
                locale=bc.get("locale", "zh-CN"),
                timezone_id=bc.get("timezone", "Asia/Shanghai"),
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            )

            # 加载 Cookie
            self._load_browser_cookies(context)
            page = context.new_page()

            # 访问数据页面
            login_success = self._browser_login_if_needed(page)
            if not login_success:
                logger.error("Cookie 登录失败，请重新运行: python login_helper.py")
                browser.close()
                return []

            # ---- 初始化：移除遮罩、设置每页条数 ----

            # ---- 设置筛选条件：仅查看区间在场人员 ----
            try:
                sel_filter = page.query_selector("#selIsHistoryEntry")
                if sel_filter:
                    sel_filter.select_option("1")
                    logger.info("筛选条件已设为：仅查看区间在场人员")
                    page.wait_for_timeout(1000)
                else:
                    logger.warning("未找到工人范围筛选控件")
            except Exception as e:
                logger.warning(f"设置筛选条件失败: {e}")

            # ---- 点击查询按钮刷新数据 ----
            try:
                query_btn = page.query_selector("a#btnQuery")
                if query_btn:
                    query_btn.dispatch_event("click")
                    logger.info("已点击查询按钮，数据刷新中...")
                    page.wait_for_timeout(3000)
                else:
                    logger.warning("未找到查询按钮")
            except Exception as e:
                logger.warning(f"点击查询按钮失败: {e}")
            # ---- 动态检测表格表头结构（月份+天数列） ----
            if self.config.get("dynamic_dates", False):
                self._detect_table_structure(page)
            if bc.get("remove_overlay"):
                page.evaluate("document.querySelectorAll(\"[class*='cover'], [class*='modal-mask']\").forEach(e => e.remove())")
                logger.info("遮罩层已移除")

            page_size = self.pagination.get("page_size", 100)
            try:
                page.evaluate(f'document.querySelector("#attendanceTable_length select") && ' +
                              f'(document.querySelector("#attendanceTable_length select").value = "{page_size}") && ' +
                              f'document.querySelector("#attendanceTable_length select").dispatchEvent(new Event("change"))')
                logger.info(f"每页条数已设为 {page_size}")
                page.wait_for_timeout(2000)
            except Exception as e:
                logger.warning(f"设置每页条数失败: {e}")

            # 获取总记录数
            total_info = page.inner_text("#attendanceTable_info") if page.query_selector("#attendanceTable_info") else ""
            logger.info(f"表格信息: {total_info}")

            # ---- 翻页提取数据 ----
            max_pages = self.pagination.get("max_pages", 10)
            next_sel = self.pagination.get("next_selector", "#attendanceTable_next:not(.disabled)")

            for pg in range(1, max_pages + 1):
                logger.info(f"  提取第 {pg} 页...")
                page_data = self._parse_page_with_browser(page)
                all_data.extend(page_data)
                logger.info(f"  第 {pg} 页提取到 {len(page_data)} 条数据（累计 {len(all_data)} 条）")

                # 检查是否有下一页
                next_btn = page.query_selector(next_sel)
                if not next_btn:
                    logger.info("  没有更多页，提取完成")
                    break

                try:
                    next_btn.click()
                    page.wait_for_timeout(2000)
                except Exception as e:
                    logger.warning(f"  翻页失败: {e}")
                    break

                time.sleep(self.request_interval)

            browser.close()

        self._save_results(all_data)
        return all_data

    def _load_browser_cookies(self, context) -> bool:
        """为浏览器上下文加载 Cookie（适配 Playwright 的 Cookie 格式）"""
        if self.login_method != "cookie" or not self.cookie_file:
            return False

        if not os.path.exists(self.cookie_file):
            logger.warning(f"Cookie 文件不存在: {self.cookie_file}")
            return False

        try:
            with open(self.cookie_file, "r", encoding="utf-8") as f:
                cookies_data = json.load(f)

            # Playwright 的 add_cookies 要求特定格式
            valid_cookies = []
            for c in cookies_data:
                cookie = {
                    "name": c.get("name", ""),
                    "value": c.get("value", ""),
                    "domain": c.get("domain", ".yzw.cn"),
                    "path": c.get("path", "/"),
                }
                if "httpOnly" in c:
                    cookie["httpOnly"] = c["httpOnly"]
                if "secure" in c:
                    cookie["secure"] = c["secure"]
                if "sameSite" in c and c["sameSite"]:
                    cookie["sameSite"] = c["sameSite"]
                if "expires" in c and c["expires"]:
                    cookie["expires"] = c["expires"]
                valid_cookies.append(cookie)

            if valid_cookies:
                context.add_cookies(valid_cookies)
                logger.info(f"浏览器已加载 {len(valid_cookies)} 个 Cookie")
                return True
            else:
                logger.warning("Cookie 文件为空")
                return False

        except Exception as e:
            logger.error(f"加载浏览器 Cookie 失败: {e}")
            return False

    def _browser_login_if_needed(self, page) -> bool:
        """
        访问数据页面，检查是否需要登录
        如果被重定向到 portal，说明 Cookie 已过期
        """
        try:
            page.goto(self.data_url, wait_until="networkidle", timeout=self.timeout * 1000)
            page.wait_for_timeout(3000)

            current_url = page.url
            logger.info(f"  访问数据页面后的 URL: {current_url}")

            # 检查是否被重定向到 portal（未登录）
            if "portal" in current_url or "login" in current_url.lower():
                logger.warning("Cookie 已过期或被重定向到登录页")
                logger.warning("请重新运行: python login_helper.py")
                return False

            logger.info("Cookie 登录验证成功！")
            return True

        except Exception as e:
            logger.error(f"  访问数据页面异常: {e}")
            return False

    def _parse_page_with_browser(self, page) -> List[Dict[str, str]]:
        """
        使用 Playwright page 对象提取数据
        优先使用 JavaScript 批量提取表格数据
        """
        # ---- 动态读取表头日期标签 ----
        # 读取云筑网考勤表 <thead> 中的日期列标题
        # 解决日期列偏移问题（如7月11日网站显示2日~11日而非1日~10日）
        date_labels = {}
        try:
            header_dates = page.evaluate("""() => {
                const headers = document.querySelectorAll('#attendanceTable thead tr th');
                const dates = [];
                for (let i = 0; i < headers.length; i++) {
                    const text = headers[i].textContent.trim();
                    // 匹配 "X日" 格式的日期列
                    if (/^\\d{1,2}日$/.test(text)) {
                        dates.push({index: i, label: text});
                    }
                }
                return dates;
            }""")
            # 建立 "每日工时_Y日" -> 实际列索引的映射
            # 例如网站显示 2日~11日，则 "每日工时_1日" 应映射到 2日 那列
            actual_dates = [d['label'] for d in header_dates]
            static_dates = [f"{d}日" for d in range(1, len(actual_dates) + 1)]
            for static_label, actual_label in zip(static_dates, actual_dates):
                date_labels[static_label] = actual_label
            logger.info(f"  动态日期映射: {dict(zip(static_dates, actual_dates))}")
        except Exception as e:
            logger.warning(f"  无法读取表头日期: {e}，将使用静态字段名")
        
        if not self.fields:
            return []

        # 自动推断行选择器：取第一个字段选择器的父级tr
        first_sel = list(self.fields.values())[0]
        row_sel = self._guess_row_selector(first_sel)

        try:
            # 方案1: 使用JS批量提取（推荐，性能好）
            js_fields = {}
            for field_name, selector in self.fields.items():
                # 提取单元格索引 nth-child(N)
                import re as _re
                m = _re.search(r':nth-child\((\d+)\)', selector)
                if m:
                    js_fields[field_name] = int(m.group(1)) - 1  # 转0-based索引
                else:
                    js_fields[field_name] = selector  # 保留原始选择器备选

            js_code = f"""
            () => {{
                const rowSelector = '{row_sel}';
                const rows = document.querySelectorAll(rowSelector);
                const result = [];
                const fieldMap = {json.dumps(js_fields, ensure_ascii=False)};

                rows.forEach(row => {{
                    const cells = row.querySelectorAll('td');
                    if (cells.length === 0) return;
                    const rowData = {{}};
                    for (const [fieldName, idxOrSel] of Object.entries(fieldMap)) {{
                        if (typeof idxOrSel === 'number') {{
                            rowData[fieldName] = cells[idxOrSel] ? cells[idxOrSel].innerText.trim() : '';
                        }} else {{
                            const el = row.querySelector(idxOrSel);
                            rowData[fieldName] = el ? el.innerText.trim() : '';
                        }}
                    }}
                    // 跳过全部为空的行
                    if (Object.values(rowData).some(v => v.length > 0)) {{
                        result.push(rowData);
                    }}
                }});
                return result;
            }}
            """
            import json as _json
            row_data = page.evaluate(js_code)
            # ---- 后处理：将静态日期字段名替换为实际日期 ----
            if row_data and date_labels:
                for row in row_data:
                    for static_label, actual_label in date_labels.items():
                        key = f"每日工时_{static_label}"
                        if key in row:
                            new_key = f"每日工时_{actual_label}"
                            row[new_key] = row.pop(key)
            
            if row_data and len(row_data) > 0:
                logger.info(f"  JS批量提取到 {len(row_data)} 条数据")
                return row_data

        except Exception as e:
            logger.warning(f"  JS批量提取失败: {e}")

        # 方案2: 降级为逐行提取
        try:
            import json as _json2
        except:
            pass
        return self._parse_rows_directly(page, row_sel)


    def _guess_row_selector(self, cell_selector: str) -> str:
        """从单元格选择器推断行选择器"""
        # 如果已经是行选择器，直接返回
        if 'tr' in cell_selector.lower() and 'td' not in cell_selector.lower():
            return cell_selector
        # 从 nth-child 选择器提取父级
        table_match = re.search(r'(#[a-zA-Z0-9_-]+)\s+', cell_selector)
        if table_match:
            table_id = table_match.group(1)
            return f"{table_id} tbody tr"
        # 尝试提取 table 选择器
        m = re.search(r'(table[\w.-]*)\s', cell_selector)
        if m:
            return f"{m.group(1)} tbody tr"
        return "table.dataTable tbody tr"

    def _parse_rows_directly(self, page, row_selector: str) -> List[Dict[str, str]]:
        """降级方案：逐行提取数据"""
        results = []
        try:
            rows = page.query_selector_all(row_selector)
            for row in rows:
                row_data = {}
                cells = row.query_selector_all("td")
                for field_name, selector in self.fields.items():
                    # 尝试提取 nth-child 索引
                    m = re.search(r':nth-child\((\d+)\)', selector)
                    if m:
                        idx = int(m.group(1)) - 1
                        if idx < len(cells):
                            row_data[field_name] = cells[idx].inner_text().strip()
                        else:
                            row_data[field_name] = ""
                    else:
                        el = row.query_selector(selector)
                        row_data[field_name] = el.inner_text().strip() if el else ""
                if any(row_data.values()):
                    results.append(row_data)
            logger.info(f"  逐行提取到 {len(results)} 条数据")
        except Exception as e:
            logger.error(f"  逐行提取失败: {e}")
        return results
    def _parse_via_javascript(self, page) -> List[Dict[str, str]]:
        fields = self.fields
        js_parts = []
        for field_name, selector in fields.items():
            escaped_sel = selector.replace("'", "\\'")
            js_parts.append(f"'{field_name}': extractText('{escaped_sel}', i)")

        js_code = f"""
        () => {{
            const extractText = (sel, idx) => {{
                const els = document.querySelectorAll(sel);
                return els[idx] ? els[idx].textContent.trim() : '';
            }};
            const firstSel = '{list(fields.values())[0]}';
            const rows = document.querySelectorAll(firstSel);
            if (rows.length === 0) {{
                const single = {{}};
                {{{', '.join(js_parts)}}}
                return [single];
            }}
            const result = [];
            for (let i = 0; i < rows.length; i++) {{
                result.push({{ {{{', '.join(js_parts)}}} }});
            }}
            return result;
        }}
        """
        try:
            result = page.evaluate(js_code)
            return result if isinstance(result, list) else []
        except Exception as e:
            logger.error(f"  JS 提取失败: {e}")
            return []

    def _browser_next_page(self, page) -> bool:
        pagination_type = self.pagination.get("type", "click")
        try:
            if pagination_type == "click":
                next_selectors = [
                    ".next", ".pagination-next",
                    "a:has-text('下一页')", "a:has-text('>')",
                    "a#btnQuery'下一页')",
                    "[class*='next']", "[aria-label='下一页']",
                    ".ant-pagination-next", "[class*='pagination'] [class*='next']"
                ]
                for sel in next_selectors:
                    btn = page.query_selector(sel)
                    if btn:
                        is_disabled = btn.get_attribute("disabled") or \
                            (btn.get_attribute("class") and "disabled" in btn.get_attribute("class"))
                        if not is_disabled:
                            btn.click()
                            page.wait_for_timeout(2000)
                            return True
                        return False
                return False
            elif pagination_type == "scroll":
                page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
                page.wait_for_timeout(2000)
                return True
            return False
        except Exception as e:
            logger.error(f"  翻页失败: {e}")
            return False


    # ==================== 动态表头检测 ====================

    def _detect_table_structure(self, page):
        """动态检测 #attendanceTable 表头结构，根据配置选择最近N天"""
        result = page.evaluate(r"""
            () => {
                const table = document.querySelector("#attendanceTable");
                if (!table) return {error: "table not found"};
                const ths = table.querySelectorAll("thead th");
                let monthStr = "";
                let totalDayCount = 0;
                ths.forEach(th => {
                    const text = th.innerText.trim();
                    const colspan = parseInt(th.getAttribute("colspan") || "1");
                    if (/^\d{4}年\d{1,2}月$/.test(text) && colspan >= 5) {
                        monthStr = text;
                        totalDayCount = colspan;
                    }
                });
                return {monthStr, totalDayCount};
            }
        """)

        if "error" in result:
            logger.error(f"表格结构检测失败: {result['error']}")
            return None

        month_str = result["monthStr"]
        total_day_count = result["totalDayCount"]

        if not month_str or total_day_count == 0:
            logger.warning("动态表头检测未找到月份/天数列，使用静态配置")
            return None

        FIXED_COLS = 7
        day_start_nth = FIXED_COLS + 1

        day_count = self.config.get("day_count", 10)
        day_mode = self.config.get("day_mode", "last_n")

        if day_mode == "last_n":
            if total_day_count <= day_count:
                selected_days = list(range(1, total_day_count + 1))
            else:
                start_day = total_day_count - day_count + 1
                selected_days = list(range(start_day, total_day_count + 1))
        else:
            selected_days = list(range(1, min(day_count, total_day_count) + 1))

        m = re.match(r'(\d{4})年(\d{2})月', month_str)
        if m:
            year, month_num = m.groups()
            month_label = f"{month_num}月"
        else:
            month_label = month_str

        dynamic_fields = {}
        static_names = ["姓名", "身份证号", "参建单位", "班组", "工种", "考勤卡号", "考勤卡状态"]
        for i, name in enumerate(static_names):
            dynamic_fields[name] = f"#attendanceTable tbody tr td:nth-child({i + 1})"

        day_offset = selected_days[0] - 1
        day_field_keys = []
        day_labels = []
        for i, day in enumerate(selected_days):
            col = day_start_nth + day_offset + i
            field_name = f"每日工时_{month_label}{day}日"
            dynamic_fields[field_name] = f"#attendanceTable tbody tr td:nth-child({col})"
            day_field_keys.append(field_name)
            day_labels.append(f"{month_label}{day}日")

        summary_col = day_start_nth + total_day_count
        dynamic_fields["总工时"] = f"#attendanceTable tbody tr td:nth-child({summary_col})"
        dynamic_fields["请假天数"] = f"#attendanceTable tbody tr td:nth-child({summary_col + 1})"
        dynamic_fields["出勤天数"] = f"#attendanceTable tbody tr td:nth-child({summary_col + 2})"
        dynamic_fields["有效工天"] = f"#attendanceTable tbody tr td:nth-child({summary_col + 3})"

        self.fields = dynamic_fields
        self._table_meta = {
            "month": month_str,
            "total_days": total_day_count,
            "selected_days": selected_days,
            "day_field_keys": day_field_keys,
            "day_labels": day_labels,
            "day_start_nth": day_start_nth,
        }

        logger.info(f"表格结构: {month_str}, 共{total_day_count}天, 选取最近{len(selected_days)}天: {selected_days[0]}日~{selected_days[-1]}日")
        return self._table_meta

    # ==================== 数据存储 ====================

    def _save_results(self, data: List[Dict[str, str]]) -> str:
        if not data:
            logger.warning("没有数据需要保存")
            return ""

        os.makedirs(self.data_dir, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_name = re.sub(r'[\\/*?:"<>|]', "_", self.name)
        filename = f"{safe_name}_{timestamp}.json"
        filepath = os.path.join(self.data_dir, filename)

        output = {
            "site": self.name,
            "url": self.data_url,
            "fetch_time": datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
            "total_count": len(data),
            "table_meta": getattr(self, "_table_meta", None),
            "fields": list(self.fields.keys()),
            "data": data,
        }

        with open(filepath, "w", encoding="utf-8") as f:
            json.dump(output, f, ensure_ascii=False, indent=2)

        logger.info(f"数据已保存: {filepath} ({len(data)} 条)")
        return filepath







