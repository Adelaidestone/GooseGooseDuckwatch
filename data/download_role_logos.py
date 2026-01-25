import json
import os
import sys
import ssl
import http.cookiejar as cookiejar
import urllib.request
import urllib.parse
import urllib.error
import argparse
import time
import re
try:
    from selenium import webdriver
    from selenium.webdriver.chrome.options import Options as ChromeOptions
    from selenium.webdriver.edge.options import Options as EdgeOptions
    from selenium.webdriver.firefox.options import Options as FirefoxOptions
    from selenium.webdriver.chrome.service import Service as ChromeService
    from selenium.webdriver.edge.service import Service as EdgeService
    from selenium.webdriver.firefox.service import Service as FirefoxService
    from selenium.common.exceptions import TimeoutException, WebDriverException
    SELENIUM_AVAILABLE = True
except Exception:
    SELENIUM_AVAILABLE = False


def get_ext_from_content_type(content_type: str) -> str:
    mapping = {
        "image/png": ".png",
        "image/jpeg": ".jpg",
        "image/webp": ".webp",
        "image/gif": ".gif",
        "image/svg+xml": ".svg",
        "image/x-icon": ".ico",
        "image/vnd.microsoft.icon": ".ico",
    }
    if not content_type:
        return ""
    ct = content_type.split(";")[0].strip().lower()
    return mapping.get(ct, "")


def sanitize_filename(name: str) -> str:
    # Keep spaces, replace only invalid Windows filename characters
    invalid = '<>:"/\\|?*'
    sanitized = ''.join('_' if c in invalid else c for c in name)
    # Windows does not allow trailing dot or space
    return sanitized.rstrip(' .')


