"""
基于 Selenium 的爬虫，按 login.py 的最新 DOM 规则提取字段：
- 容器: .recent-games .game-item.ng-star-inserted（兼容 .recent-games .game-item）
- 字段: 玩家角色(.player-details .role-name) | 日期(.meta-info .match-date) | 玩家人数(.meta-info .player-count) | 存活回合(.meta-info .rounds) | 胜负(.win-status)
返回 (headers, rows)
"""
import time
from typing import List, Tuple
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.chrome.options import Options
from selenium.common.exceptions import TimeoutException, NoSuchElementException


class GaggleScraper:
    LOGIN_URL = "https://gaggle.fun/auth/login"
    GAME_STATS_URL = "https://gaggle.fun/dashboard/game-stats"

    def __init__(self, headless: bool = True):
        options = Options()
        if headless:
            options.add_argument("--headless")
        options.add_argument("--disable-gpu")
        options.add_argument("--no-sandbox")
        options.add_argument("--window-size=1920,1080")
        options.add_argument("--disable-dev-shm-usage")
        options.page_load_strategy = "eager"
        options.add_argument("--blink-settings=imagesEnabled=false")
        options.add_experimental_option("prefs", {"profile.managed_default_content_settings.images": 2})
        options.add_argument("--disable-extensions")
        self.driver = webdriver.Chrome(options=options)
        self.wait = WebDriverWait(self.driver, 15)

    def preload_login_page(self) -> None:
        """预先打开登录页，等待输入框出现。"""
        self.driver.get(self.LOGIN_URL)
        # 等待邮箱输入框出现
        self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="email"]')))

    def login(self, email: str, password: str) -> bool:
        self.driver.get(self.LOGIN_URL)
        try:
            email_input = self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, 'input[type="email"]')))
            email_input.send_keys(email)
            pwd_input = self.driver.find_element(By.CSS_SELECTOR, 'input[type="password"]')
            pwd_input.send_keys(password)
            btn = self.driver.find_element(By.CSS_SELECTOR, 'button[type="submit"]')
            btn.click()
            self.wait.until(lambda d: "login" not in d.current_url.lower())
            # 登录后直接进入统计页，避免之后重复加载
            self.driver.get(self.GAME_STATS_URL)
            try:
                self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.match-list-container, .recent-games')))
            except TimeoutException:
                pass
            return True
        except Exception:
            return False

    def fetch(self) -> Tuple[List[str], List[List[str]]]:
        # 若已在统计页则不再重复加载
        if "game-stats" not in self.driver.current_url:
            self.driver.get(self.GAME_STATS_URL)
        try:
            self.wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, '.match-list-container, .recent-games')))
        except TimeoutException:
            pass
        last_count = -1
        stable_rounds = 0
        start_ts = time.time()
        max_secs = 5
        while time.time() - start_ts < max_secs and stable_rounds < 2:
            items = self.driver.find_elements(By.CSS_SELECTOR, '.recent-games .game-item.ng-star-inserted, .recent-games .game-item')
            count = len(items)
            self.driver.execute_script("window.scrollTo(0, document.body.scrollHeight);")
            time.sleep(0.3)
            items2 = self.driver.find_elements(By.CSS_SELECTOR, '.recent-games .game-item.ng-star-inserted, .recent-games .game-item')
            count2 = len(items2)
            if count2 == count == last_count:
                stable_rounds += 1
            else:
                stable_rounds = 0
            last_count = count2
        self.driver.execute_script("window.scrollTo(0, 0);")

        headers, rows = self._extract_headers_and_rows()
        return headers, rows

    def _extract_headers_and_rows(self) -> Tuple[List[str], List[List[str]]]:
        headers = ['玩家角色', '日期', '玩家人数', '存活回合', '胜负']
        rows: List[List[str]] = []
        try:
            game_items = self.driver.find_elements(By.CSS_SELECTOR, '.recent-games .game-item.ng-star-inserted, .recent-games .game-item')
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
                # 胜负
                try:
                    win_status = item.find_element(By.CSS_SELECTOR, '.win-status').text.strip()
                except NoSuchElementException:
                    win_status = ''
                rows.append([role_name, date_text, player_count, rounds, win_status])
        except Exception as e:
            print(f"提取表头或记录时出错: {e}")
        return headers, rows

    def close(self):
        try:
            if self.driver:
                self.driver.quit()
        except Exception:
            pass
