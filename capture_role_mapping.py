"""
捕获后端API响应，提取角色ID与名称的映射关系
通过访问match详情页，拦截Network请求获取JSON数据
"""

import time
import json
import re
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options


class RoleMappingExtractor:
    """角色ID映射提取器"""

    LOGIN_URL = "https://gaggle.fun/auth/login"
    GAME_STATS_URL = "https://gaggle.fun/dashboard/game-stats"

    def __init__(self):
        options = Options()
        options.add_argument('--disable-gpu')
        options.add_argument('--no-sandbox')
        options.add_argument('--window-size=1920,1080')

        # 启用性能日志以捕获网络请求
        options.set_capability('goog:loggingPrefs', {'performance': 'ALL'})

        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 20)
        self.role_mapping = {}
        self.captured_responses = []

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

    def get_network_logs(self):
        """获取网络日志"""
        logs = self.driver.get_log('performance')
        return logs

    def extract_response_body(self, request_id):
        """尝试获取响应体"""
        try:
            response = self.driver.execute_cdp_cmd('Network.getResponseBody', {'requestId': request_id})
            return response.get('body', '')
        except:
            return None

    def capture_match_api(self, match_id):
        """访问match页面并捕获API响应"""
        url = f"https://gaggle.fun/dashboard/game-stats/match/{match_id}"
        print(f"\n访问: {url}")

        # 清除之前的日志
        self.driver.get_log('performance')

        self.driver.get(url)
        time.sleep(3)

        # 获取网络日志
        logs = self.get_network_logs()

        api_data = None
        for log in logs:
            try:
                message = json.loads(log['message'])['message']

                # 查找响应接收事件
                if message['method'] == 'Network.responseReceived':
                    response = message['params']['response']
                    url = response.get('url', '')

                    # 查找match API请求
                    if match_id in url and ('json' in response.get('mimeType', '') or 'api' in url.lower()):
                        print(f"  找到API响应: {url}")
                        request_id = message['params']['requestId']

                        # 尝试获取响应体
                        body = self.extract_response_body(request_id)
                        if body:
                            try:
                                api_data = json.loads(body)
                                print(f"  成功获取JSON数据")
                            except:
                                pass

            except Exception as e:
                pass

        return api_data

    def get_match_ids(self):
        """获取所有match ID"""
        print("\n获取Match ID列表...")
        self.driver.get(self.GAME_STATS_URL)
        time.sleep(5)

        # 滚动加载
        for i in range(5):
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(1)

        self.driver.execute_script("window.scrollTo(0, 0);")
        time.sleep(1)

        # 提取match ID
        links = self.driver.find_elements(By.TAG_NAME, 'a')
        match_ids = []
        pattern = re.compile(r'/dashboard/game-stats/match/(V\d+)')

        for link in links:
            href = link.get_attribute('href') or ''
            match = pattern.search(href)
            if match:
                match_ids.append(match.group(1))

        match_ids = list(set(match_ids))
        print(f"找到 {len(match_ids)} 个Match ID")
        return match_ids

    def extract_role_mapping_from_page(self):
        """从页面内容提取角色映射"""
        # 获取页面所有脚本和内容
        scripts = self.driver.find_elements(By.TAG_NAME, 'script')

        for script in scripts:
            content = script.get_attribute('innerHTML') or ''
            if 'role' in content.lower():
                # 查找角色映射模式
                # 模式: {33: "Demolitionist"} 或 {"33": "Demolitionist"}
                patterns = [
                    r'(\d+)\s*:\s*["\']([A-Za-z\s]+)["\']',
                    r'["\'](\d+)["\']\s*:\s*["\']([A-Za-z\s]+)["\']',
                ]

                for pattern in patterns:
                    matches = re.findall(pattern, content)
                    for m in matches:
                        role_id, role_name = m
                        if role_name.strip() and len(role_name) < 30:
                            self.role_mapping[int(role_id)] = role_name.strip()

    def run(self, email, password, sample_count=5):
        """运行提取流程"""
        try:
            if not self.login(email, password):
                print("登录失败")
                return None

            # 先访问game-stats页面获取match ID
            match_ids = self.get_match_ids()

            if not match_ids:
                print("从链接未找到Match ID，尝试从页面文本提取...")
                # 备用方案：从页面文本提取
                body = self.driver.find_element(By.TAG_NAME, 'body')
                text = body.text
                # 查找V开头的ID模式
                pattern = re.compile(r'V\d{15,}')
                match_ids = list(set(pattern.findall(text)))
                print(f"从文本找到 {len(match_ids)} 个Match ID")

            if not match_ids:
                print("仍未找到Match ID，请手动输入一个:")
                manual_id = input("Match ID (如 V056281220251545921564): ").strip()
                if manual_id:
                    match_ids = [manual_id]

            if not match_ids:
                print("无法获取Match ID")
                return None

            # 访问match页面，捕获API响应
            print(f"\n===== 开始访问 {min(sample_count, len(match_ids))} 个Match页面 =====")
            all_data = []
            all_page_data = []

            for i, match_id in enumerate(match_ids[:sample_count], 1):
                print(f"\n[{i}/{min(sample_count, len(match_ids))}] 访问Match: {match_id}")

                # 捕获API响应
                api_data = self.capture_match_api(match_id)

                if api_data:
                    all_data.append({
                        'match_id': match_id,
                        'data': api_data
                    })
                    # 从API数据中提取角色信息
                    self.analyze_api_data(api_data)
                else:
                    # 如果无法捕获API，从页面提取数据
                    print("  未捕获到API响应，从页面提取...")
                    page_data = self.extract_page_data(match_id)
                    if page_data:
                        all_page_data.append(page_data)

                # 从页面脚本提取映射
                self.extract_role_mapping_from_page()

                time.sleep(1)

            return {
                'role_mapping': self.role_mapping,
                'captured_data': all_data,
                'page_data': all_page_data
            }

        finally:
            pass

    def extract_page_data(self, match_id):
        """从页面提取可见数据"""
        try:
            body = self.driver.find_element(By.TAG_NAME, 'body')
            text = body.text

            # 过滤无关内容
            lines = [l.strip() for l in text.split('\n') if l.strip()]
            skip_words = ['Dashboard', 'Log Out', 'Privacy', 'Cookie', 'Terms', '©',
                          'Home', 'Store', 'News', 'FAQ', 'Discord', 'Sign']

            data_lines = []
            for line in lines:
                if len(line) > 2 and not any(w.lower() in line.lower() for w in skip_words):
                    data_lines.append(line)

            return {
                'match_id': match_id,
                'url': self.driver.current_url,
                'content': data_lines[:50]  # 保存前50行
            }
        except Exception as e:
            print(f"  提取页面数据出错: {e}")
            return None

    def analyze_api_data(self, data, prefix=''):
        """递归分析API数据，查找role相关字段"""
        if isinstance(data, dict):
            for key, value in data.items():
                if 'role' in key.lower():
                    print(f"  {prefix}{key}: {value}")
                    if isinstance(value, int):
                        # 找到role ID，尝试找对应的name
                        for k, v in data.items():
                            if 'name' in k.lower() and isinstance(v, str):
                                self.role_mapping[value] = v
                                print(f"    -> 映射: {value} = {v}")
                self.analyze_api_data(value, prefix + '  ')
        elif isinstance(data, list):
            for item in data:
                self.analyze_api_data(item, prefix)

    def close(self):
        if self.driver:
            self.driver.quit()