def main() -> None:
    parser = argparse.ArgumentParser(description='Download role icons, optionally showing a browser.')
    parser.add_argument('--show-browser', action='store_true')
    parser.add_argument('--delay', type=float, default=0.8)
    parser.add_argument('--browser', choices=['chrome', 'edge', 'firefox'], default='chrome')
    parser.add_argument('--driver-path', type=str, default='')
    parser.add_argument('--binary', type=str, default='')
    parser.add_argument('--page-timeout', type=float, default=15.0)
    args = parser.parse_args()
    base_dir = os.path.dirname(os.path.abspath(__file__))
    dd_path = os.path.join(base_dir, 'dd.json')
    out_dir = os.path.join(base_dir, 'role_logos')
    os.makedirs(out_dir, exist_ok=True)

    try:
        with open(dd_path, 'r', encoding='utf-8') as f:
            data = json.load(f)
    except FileNotFoundError:
        print(f'File not found: {dd_path}', file=sys.stderr)
        sys.exit(1)
    except json.JSONDecodeError as e:
        print(f'Invalid JSON in {dd_path}: {e}', file=sys.stderr)
        sys.exit(1)

    roles = data.get('ROLES', {})
    if not isinstance(roles, dict) or not roles:
        print('No ROLES found in dd.json', file=sys.stderr)
        sys.exit(1)

    base_url = 'https://gaggle.fun/assets/images/ggd/role-icons/{key}-64x64.png'

    # Browser-like headers to mimic real downloads
    headers = {
        'User-Agent': (
            'Mozilla/5.0 (Windows NT 10.0; Win64; x64) '
            'AppleWebKit/537.36 (KHTML, like Gecko) '
            'Chrome/121.0.0.0 Safari/537.36'
        ),
        'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
        'Accept-Language': 'zh-CN,zh;q=0.9,en;q=0.8',
        'Accept-Encoding': 'gzip, deflate, br',
        'Connection': 'keep-alive',
        'Referer': 'https://gaggle.fun/',
        'Origin': 'https://gaggle.fun',
        'Sec-Fetch-Dest': 'image',
        'Sec-Fetch-Mode': 'no-cors',
        'Sec-Fetch-Site': 'same-origin',
    }

    # SSL context and a cookie-enabled opener to persist session like a browser
    ctx = ssl.create_default_context()
    cj = cookiejar.CookieJar()
    opener = urllib.request.build_opener(
        urllib.request.HTTPCookieProcessor(cj),
        urllib.request.HTTPSHandler(context=ctx)
    )

    driver = None
    cookie_header = ''
    if args.show_browser:
        if not SELENIUM_AVAILABLE:
            print('Selenium is not available. Install it with: pip install -U selenium', file=sys.stderr)
            sys.exit(2)
        try:
            browser = args.browser
            if browser == 'chrome':
                options = ChromeOptions()
                try:
                    options.page_load_strategy = 'eager'
                except Exception:
                    pass
                if args.binary:
                    options.binary_location = args.binary
                options.add_argument('--lang=zh-CN')
                options.add_argument('--disable-gpu')
                if args.driver_path:
                    service = ChromeService(executable_path=args.driver_path)
                    driver = webdriver.Chrome(service=service, options=options)
                else:
                    driver = webdriver.Chrome(options=options)
            elif browser == 'edge':
                options = EdgeOptions()
                try:
                    options.page_load_strategy = 'eager'
                except Exception:
                    pass
                if args.binary:
                    options.binary_location = args.binary
                options.add_argument('--lang=zh-CN')
                options.add_argument('--disable-gpu')
                if args.driver_path:
                    service = EdgeService(executable_path=args.driver_path)
                    driver = webdriver.Edge(service=service, options=options)
                else:
                    driver = webdriver.Edge(options=options)
            else:
                options = FirefoxOptions()
                try:
                    options.page_load_strategy = 'eager'
                except Exception:
                    pass
                if args.binary:
                    options.binary_location = args.binary
                if args.driver_path:
                    service = FirefoxService(executable_path=args.driver_path)
                    driver = webdriver.Firefox(service=service, options=options)
                else:
                    driver = webdriver.Firefox(options=options)

            try:
                driver.set_page_load_timeout(args.page_timeout)
            except Exception:
                pass
            try:
                driver.get('https://gaggle.fun/')
                time.sleep(0.5)
            except Exception:
                pass
            try:
                ck = driver.get_cookies()
                if ck:
                    cookie_header = '; '.join(
                        f"{c['name']}={c['value']}" for c in ck if 'name' in c and 'value' in c
                    )
            except Exception:
                pass
        except Exception as e:
            print(f'Failed to start browser: {e}', file=sys.stderr)
            sys.exit(2)

    # Iterate deterministically
    try:
        for key in roles.keys():
            # Build candidate name variants to cope with server case-sensitivity
            def pascal_from(raw: str) -> str:
                parts = [p for p in re.split(r'[^A-Za-z0-9]+', raw) if p]
                return ''.join(w[:1].upper() + w[1:].lower() for w in parts) if parts else raw

            variants = []
            # 1) First letter upper, rest lower (user-observed requirement)
            variants.append(key[:1].upper() + key[1:].lower() if key else key)
            # 2) As-is (original, e.g., all-caps)
            variants.append(key)
            # 3) PascalCase from word splits
            variants.append(pascal_from(key))
            # 4) lower()
            variants.append(key.lower())

            success_url = None
            success_variant = None
            last_err = None

            for name_variant in variants:
                url_key = urllib.parse.quote(name_variant, safe='')
                url = base_url.format(key=url_key)
                req_headers = dict(headers)
                if cookie_header:
                    req_headers['Cookie'] = cookie_header
                req = urllib.request.Request(url, headers=req_headers)

                try:
                    with opener.open(req, timeout=20) as resp_try:
                        if resp_try.getcode() == 200:
                            # We have a good URL; reuse this response to save
                            info = resp_try.info()
                            content_type = ''
                            try:
                                if hasattr(info, 'get_content_type'):
                                    content_type = info.get_content_type()
                                else:
                                    content_type = info.get('Content-Type', '')
                            except Exception:
                                content_type = info.get('Content-Type', '')

                            ext = get_ext_from_content_type(content_type)
                            if not ext:
                                parsed = urllib.parse.urlparse(url)
                                _, ext = os.path.splitext(parsed.path)
                            if not ext:
                                ext = '.bin'

                            filename = sanitize_filename(key) + ext
                            out_path = os.path.join(out_dir, filename)
                            data_bytes = resp_try.read()
                            with open(out_path, 'wb') as out_f:
                                out_f.write(data_bytes)
                            print(f'Downloaded: {key} -> {filename} ({len(data_bytes)} bytes) [via {name_variant}]')
                            success_url = url
                            success_variant = name_variant
                            break
                except Exception as e:
                    last_err = e

            if success_url is None:
                # Log failure once with last error if any
                if last_err is not None:
                    print(f'[FAILED] {key}: {last_err}', file=sys.stderr)
                else:
                    print(f'[FAILED] {key}: no matching case variant found', file=sys.stderr)
                # Still attempt to show something in browser if requested
                if driver is not None:
                    try:
                        driver.get(base_url.format(key=urllib.parse.quote(variants[0], safe='')))
                        time.sleep(max(0.0, args.delay))
                    except Exception:
                        pass
                continue

            # Show in browser the successful URL variant
            if driver is not None:
                try:
                    driver.get(success_url)
                    time.sleep(max(0.0, args.delay))
                except TimeoutException:
                    pass
                except WebDriverException:
                    pass
                except Exception:
                    pass
    except KeyboardInterrupt:
        print('Aborted by user (Ctrl+C)', file=sys.stderr)
    finally:
        if driver is not None:
            try:
                driver.quit()
            except Exception:
                pass


if __name__ == '__main__':
    main()
