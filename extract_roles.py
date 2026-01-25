"""
GooseGooseDuck 角色与Match ID提取器
登录后提取所有游戏记录中的角色和对应的后端数据编号
"""

import time
import json
import os
import re
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.common.desired_capabilities import DesiredCapabilities


class RoleExtractor:
    """角色与Match ID提取器"""

    LOGIN_URL = "https://gaggle.fun/auth/login"
    GAME_STATS_URL = "https://gaggle.fun/dashboard/game-stats"
    MATCH_URL_PATTERN = re.compile(r'/dashboard/game-stats/match/(V\d+)')

    def __init__(self, headless=False):
        options = Options()
        if headless:
            options.add_argument('--headless')
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')

        # 启用网络日志捕获
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 20)
        self.role_match_data = []

    def login(self, email, password):
        """登录"""
        print("正在登录...")
        self.driver.get(self.LOGIN_URL)
        time.sleep(3)

        try:
            email_input = self.wait.until(
                EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="email"]'))
            )
            email_input.send_keys(email)
        except:
            return False

        try:
            pwd_input = self.driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
            pwd_input.send_keys(password)
        except:
            return False

        try:
            btn = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            btn.click()
        except:
            return False

        time.sleep(5)

        if "login" not in self.driver.current_url.lower():
            print("登录成功！")
            return True
        return False

    def extract_roles_and_matches(self):
        """提取所有角色和Match ID"""
        print("正在获取游戏记录...")
        self.driver.get(self.GAME_STATS_URL)
        time.sleep(5)

        # 滚动加载所有数据
        last_height = 0
        scroll_count = 0
        max_scrolls = 20  # 最多滚动20次

        print("滚动加载数据中...")
        while scroll_count < max_scrolls:
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1.5)
            new_height = self.driver.execute_script("return document.body.scrollHeight")
            if new_height == last_height:
                break
            last_height = new_height
            scroll_count += 1
            print(f"  滚动 {scroll_count} 次...")

        self.driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        # 方法1: 查找所有链接中的match ID
        print("\n提取Match链接...")
        links = self.driver.find_elements(By.TAG_NAME, 'a')
        match_ids = set()

        for link in links:
            href = link.get_attribute('href') or ''
            match = self.MATCH_URL_PATTERN.search(href)
            if match:
                match_ids.add(match.group(1))

        print(f"找到 {len(match_ids)} 个Match ID")

        # 方法2: 解析页面文本获取角色信息
        print("\n提取角色信息...")
        body = self.driver.find_element(By.TAG_NAME, 'body')
        page_text = body.text

        # 查找所有可能的角色名称（游戏中的角色）
        known_roles = [
            'Goose', 'Duck', 'Dodo', 'Pigeon', 'Vulture', 'Falcon', 'Morphling',
            'Silencer', 'Canadian Goose', 'Vigilante', 'Birdwatcher', 'Detective',
            'Sheriff', 'Gravy', 'Mechanic', 'Technician', 'Mimic', 'Professional',
            'Hitman', 'Assassin', 'Ninja', 'Spy', 'Cannibal', 'Lover', 'Duellist',
            'Medium', 'Adventurer', 'Celebrity', 'Undertaker', 'Esper', 'Bodyguard',
            'Political', 'Astral', 'Street Urchin', 'Avenger', 'Locksmith',
            'Bounty Hunter', 'Identity Thief', 'Pelican', 'Snitch', 'Warlock',
            'Necromancer', 'Invisibility', 'Serial Killer', 'Demolitionist',
            'Tracker', 'Medic', 'Engineer', 'Spy', 'Sheriff', 'Mayor', 'Lovers'
        ]

        # 从页面文本中提取记录
        lines = [l.strip() for l in page_text.split('\n') if l.strip()]

        # 过滤导航内容
        skip_words = ['Dashboard', 'Log Out', 'Download', 'Privacy', 'Cookie',
                      'Terms', '©', 'Home', 'Store', 'News', 'FAQ', 'Discord',
                      'Game Stats', 'Profile', 'Settings', 'Sign', 'Games']

        data_lines = []
        for line in lines:
            if len(line) > 2 and not any(w.lower() in line.lower() for w in skip_words):
                data_lines.append(line)

        # 收集所有出现的角色
        roles_found = {}
        for line in data_lines:
            for role in known_roles:
                if role.lower() in line.lower():
                    if role not in roles_found:
                        roles_found[role] = 0
                    roles_found[role] += 1

        print(f"找到 {len(roles_found)} 种角色")

        # 将match ID列表和角色统计保存
        self.role_match_data = {
            'match_ids': list(match_ids),
            'roles_count': roles_found,
            'total_matches': len(match_ids)
        }

        return self.role_match_data

    def fetch_match_details(self, match_id):
        """访问单个match页面获取详细信息"""
        url = f"https://gaggle.fun/dashboard/game-stats/match/{match_id}"
        self.driver.get(url)
        time.sleep(3)

        body = self.driver.find_element(By.TAG_NAME, 'body')
        page_text = body.text

        # 提取角色信息
        role_info = {
            'match_id': match_id,
            'url': url,
            'page_content': page_text[:2000]  # 保存前2000字符用于分析
        }

        return role_info

    def fetch_all_match_details(self, limit=None):
        """获取所有match的详细信息"""
        if not self.role_match_data or not self.role_match_data.get('match_ids'):
            print("请先运行 extract_roles_and_matches()")
            return []

        match_ids = self.role_match_data['match_ids']
        if limit:
            match_ids = match_ids[:limit]

        print(f"\n正在获取 {len(match_ids)} 个match的详细信息...")
        details = []

        for i, match_id in enumerate(match_ids, 1):
            print(f"  [{i}/{len(match_ids)}] 获取 {match_id}...")
            detail = self.fetch_match_details(match_id)
            details.append(detail)
            time.sleep(1)  # 避免请求过快

        return details

    def save_results(self, filename=None):
        """保存结果到文件"""
        if not filename:
            filename = f'role_match_data_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'

        with open(filename, 'w', encoding='utf-8') as f:
            json.dump(self.role_match_data, f, ensure_ascii=False, indent=2)

        print(f"\n数据已保存到: {filename}")
        return filename

    def close(self):
        if self.driver:
            self.driver.quit()


