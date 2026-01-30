"""
GooseGooseDuck (Gaggle Fun) 游戏记录爬虫
登录并抓取游戏记录数据，生成HTML展示
"""

import time
import json
import os
from datetime import datetime
from string import Template
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.action_chains import ActionChains
from selenium.webdriver.support.ui import WebDriverWait, Select
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException
import random
import base64


def get_html_template():
    """返回固定的HTML模板 - 直接显示原始数据"""
    return '''<!DOCTYPE html>
<html lang="zh-CN">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>Gaggle Fun 🎮 游戏记录</title>
    <link href="https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap" rel="stylesheet">
    <style>
        :root {
            --main: #46a6f8;
            --bgcolor: #100a21;
            --bgcolor-card: #1e1535;
            --text: #ffffff;
            --text-secondary: #b3b3b3;
            --text-muted: #707070;
            --gradient-primary: linear-gradient(90deg, #00a6ff 0%, #c369ff 52.4%, #ff4590 100%);
        }
        * { margin: 0; padding: 0; box-sizing: border-box; }
        body {
            font-family: 'Inter', 'Microsoft YaHei', sans-serif;
            background-color: var(--bgcolor);
            color: var(--text);
            min-height: 100vh;
            padding: 40px 20px;
        }
        .container { max-width: 1200px; margin: 0 auto; }
        h1 {
            font-size: 28px;
            margin-bottom: 10px;
            background: var(--gradient-primary);
            -webkit-background-clip: text;
            -webkit-text-fill-color: transparent;
            background-clip: text;
        }
        .subtitle { color: var(--text-secondary); margin-bottom: 30px; }
        .stats {
            display: flex;
            gap: 20px;
            margin-bottom: 30px;
            flex-wrap: wrap;
        }
        .stat-item {
            background: var(--bgcolor-card);
            padding: 20px 30px;
            border-radius: 12px;
            text-align: center;
            min-width: 120px;
        }
        .stat-value { font-size: 32px; font-weight: 700; color: var(--main); }
        .stat-label { font-size: 14px; color: var(--text-muted); margin-top: 5px; }

        /* 游戏记录表格 */
        .records-table {
            width: 100%;
            border-collapse: collapse;
            background: var(--bgcolor-card);
            border-radius: 12px;
            overflow: hidden;
        }
        .records-table th {
            background: rgba(70, 166, 248, 0.2);
            color: var(--main);
            padding: 15px;
            text-align: left;
            font-weight: 600;
            font-size: 14px;
        }
        .records-table td {
            padding: 12px 15px;
            border-bottom: 1px solid rgba(255,255,255,0.05);
            font-size: 14px;
        }
        .records-table tr:hover {
            background: rgba(70, 166, 248, 0.1);
        }
        .records-table tr:last-child td {
            border-bottom: none;
        }

        /* 胜负标签 */
        .win-tag {
            background: #10b981;
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }
        .loss-tag {
            background: #ef4444;
            color: white;
            padding: 4px 12px;
            border-radius: 12px;
            font-size: 12px;
            font-weight: 600;
        }

        /* 阵营颜色 */
        .goose { color: #22c55e; font-weight: 600; }
        .duck { color: #ef4444; font-weight: 600; }

        .footer {
            text-align: center;
            margin-top: 40px;
            color: var(--text-muted);
            font-size: 14px;
        }
        .footer a { color: var(--main); text-decoration: none; }
        .footer a:hover { text-decoration: underline; }
    </style>
</head>
<body>
    <div class="container">
        <h1>🦆 GooseGooseDuck 游戏记录</h1>
        <p class="subtitle">生成时间: $generation_time | 共 $total_records 条记录</p>

        <div class="stats">
            <div class="stat-item">
                <div class="stat-value">$total_records</div>
                <div class="stat-label">总记录</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">$wins</div>
                <div class="stat-label">胜利</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">$losses</div>
                <div class="stat-label">失败</div>
            </div>
            <div class="stat-item">
                <div class="stat-value">$win_rate%</div>
                <div class="stat-label">胜率</div>
            </div>
        </div>

        <table class="records-table">
            <thead>
                <tr>
                    <th>#</th>
                    $table_headers
                </tr>
            </thead>
            <tbody>
                $table_rows
            </tbody>
        </table>

        <div class="footer">
            数据来源: <a href="https://gaggle.fun">Gaggle Fun</a>
        </div>
    </div>
</body>
</html>'''