def main():
    print("=" * 60)
    print("🦆 GooseGooseDuck 角色ID映射提取器")
    print("=" * 60)
    print("通过访问match详情页，捕获后端API响应")
    print("=" * 60)

    email = input("\n邮箱: ").strip()
    password = input("密码: ").strip()

    if not email or not password:
        print("邮箱和密码不能为空！")
        return

    sample = input("分析Match数量 (默认5): ").strip()
    sample_count = int(sample) if sample else 5

    extractor = RoleMappingExtractor()

    try:
        result = extractor.run(email, password, sample_count)

        if result:
            print("\n" + "=" * 60)
            print("提取结果:")
            print("=" * 60)

            if result['role_mapping']:
                print("\n✅ 角色ID映射表:")
                print("-" * 40)
                for role_id, role_name in sorted(result['role_mapping'].items()):
                    print(f"  {role_id}: {role_name}")

                # 保存映射表
                with open('role_id_mapping.json', 'w', encoding='utf-8') as f:
                    json.dump(result['role_mapping'], f, ensure_ascii=False, indent=2)
                print("\n映射表已保存到: role_id_mapping.json")
            else:
                print("\n⚠️ 未能自动提取角色映射")

            if result.get('captured_data'):
                print(f"\n✅ 捕获到 {len(result['captured_data'])} 个API响应")
                # 保存原始API数据供手动分析
                with open('captured_api_data.json', 'w', encoding='utf-8') as f:
                    json.dump(result['captured_data'], f, ensure_ascii=False, indent=2)
                print("API原始数据已保存到: captured_api_data.json")

            if result.get('page_data'):
                print(f"\n✅ 提取到 {len(result['page_data'])} 个页面数据")
                with open('page_data.json', 'w', encoding='utf-8') as f:
                    json.dump(result['page_data'], f, ensure_ascii=False, indent=2)
                print("页面数据已保存到: page_data.json")

                # 显示页面内容预览
                print("\n页面内容预览:")
                print("-" * 40)
                for pd in result['page_data'][:2]:
                    print(f"\nMatch: {pd['match_id']}")
                    for line in pd['content'][:10]:
                        print(f"  {line}")

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