def main():
    print("=" * 60)
    print("🦆 GooseGooseDuck 角色与Match ID提取器")
    print("=" * 60)

    email = input("邮箱: ").strip()
    password = input("密码: ").strip()

    if not email or not password:
        print("邮箱和密码不能为空！")
        return

    extractor = RoleExtractor(headless=False)

    try:
        if not extractor.login(email, password):
            print("登录失败")
            return

        # 提取角色和Match ID
        data = extractor.extract_roles_and_matches()

        if data:
            print("\n" + "=" * 60)
            print("提取结果:")
            print("=" * 60)

            print(f"\n总Match数量: {data['total_matches']}")

            print(f"\n角色统计 (共 {len(data['roles_count'])} 种):")
            print("-" * 40)
            for role, count in sorted(data['roles_count'].items(), key=lambda x: -x[1]):
                print(f"  {role}: {count} 次")

            print(f"\nMatch ID列表 (前10个):")
            print("-" * 40)
            for i, match_id in enumerate(data['match_ids'][:10], 1):
                print(f"  {i}. {match_id}")
                print(f"     URL: https://gaggle.fun/dashboard/game-stats/match/{match_id}")

            if len(data['match_ids']) > 10:
                print(f"  ... 共 {len(data['match_ids'])} 个")

            # 保存结果
            extractor.save_results()

            # 询问是否获取详细信息
            print("\n" + "-" * 40)
            get_details = input("是否获取每个match的详细信息? (y/n): ").strip().lower()
            if get_details == 'y':
                limit_str = input(f"获取数量限制 (直接回车获取全部 {len(data['match_ids'])} 个): ").strip()
                limit = int(limit_str) if limit_str else None

                details = extractor.fetch_all_match_details(limit)

                # 保存详细信息
                detail_file = f'match_details_{datetime.now().strftime("%Y%m%d_%H%M%S")}.json'
                with open(detail_file, 'w', encoding='utf-8') as f:
                    json.dump(details, f, ensure_ascii=False, indent=2)
                print(f"\n详细信息已保存到: {detail_file}")

        print("\n按 Enter 关闭浏览器...")
        input()

    except Exception as e:
        print(f"错误: {e}")
        import traceback
        traceback.print_exc()
    finally:
        extractor.close()


if __name__ == "__main__":
    main()