class GaggleFunScraper:
    """Gaggle Fun 游戏记录爬虫"""

    LOGIN_URL = "https://gaggle.fun/auth/login"
    GAME_STATS_URL = "https://gaggle.fun/dashboard/game-stats"

    def __init__(self, headless=False):
        options = Options()
        if headless:
            options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')
        # 启用性能日志以捕获网络事件
        try:
            options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})
        except Exception:
            pass

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 20)
        self.game_records = []  # 将作为按行的二维数组保存
        self.table_headers = []  # 从 .games-header .grid-container 提取的表头标签
        # 启用 CDP 网络监听
        try:
            self.driver.execute_cdp_cmd('Network.enable', {})
        except Exception:
            pass
        # 最近一次错误代码（如 invalid_credentials）
        self.last_error = None

    def login(self, email, password):
        """登录"""
        print("正在登录...")
        self.last_error = None
        self.driver.get(self.LOGIN_URL)
        time.sleep(3)

        # 输入邮箱
        try:
            email_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="email"]'))
            )
            email_input.send_keys(email)
        except:
            return False

        # 输入密码
        try:
            pwd_input = self.driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
            pwd_input.send_keys(password)
        except:
            return False

        # 点击登录
        try:
            btn = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            btn.click()
        except:
            return False

        # 等待：成功跳转或出现 toast 错误
        end = time.time() + 15
        while time.time() < end:
            try:
                cur = (self.driver.current_url or '').lower()
            except Exception:
                cur = ''
            # 成功：不在登录页即可认为成功
            if 'login' not in cur:
                print("登录成功！")
                return True
            # 检测 p-toast 错误提示
            try:
                items = self.driver.find_elements(By.CSS_SELECTOR, 'p-toastitem .p-toast-message-text')
            except Exception:
                items = []
            for it in items:
                try:
                    summary_el = it.find_element(By.CSS_SELECTOR, '.p-toast-summary')
                    detail_el = it.find_element(By.CSS_SELECTOR, '.p-toast-detail')
                    summary = (summary_el.text or '').strip()
                    detail = (detail_el.text or '').strip()
                except Exception:
                    summary = ''
                    detail = ''
                # 识别“用户名或密码错误”提示（英文原文）
                if summary.lower() == 'error' and ('incorrect' in detail.lower() or 'password is incorrect' in detail.lower()):
                    self.last_error = 'invalid_credentials'
                    return False
            time.sleep(0.5)
        # 超时仍在登录页，视为失败（未知原因）
        return False

    def save_cookies(self, path):
        try:
            os.makedirs(os.path.dirname(path), exist_ok=True)
        except Exception:
            pass
        try:
            cookies = self.driver.get_cookies()
            with open(path, 'w', encoding='utf-8') as f:
                json.dump(cookies, f, ensure_ascii=False, indent=2)
            return True
        except Exception:
            return False

    def try_cookie_login(self, cookies_path: str) -> bool:
        try:
            if not cookies_path or not os.path.exists(cookies_path):
                return False
            # 先打开登录域，才能 add_cookie
            self.driver.get(self.LOGIN_URL)
            time.sleep(1)
            with open(cookies_path, 'r', encoding='utf-8') as f:
                cookies = json.load(f) or []
            for c in cookies:
                try:
                    cc = {k: v for k, v in c.items() if k in ('name','value','domain','path','expiry','httpOnly','secure','sameSite')}
                    if 'expiry' in cc and isinstance(cc['expiry'], float):
                        try:
                            cc['expiry'] = int(cc['expiry'])
                        except Exception:
                            del cc['expiry']
                    self.driver.add_cookie(cc)
                except Exception:
                    pass
            # 跳转到目标页验证登录状态
            self.driver.get(self.GAME_STATS_URL)
            try:
                self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            except Exception:
                pass
            cur = (self.driver.current_url or '').lower()
            return 'login' not in cur
        except Exception:
            return False

    def fetch_game_records(self, save_path: str = None):
        """获取游戏记录"""
        print("正在获取游戏记录...")
        self.driver.get(self.GAME_STATS_URL)
        time.sleep(5)

        # 等待页面就绪并选择“轮抽”模式（更健壮，多策略 + JS 回退）
        try:
            self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
        except Exception:
            pass

        # 预先清空性能日志，开始监测 XHR/Fetch（在点击前启动）
        try:
            _ = self.driver.get_log('performance')
        except Exception:
            pass

        mode_select_el = None
        selector_strategies = [
            (By.ID, 'statsGameMode'),
            (By.CSS_SELECTOR, 'select#statsGameMode'),
            (By.CSS_SELECTOR, 'select.ng-pristine.ng-valid.ng-touched'),
            (By.XPATH, '//select[@id="statsGameMode"]'),
            (By.XPATH, '//select[option[@value="5"] or option[normalize-space()="轮抽"]]'),
        ]

        for by, sel in selector_strategies:
            try:
                mode_select_el = WebDriverWait(self.driver, 10).until(
                    EC.presence_of_element_located((by, sel))
                )
                break
            except Exception:
                mode_select_el = None

        if mode_select_el is not None:
            try:
                self.driver.execute_script("arguments[0].scrollIntoView({block:'center'});", mode_select_el)
            except Exception:
                pass
            # 拟人化：移动鼠标、停顿、点击打开下拉
            try:
                ActionChains(self.driver).move_to_element(mode_select_el).pause(random.uniform(0.2, 0.6)).click(mode_select_el).perform()
                time.sleep(random.uniform(0.3, 0.8))
            except Exception:
                try:
                    mode_select_el.click()
                    time.sleep(random.uniform(0.3, 0.8))
                except Exception:
                    pass

            applied = False
            # 优先尝试通过可见文本或值进行设置
            try:
                Select(mode_select_el).select_by_visible_text('轮抽')
                applied = True
            except Exception:
                try:
                    Select(mode_select_el).select_by_value('5')
                    applied = True
                except Exception:
                    pass

            if not applied:
                try:
                    # 直接点击 option
                    option_el = mode_select_el.find_element(By.XPATH, './/option[@value="5" or normalize-space()="轮抽"]')
                    ActionChains(self.driver).move_to_element(option_el).pause(random.uniform(0.2, 0.5)).click(option_el).perform()
                    applied = True
                except Exception:
                    pass

            if not applied:
                try:
                    # JS 回退：设置值并触发变更事件
                    self.driver.execute_script(
                        """
                        const s = arguments[0];
                        s.value = '5';
                        s.dispatchEvent(new Event('input', {bubbles: true}));
                        s.dispatchEvent(new Event('change', {bubbles: true}));
                        """,
                        mode_select_el,
                    )
                    applied = True
                except Exception:
                    pass

            if not applied:
                print('未能设置游戏模式为“轮抽”')
            else:
                time.sleep(random.uniform(1.2, 2.0))
        else:
            print('未找到游戏模式选择下拉框（statsGameMode）')
            found_in_iframe = False
            try:
                frames = self.driver.find_elements(By.CSS_SELECTOR, 'iframe, frame')
                for fr in frames:
                    try:
                        self.driver.switch_to.frame(fr)
                        mode_select_el = None
                        for by, sel in selector_strategies:
                            try:
                                mode_select_el = WebDriverWait(self.driver, 5).until(
                                    EC.presence_of_element_located((by, sel))
                                )
                                break
                            except Exception:
                                mode_select_el = None
                        if mode_select_el is not None:
                            applied = False
                            try:
                                Select(mode_select_el).select_by_visible_text('轮抽')
                                applied = True
                            except Exception:
                                try:
                                    Select(mode_select_el).select_by_value('5')
                                    applied = True
                                except Exception:
                                    pass
                            if not applied:
                                try:
                                    option_el = mode_select_el.find_element(By.XPATH, './/option[@value="5" or normalize-space()="轮抽"]')
                                    option_el.click()
                                    applied = True
                                except Exception:
                                    pass
                            if not applied:
                                try:
                                    self.driver.execute_script(
                                        """
                                        const s = arguments[0];
                                        s.value = '5';
                                        s.dispatchEvent(new Event('input', {bubbles: true}));
                                        s.dispatchEvent(new Event('change', {bubbles: true}));
                                        """,
                                        mode_select_el,
                                    )
                                    applied = True
                                except Exception:
                                    pass
                            if applied:
                                found_in_iframe = True
                                time.sleep(2)
                                break
                    except Exception:
                        pass
                    finally:
                        self.driver.switch_to.default_content()
            except Exception:
                self.driver.switch_to.default_content()

            if not found_in_iframe:
                try:
                    frames = self.driver.find_elements(By.CSS_SELECTOR, 'iframe, frame')
                    applied_any = False
                    for fr in frames:
                        try:
                            self.driver.switch_to.frame(fr)
                            applied_js = self.driver.execute_script(
                                """
                                const selects = Array.from(document.querySelectorAll('select'));
                                function setSelect(s){
                                    const opts = Array.from(s.options||[]);
                                    const tgt = opts.find(o => (o.text||'').trim().includes('轮抽') || /Draft/i.test(o.text||''));
                                    if(!tgt) return false;
                                    s.value = tgt.value;
                                    s.dispatchEvent(new Event('input', {bubbles:true}));
                                    s.dispatchEvent(new Event('change', {bubbles:true}));
                                    return true;
                                }
                                for(const s of selects){ if(setSelect(s)) return true; }
                                return false;
                                """
                            )
                            if applied_js:
                                applied_any = True
                                time.sleep(2)
                                break
                        except Exception:
                            pass
                        finally:
                            self.driver.switch_to.default_content()
                    if not applied_any:
                        applied_js = self.driver.execute_script(
                            """
                            const selects = Array.from(document.querySelectorAll('select'));
                            function setSelect(s){
                                const opts = Array.from(s.options||[]);
                                const tgt = opts.find(o => (o.text||'').trim().includes('轮抽') || /Draft/i.test(o.text||''));
                                if(!tgt) return false;
                                s.value = tgt.value;
                                s.dispatchEvent(new Event('input', {bubbles:true}));
                                s.dispatchEvent(new Event('change', {bubbles:true}));
                                return true;
                            }
                            for(const s of selects){ if(setSelect(s)) return true; }
                            return false;
                            """
                        )
                        if applied_js:
                            time.sleep(2)
                        else:
                            print('未能通过JS查找到包含“轮抽/Draft”的下拉框')
                except Exception:
                    pass

        # 监听并抓取 SearchMatches 的响应体
        result = self._wait_for_search_matches(timeout=25)
        if result:
            try:
                if save_path:
                    dir_path = os.path.dirname(save_path)
                    try:
                        os.makedirs(dir_path, exist_ok=True)
                    except Exception:
                        pass
                    tmp_path = save_path + ".tmp"
                    with open(tmp_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    try:
                        os.replace(tmp_path, save_path)
                    except Exception:
                        # 回退：直接写最终文件
                        with open(save_path, 'w', encoding='utf-8') as f:
                            json.dump(result, f, ensure_ascii=False, indent=2)
                    print(f"SearchMatches 响应已保存: {save_path}")
                else:
                    out_dir = os.path.join(os.path.dirname(__file__), 'data', '对局记录文件夹')
                    os.makedirs(out_dir, exist_ok=True)
                    ts = datetime.now().strftime('%Y%m%d_%H%M%S')
                    out_path = os.path.join(out_dir, f'SearchMatches_{ts}.json')
                    with open(out_path, 'w', encoding='utf-8') as f:
                        json.dump(result, f, ensure_ascii=False, indent=2)
                    print(f"SearchMatches 响应已保存: {out_path}")
            except Exception as e:
                print(f"保存 SearchMatches 响应失败: {e}")
        else:
            print('在指定时间内未捕获到 SearchMatches 响应')

        # 按要求：不再通过前端页面抓取表格数据，直接返回空列表
        return []

    def _wait_for_search_matches(self, timeout=20):
        target_prefix = 'https://us-central1-gaggle-staging.cloudfunctions.net/ggdPlayerMatch'
        target_action = 'action=SearchMatches'
        end = time.time() + timeout
        while time.time() < end:
            try:
                logs = self.driver.get_log('performance')
            except Exception:
                logs = []
            for entry in logs:
                try:
                    msg = json.loads(entry.get('message', '{}')).get('message', {})
                except Exception:
                    continue
                if msg.get('method') == 'Network.responseReceived':
                    params = msg.get('params', {})
                    response = params.get('response', {})
                    url = response.get('url', '')
                    if url.startswith(target_prefix) and target_action in url:
                        request_id = params.get('requestId')
                        try:
                            body_obj = self.driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': request_id})
                            body = body_obj.get('body', '')
                            if body_obj.get('base64Encoded'):
                                try:
                                    decoded = base64.b64decode(body).decode('utf-8', errors='ignore')
                                except Exception:
                                    decoded = body
                                text = decoded
                            else:
                                text = body
                            data = None
                            try:
                                data = json.loads(text)
                            except Exception:
                                # 有时返回前可能包含 BOM 或非 JSON 包裹
                                text_stripped = text.strip('\ufeff\n\r\t ')
                                if text_stripped.startswith('{') or text_stripped.startswith('['):
                                    data = json.loads(text_stripped)
                            if data is not None:
                                return {
                                    'url': url,
                                    'status': response.get('status'),
                                    'data': data,
                                }
                        except Exception:
                            pass
            time.sleep(0.5)
        return None

    def fetch_match_detail(self, match_id: str, timeout: int = 20):
        try:
            try:
                _ = self.driver.get_log('performance')
            except Exception:
                pass
            url = f"https://gaggle.fun/dashboard/game-stats/match/{match_id}"
            self.driver.get(url)
            try:
                self.wait.until(lambda d: d.execute_script("return document.readyState") == "complete")
            except Exception:
                pass
            end = time.time() + timeout
            while time.time() < end:
                try:
                    logs = self.driver.get_log('performance')
                except Exception:
                    logs = []
                for entry in logs:
                    try:
                        msg = json.loads(entry.get('message', '{}')).get('message', {})
                    except Exception:
                        continue
                    if msg.get('method') == 'Network.responseReceived':
                        params = msg.get('params', {})
                        response = params.get('response', {})
                        u = response.get('url', '')
                        if isinstance(u, str) and match_id in u:
                            request_id = params.get('requestId')
                            try:
                                body_obj = self.driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': request_id})
                                body = body_obj.get('body', '')
                                if body_obj.get('base64Encoded'):
                                    try:
                                        decoded = base64.b64decode(body).decode('utf-8', errors='ignore')
                                    except Exception:
                                        decoded = body
                                    text = decoded
                                else:
                                    text = body
                                data = None
                                try:
                                    data = json.loads(text)
                                except Exception:
                                    t2 = (text or '').strip('\ufeff\n\r\t ')
                                    if t2.startswith('{') or t2.startswith('['):
                                        data = json.loads(t2)
                                if data is not None:
                                    return data
                            except Exception:
                                pass
                time.sleep(0.5)
            return None
        except Exception:
            return None

    def _extract_headers_and_rows(self):
        """严格按用户要求提取字段：
        行容器: .recent-games .game-item.ng-star-inserted（兼容 .recent-games .game-item）
        - 日期: .meta-info .match-date
        - 玩家人数: .meta-info .player-count
        - 存活回合: .meta-info .rounds
        - 玩家角色: .player-details .role-name
        - 胜负: .win-status （仅中文“获胜/失败”）
        返回: (headers: List[str], rows: List[List[str]])
        """
        headers = ['玩家角色', '日期', '玩家人数', '存活回合', '胜负']
        rows = []

        try:
            game_items = self.driver.find_elements(
                By.CSS_SELECTOR,
                '.recent-games .game-item.ng-star-inserted, .recent-games .game-item'
            )

            for item in game_items:
                # 日期
                try:
                    date_text = item.find_element(By.CSS_SELECTOR, '.meta-info .match-date').text.strip()
                except NoSuchElementException:
                    date_text = ''

                # 玩家人数
                try:
                    player_count = item.find_element(By.CSS_SELECTOR, '.meta-info .player-count').text.strip()
                except NoSuchElementException:
                    player_count = ''

                # 存活回合
                try:
                    rounds = item.find_element(By.CSS_SELECTOR, '.meta-info .rounds').text.strip()
                except NoSuchElementException:
                    rounds = ''

                # 玩家角色
                try:
                    role_name = item.find_element(By.CSS_SELECTOR, '.player-details .role-name').text.strip()
                except NoSuchElementException:
                    role_name = ''

                # 胜负（中文）
                try:
                    win_status = item.find_element(By.CSS_SELECTOR, '.win-status').text.strip()
                except NoSuchElementException:
                    win_status = ''

                rows.append([role_name, date_text, player_count, rounds, win_status])

        except Exception as e:
            print(f'提取表头或记录时出错: {e}')

        return headers, rows

    def generate_html(self, filename=None):
        """生成HTML报告 - 使用动态表头与行数据"""
        if not filename:
            filename = f'game_records_{datetime.now().strftime("%Y%m%d_%H%M%S")}.html'

        # 统计胜负（仅中文“获胜/失败”）：在每行任意单元格文本中搜索
        wins = 0
        losses = 0
        for row in self.game_records:
            status = str(row[4]) if len(row) > 4 else ' '.join([str(c) for c in row])
            if ('胜利' in status) or ('获胜' in status) or ('勝' in status):
                wins += 1
            elif ('失败' in status) or ('敗' in status):
                losses += 1

        total = len(self.game_records)
        win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0

        # 生成表头 HTML（动态）
        headers_html = ''.join([f'<th>{self._escape(h)}</th>' for h in self.table_headers])

        # 生成表格行 HTML（动态列）
        table_rows = ''
        for i, row in enumerate(self.game_records, 1):
            cells_html = ''
            for cell in row:
                ctext = str(cell)
                if ('胜利' in ctext) or ('获胜' in ctext) or ('勝' in ctext):
                    cells_html += '<td><span class="win-tag">胜利</span></td>'
                elif '失败' in ctext or '敗' in ctext:
                    cells_html += '<td><span class="loss-tag">失败</span></td>'
                else:
                    cells_html += f'<td>{self._escape(ctext)}</td>'

            table_rows += f'''
                <tr>
                    <td>{i}</td>
                    {cells_html}
                </tr>'''

        # 填充模板
        template = Template(get_html_template())
        html = template.substitute(
            generation_time=datetime.now().strftime('%Y-%m-%d %H:%M:%S'),
            total_records=total,
            wins=wins,
            losses=losses,
            win_rate=win_rate,
            table_headers=headers_html,
            table_rows=table_rows
        )

        with open(filename, 'w', encoding='utf-8') as f:
            f.write(html)

        print(f"HTML已生成: {filename}")
        return filename

    def _escape(self, text):
        """转义HTML特殊字符"""
        return str(text).replace('<', '&lt;').replace('>', '&gt;').replace('&', '&amp;')

    def close(self):
        if self.driver:
            self.driver.quit()


def main():
    print("=" * 50)
    print("🦆 GooseGooseDuck 游戏记录查询")
    print("=" * 50)

    email = "631625980@qq.com"
    password = "chx2000227"

    if not email or not password:
        print("邮箱和密码不能为空！")
        return

    scraper = GaggleFunScraper(headless=False)

    try:
        if not scraper.login(email, password):
            print("登录失败")
            return

        records = scraper.fetch_game_records()

        if records:
            # 打印记录预览（动态表头与前10条）
            print("\n游戏记录预览:")
            print("-" * 75)
            header_line = '# | ' + ' | '.join(scraper.table_headers)
            print(header_line)
            print("-" * 75)
            for i, row in enumerate(records[:10], 1):
                cells = [str(c)[:20] for c in row]
                print(f"{i} | " + ' | '.join(cells))
            if len(records) > 10:
                print(f"... 共 {len(records)} 条记录")
            print("-" * 75)

            # 生成HTML
            # html_file = scraper.generate_html()

            # 保存JSON
            # json_file = html_file.replace('.html', '.json')
            # with open(json_file, 'w', encoding='utf-8') as f:
                # json.dump({'headers': scraper.table_headers, 'rows': records}, f, ensure_ascii=False, indent=2)
            # print(f"JSON已保存: {json_file}")

            # 打开HTML
            # try:
            #     os.startfile(html_file)
            # except:
            #     pass

        print("\n按 Enter 关闭浏览器...")
        input()

    except Exception as e:
        print(f"错误: {e}")
    finally:
        scraper.close()


if __name__ == "__main__":
    main()

