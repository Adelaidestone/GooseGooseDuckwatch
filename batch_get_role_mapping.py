"""
从1.txt中的URL批量获取游戏角色ID映射
"""

import time
import json
import re
import os
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


class BatchRoleMappingExtractor:
    MAPPING_FILE = "game_role_id_mapping.json"

    def __init__(self):
        options = Options()
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 15)
        self.role_mapping = {}  # {role_id: role_name}

        # 加载已有映射
        self._load_existing_mapping()

    def _load_existing_mapping(self):
        """加载已有的映射文件"""
        if os.path.exists(self.MAPPING_FILE):
            try:
                with open(self.MAPPING_FILE, 'r', encoding='utf-8') as f:
                    data = json.load(f)
                    for k, v in data.items():
                        role_id = int(k)
                        if isinstance(v, dict):
                            self.role_mapping[role_id] = v.get('cn', v.get('en', str(v)))
                        else:
                            self.role_mapping[role_id] = v
                    print(f"已加载 {len(self.role_mapping)} 个已有角色映射")
            except Exception as e:
                print(f"加载映射文件失败: {e}")

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

    def extract_players_from_json(self, json_data):
        """从JSON提取玩家数据: {nickname: role_id}"""
        players = {}

        def find_players(data):
            if isinstance(data, dict):
                if 'nickname' in data and 'role' in data:
                    nickname = data['nickname']
                    role_id = data['role']
                    if isinstance(role_id, int):
                        players[nickname] = role_id
                else:
                    for v in data.values():
                        find_players(v)
            elif isinstance(data, list):
                for item in data:
                    find_players(item)

        find_players(json_data)
        return players

    def extract_players_from_page(self):
        """从页面提取玩家数据: {player_name: role_name}"""
        players = {}

        # 查找所有table-row
        rows = self.driver.find_elements(By.CSS_SELECTOR, '.table-row')

        for row in rows:
            try:
                name_elem = row.find_element(By.CSS_SELECTOR, '.player-name')
                player_name = name_elem.text.strip()

                role_elem = row.find_element(By.CSS_SELECTOR, '.player-role')
                role_name = role_elem.text.strip()

                if player_name and role_name and role_name != '-':
                    players[player_name] = role_name
            except:
                pass

        return players

    def process_url(self, url):
        """处理单个URL"""
        # 提取match_id
        match = re.search(r'/(V\d+)', url)
        if not match:
            print(f"  ⚠️ 无法提取Match ID: {url}")
            return 0

        match_id = match.group(1)
        print(f"\n访问: {url}")

        # 清除日志
        self.driver.get_log('performance')

        self.driver.get(url)
        time.sleep(3)

        # 获取后端JSON
        json_data = self.capture_json_response(match_id)

        if not json_data:
            print("  ⚠️ 未捕获到JSON响应")
            return 0

        json_players = self.extract_players_from_json(json_data)
        print(f"  后端玩家数: {len(json_players)}")

        # 获取前端角色
        page_players = self.extract_players_from_page()
        print(f"  前端玩家数: {len(page_players)}")

        # 匹配建立映射，只添加新的
        new_count = 0
        for nickname, role_id in json_players.items():
            if nickname in page_players:
                role_name = page_players[nickname]
                if role_id not in self.role_mapping:
                    self.role_mapping[role_id] = role_name
                    print(f"  ✓ 新增: {role_id} -> {role_name}")
                    new_count += 1

        print(f"  本次新增 {new_count} 个")
        return new_count

    def run(self, url_file):
        """从文件读取URL并批量处理"""
        # 读取URL列表
        with open(url_file, 'r', encoding='utf-8') as f:
            urls = [line.strip() for line in f if line.strip()]

        # 去重
        urls = list(dict.fromkeys(urls))
        print(f"共 {len(urls)} 个不重复的URL")

        total_new = 0
        for i, url in enumerate(urls, 1):
            print(f"\n{'='*50}")
            print(f"[{i}/{len(urls)}] 当前已收集 {len(self.role_mapping)} 个角色映射")
            print('='*50)

            new_count = self.process_url(url)
            total_new += new_count

            time.sleep(1)

        print(f"\n本次运行共新增 {total_new} 个角色映射")
        return self.role_mapping

    def save(self):
        """保存映射"""
        with open(self.MAPPING_FILE, 'w', encoding='utf-8') as f:
            json.dump(self.role_mapping, f, ensure_ascii=False, indent=2)
        print(f"已保存到: {self.MAPPING_FILE}")

    def close(self):
        if self.driver:
            self.driver.quit()


def main():
    print("=" * 60)
    print("🦆 批量获取游戏角色ID映射")
    print("=" * 60)

    url_file = r'E:\Code-yssey\GooseGooseDuck游戏记录查询\1.txt'

    extractor = BatchRoleMappingExtractor()

    try:
        mapping = extractor.run(url_file)

        if mapping:
            print("\n" + "=" * 60)
            print("✅ 游戏角色ID映射表")
            print("=" * 60)

            for role_id, role_name in sorted(mapping.items()):
                print(f"  {role_id}: {role_name}")

            extractor.save()
            print(f"共 {len(mapping)} 个角色映射")
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
