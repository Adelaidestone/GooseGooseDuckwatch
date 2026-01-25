"""
提取游戏角色ID映射
通过匹配后端JSON的nickname与前端的player-name，建立role ID与角色名的对应关系
"""

import time
import json
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


class GameRoleMappingExtractor:
    LOGIN_URL = "https://gaggle.fun/auth/login"
    GAME_STATS_URL = "https://gaggle.fun/dashboard/game-stats"
    MAPPING_FILE = "data/event_id_mapping.json"

    def __init__(self):
        options = Options()
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 20)
        self.event_mapping = {}  # {event_type: event_label}

        # 加载已有的映射文件
        self._load_existing_mapping()

    def _load_existing_mapping(self):
        """加载已有的事件映射文件"""
        import os
        if os.path.exists(self.MAPPING_FILE):
            try:
                with open(self.MAPPING_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for k, v in data.items():
                        try:
                            etype = int(k)
                        except Exception:
                            continue
                        # 值通常为字符串；若为对象则取任意字符串字段
                        if isinstance(v, dict):
                            label = next((vv for vv in v.values() if isinstance(vv, str) and vv.strip()), None)
                            if label:
                                self.event_mapping[etype] = label
                        elif isinstance(v, str):
                            self.event_mapping[etype] = v
                    print(f"已加载 {len(self.event_mapping)} 个已有事件映射")
            except Exception as e:
                print(f"加载映射文件失败: {e}")
                self.event_mapping = {}

    def login(self, email, password):
        print("正在登录...")
        self.driver.get(self.LOGIN_URL)
        time.sleep(3)

        try:
            email_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="email"]'))
            )
            email_input.send_keys(email)

            pwd_input = self.driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
            pwd_input.send_keys(password)

            btn = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            btn.click()
            time.sleep(5)

            if "login" not in self.driver.current_url.lower():
                print("登录成功！")
                return True
        except Exception as e:
            print(f"登录出错: {e}")
        return False

    def get_match_ids(self):
        print("\n获取Match ID...")
        self.driver.get(self.GAME_STATS_URL)
        time.sleep(5)

        for _ in range(5):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

        links = self.driver.find_elements(By.TAG_NAME, 'a')
        match_ids = []
        pattern = re.compile(r'/match/(V\d+)')

        for link in links:
            href = link.get_attribute('href') or ''
            m = pattern.search(href)
            if m:
                match_ids.append(m.group(1))

        return list(set(match_ids))

    def capture_json_response(self, match_id):
        """从Network日志捕获JSON响应"""
        logs = self.driver.get_log('performance')

        for log in logs:
            try:
                message = json.loads(log['message'])['message']
                if message['method'] == 'Network.responseReceived':
                    response = message['params']['response']
                    resp_url = response.get('url', '')

                    if match_id in resp_url:
                        request_id = message['params']['requestId']
                        try:
                            body = self.driver.execute_cdp_cmd(
                                'Network.getResponseBody',
                                {'requestId': request_id}
                            )
                            if body.get('body'):
                                return json.loads(body['body'])
                        except:
                            pass
            except:
                pass
        return None

    def extract_events_from_json(self, json_data):
        """从后端JSON提取每回合事件类型序列: {round_index: [type, ...]}"""
        result = {}
        try:
            rounds = json_data.get('rounds', []) if isinstance(json_data, dict) else []
            for idx, rd in enumerate(rounds):
                timeline = rd.get('timeline') or []
                # 按时间排序，提取type
                types = []
                try:
                    timeline_sorted = sorted(timeline, key=lambda x: x.get('timestamp', 0))
                except Exception:
                    timeline_sorted = timeline
                for ev in timeline_sorted:
                    t = ev.get('type') if isinstance(ev, dict) else None
                    if isinstance(t, int):
                        types.append(t)
                result[idx] = types
        except Exception:
            pass
        return result

    def extract_events_from_page(self):
        """从页面提取每回合事件文本序列: {round_index: [label, ...]}"""
        round_labels = {}
        try:
            # 回合标题与容器列表（按DOM顺序对齐）
            titles = self.driver.find_elements(By.CSS_SELECTOR, '.match-title.round-title, [class*="match-title"][class*="round-title"]')
            containers = self.driver.find_elements(By.CSS_SELECTOR, '.round-events, [class*="round-events"]')

            count = min(len(titles), len(containers))
            for i in range(count):
                title = titles[i]
                container = containers[i]
                txt = (title.text or '').strip()
                m = re.search(r'轮次\s*(\d+)', txt)
                if not m:
                    # 兼容英文 Round n
                    m = re.search(r'Round\s*(\d+)', txt, re.IGNORECASE)
                if not m:
                    continue
                round_idx = int(m.group(1)) - 1

                labels = []
                rows = container.find_elements(By.CSS_SELECTOR, '.event-row, [class*="event-row"]')
                for r in rows:
                    label = ''
                    try:
                        et_elems = r.find_elements(By.CSS_SELECTOR, '.event-type, [class*="event-type"]')
                        if et_elems:
                            # 优先可见文本
                            txtv = (et_elems[0].text or '').strip()
                            if txtv:
                                label = txtv
                            else:
                                # 兜底：从类名中提取 style-*
                                cls = et_elems[0].get_attribute('class') or ''
                                m2 = re.search(r'style-([A-Za-z0-9_-]+)', cls)
                                if m2:
                                    label = m2.group(1)
                        if not label:
                            # 再兜底：整行文本
                            label = (r.text or '').strip()
                    except Exception:
                        pass
                    if label:
                        labels.append(label)

                if labels:
                    round_labels[round_idx] = labels
        except Exception:
            pass
        return round_labels

    def process_match(self, match_id):
        """处理单个match，提取事件映射（只添加新的event_type）"""
        url = f"https://gaggle.fun/dashboard/game-stats/match/{match_id}"
        print(f"\n访问: {url}")

        # 清除日志
        self.driver.get_log('performance')

        self.driver.get(url)
        time.sleep(4)

        # 1. 获取后端JSON数据
        print("  获取后端JSON...")
        json_data = self.capture_json_response(match_id)

        if not json_data:
            print("  ⚠️ 未捕获到JSON响应")
            return 0

        # 2. 提取后端每回合事件序列
        backend_round_events = self.extract_events_from_json(json_data)
        print(f"  后端回合数: {len(backend_round_events)}")

        # 3. 提取前端每回合事件序列
        print("  获取前端事件...")
        frontend_round_events = self.extract_events_from_page()
        print(f"  前端回合数: {len(frontend_round_events)}")

        # 4. 通过回合编号对齐（前端 '轮次n' 对应后端 rounds[n-1]），按顺序一一对应
        new_count = 0
        for r_idx, types in backend_round_events.items():
            labels = frontend_round_events.get(r_idx, [])
            pair_count = min(len(types), len(labels))
            for j in range(pair_count):
                t = types[j]
                lbl = labels[j]
                if t not in self.event_mapping and isinstance(t, int) and lbl:
                    self.event_mapping[t] = lbl
                    print(f"  ✓ 新增: {t} -> {lbl}")
                    new_count += 1

        print(f"  本次新增 {new_count} 个事件映射")
        return new_count

    def run(self, email, password, count=5):
        if not self.login(email, password):
            return None

        match_ids = self.get_match_ids()
        print(f"找到 {len(match_ids)} 个Match")

        if not match_ids:
            manual = input("未找到Match，请输入Match ID: ").strip()
            if manual:
                match_ids = [manual]

        total_new = 0
        for i, mid in enumerate(match_ids[:count], 1):
            print(f"\n{'='*50}")
            print(f"[{i}/{min(count, len(match_ids))}] Match: {mid}")
            print(f"当前已收集 {len(self.event_mapping)} 个事件映射")
            print('='*50)

            new_count = self.process_match(mid)
            total_new += new_count

            time.sleep(1)

        # 手动循环继续处理更多对局
        while True:
            manual = input("请输入Match ID：").strip()
            if not manual:
                break
            print(f"\n{'='*50}")
            print(f"[手动] Match: {manual}")
            print(f"当前已收集 {len(self.event_mapping)} 个事件映射")
            print('='*50)
            new_count = self.process_match(manual)
            total_new += new_count
            time.sleep(1)

        print(f"\n本次运行共新增 {total_new} 个事件映射")
        return self.event_mapping

    def close(self):
        if self.driver:
            self.driver.quit()


def main():
    print("=" * 60)
    print("🦆 GooseGooseDuck 事件ID映射提取器")
    print("=" * 60)
    print("通过对齐回合，将后端timeline的type与前端事件文本建立映射")
    print("=" * 60)

    email = input("\n邮箱: ").strip()
    password = input("密码: ").strip()

    if not email or not password:
        print("邮箱和密码不能为空！")
        return

    count = input("分析Match数量 (默认5): ").strip()
    count = int(count) if count else 5

    extractor = GameRoleMappingExtractor()

    try:
        mapping = extractor.run(email, password, count)

        if mapping:
            print("\n" + "=" * 60)
            print("✅ 事件ID映射表")
            print("=" * 60)

            for etype, label in sorted(mapping.items()):
                print(f"  {etype}: {label}")

            # 保存
            with open('data/event_id_mapping.json', 'w', encoding='utf-8') as f:
                json.dump(mapping, f, ensure_ascii=False, indent=2)
            print(f"\n已保存到: data/event_id_mapping.json")
            print(f"共 {len(mapping)} 个事件映射")
        else:
            print("\n未能提取映射")

        print("\n按Enter关闭浏览器...")
        input()

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        extractor.close()


if __name__ == "__main__":
    main()
