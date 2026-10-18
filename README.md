泗鹅鸭杀查询器（GooseGooseDuck 游戏记录查询）
一个针对 gaggle.fun（鹅鸭杀 Goose Goose Duck 社交平台）的游戏记录查询工具。用户在本地网页中输入自己的 gaggle.fun 账号密码，后端通过 Selenium 无头浏览器模拟登录，拦截站点的数据接口响应，抓取对局列表与对局详情（角色、胜负、存活回合、地图、模式等），并以美观的中文界面呈现，支持胜利/失败统计与胜率计算。

项目仅供个人学习与查询自己的游戏数据使用，请勿用于任何违反 gaggle.fun 服务条款的用途。

目录
功能特性
技术架构
项目结构
核心工作原理
API 接口一览
会话与资源管理机制
快速开始（本地运行）
Docker 部署
服务器部署（systemd + Nginx）
配置项（环境变量）
数据目录说明
角色映射工具脚本
常见问题排查
功能特性
免安装网页界面：登录页（带角色 Logo 动画与背景音乐）→ 对局记录列表 → 对局详情，全中文展示
对局列表：玩家角色（含角色头像）、日期、玩家人数、存活回合、胜负，以及总场次 / 胜 / 负 / 胜率 汇总
对局详情：点进任意一局查看该局所有玩家的数据（玩家名、角色、结果标签等）
实时更新：SSE（Server-Sent Events）推送，后台周期性刷新最新对局，页面无需手动刷新
按需抓取：详情数据未缓存时自动用会话凭据重建浏览器现场抓取
多会话并发控制：信号量限制同时运行的浏览器数量，防止资源耗尽
自动清理：后台 janitor 线程按 TTL 清理过期会话目录与归档文件，强制回收僵尸浏览器进程
角色资源本地化：73 个角色头像与中英文名映射全部内置，离线可用
技术架构

text
┌───────────────────────────── 浏览器（用户） ─────────────────────────────┐
│  login.html（登录）  →  records.html（对局列表）  →  detail.html（详情） │
│        │ POST /api/login      │ 轮询 /api/records        │ /api/record_detail
│        │                      └──────── SSE /api/sse（实时推送）────────┘
└────────┼──────────────────────────────┬───────────────────────────────────┘
         ▼                              ▼
┌───────────────────────  FastAPI (web/app.py) ─────────────────────────────┐
│  会话管理  并发信号量  SSE 广播  后台抓取线程  周期刷新线程  janitor 清理   │
└──────────────────────────────┬────────────────────────────────────────────┘
                               ▼
┌────────────────  Selenium 无头 Chrome (login.py) ─────────────────────────┐
│  1. 打开 gaggle.fun/auth/login，填入账号密码登录                           │
│  2. 打开 dashboard/game-stats，多策略定位"游戏模式"下拉框并切到轮抽         │
│  3. 通过 Chrome Performance Log 拦截 XHR 响应体：                         │
│     · SearchMatches  → 对局列表 JSON（保存为会话内 SearchMatches.json）    │
│     · match/<id>     → 对局详情 JSON（保存为 details/<matchId>.json）      │
└────────────────────────────────────────────────────────────────────────────┘
关键设计：不解析页面 DOM，只拦截网络响应。 网站是 Angular SPA 且有 Cloudflare 防护，DOM 结构多变；而数据接口（ggdPlayerMatch Cloud Functions）返回的 JSON 稳定可靠，因此爬虫用 CDP 性能日志拿到 requestId 后通过 Network.getResponseBody 直接读取接口原始数据。

项目结构

text
GooseGooseDuck游戏记录查询/
├── web/                        # Web 应用（前后端分离）
│   ├── app.py                  # FastAPI 后端：会话、API、后台线程、清理逻辑（~1300 行）
│   ├── scraper.py              # 【已停用】旧的 DOM 解析版爬虫，保留备查
│   ├── requirements.txt        # Python 依赖（fastapi / uvicorn / selenium 等）
│   └── static/                 # 前端静态页
│       ├── index.html          # 入口跳转页
│       ├── login.html          # 登录页（动画、BGM、角色 Logo 轮换）
│       ├── login_animated.html # 登录页的另一版式（未挂载路由）
│       ├── records.html        # 对局记录列表页（轮询 + SSE）
│       └── detail.html         # 对局详情页
├── login.py                    # Selenium 爬虫核心：登录 / 抓列表 / 抓详情 / 生成 HTML
├── web/app.py 引用的工具脚本（角色映射研究用，运行时不需要）:
│   ├── extract_roles.py        # 登录后批量提取角色与 matchId
│   ├── capture_role_mapping.py # 拦截详情页 API 建立角色映射
│   ├── get_game_role_mapping.py# 用 nickname↔player-name 对齐建立映射
│   ├── build_role_mapping.py / analyze_role_mapping.py / find_role_mapping.py
│   ├── batch_get_role_mapping.py / extract_role_id.py / parse_html_roles.py
│   └── debug_stats.py          # 临时诊断脚本（cookie 复现 game-stats 页面）
├── data/                       # 运行时数据（角色资源 + 会话数据 + 归档）
│   ├── role_logos/             # 73 个角色头像 PNG
│   ├── game_role_id_mapping.json  # 角色 ID → 英文名 映射
│   ├── role_en_ch_maping.json / en_cn_mapping.json  # 英文 → 中文名映射
│   ├── sessions/<session_id>/  # 每个会话：cookies.json / SearchMatches.json / details/
│   ├── 对局记录文件夹/          # 手动运行 login.py 时的输出目录
│   ├── debug/                  # 爬虫调试转储（页面源码 / 截图）
│   └── gaggle-logo.png、audio/ # 站点图标与 BGM
├── deploy/                     # 服务器部署样例
│   ├── ggd.service             # systemd 单元文件
│   ├── ggd.env.example         # 环境变量样例
│   └── nginx-site.example      # Nginx 站点配置样例
├── scripts/deploy.sh           # 服务器一键更新脚本（git pull + pip + 重启服务）
├── Dockerfile                  # python:3.11-slim + chromium + 中文字体
├── docker-compose.yml          # 容器编排（挂载代码与 data，shm 1g）
├── 1键关闭.txt                 # Windows 一键停止 8000 端口服务的 PowerShell 命令
└── debug_network_*.jsonl       # 历史网络调试记录
核心工作原理
1. 登录（login.py → GaggleFunScraper.login）
打开 https://gaggle.fun/auth/login，等待邮箱/密码输入框出现后填入并提交
轮询 URL：一旦跳离登录页即视为成功
同时监听 PrimeNG toast：出现 "password is incorrect" 则返回 invalid_credentials 错误码，前端显示"用户名或密码错误"
支持.cookies 免登录（try_cookie_login）：注入已保存 Cookie 后访问统计页验证
2. 抓取对局列表（fetch_game_records）
打开 dashboard/game-stats，用五种选择器策略（ID / CSS / XPath / iframe 内查找 / JS 全量扫描）定位"游戏模式"下拉框并切换到轮抽（Draft）模式以触发查询
切换动作做了拟人化处理（鼠标移动、随机停顿），并带 JS 派发 input/change 事件的兜底
通过 Chrome Performance Log 监听 Network.responseReceived，匹配到 https://us-central1-gaggle-staging.cloudfunctions.net/ggdPlayerMatch?action=SearchMatches 后用 CDP Network.getResponseBody 取出 JSON（自动处理 base64 编码与 BOM）
结果原子化写入 data/sessions/<id>/SearchMatches.json（先写 .tmp 再 os.replace）
3. 抓取对局详情（fetch_match_detail）
访问 dashboard/game-stats/match/<matchId>
同样通过性能日志拦截 URL 中包含该 matchId 的响应体
保存为 data/sessions/<id>/details/<matchId>.json
4. 数据加工（web/app.py → /api/records）
解析 latestMatches 数组，结合 game_role_id_mapping.json（角色 ID → 英文名）与中文映射表生成表格行
从详情 JSON 提取角色头像路径、游戏模式、地图名（模式索引 -2 偏移查表）
胜负判定：对文本包含"胜利/获胜/勝"或"失败/敗"分别计数，计算总胜率
API 接口一览
方法	路径	说明
GET	/	重定向到静态登录页
POST	/api/preload	创建会话并预打开登录页（前端进入登录页时即调用，缩短后续登录耗时）
POST	/api/login	参数 email/password（可带 session_id 复用预加载的浏览器）。登录成功后异步启动抓取，立即返回
GET	/api/records?session_id=	对局列表 + 汇总（total/wins/losses/win_rate）。状态未完成时返回 {"status": "processing"} 供前端轮询
GET	/api/record_detail?session_id=&index=	单局详情；本地缓存优先，未缓存则现场抓取（必要时重建浏览器）
GET	/api/sse?session_id=	SSE 事件流：records（列表更新）、detail（新详情）事件 + 15s keep-alive
POST	/api/fetch	一把梭接口：登录 + 抓取（独立于会话体系，兼容旧调用）
POST	/api/refresh_now?session_id=	立即触发一次刷新
POST	/api/refresh_stop?session_id=	停止后台周期刷新
POST	/api/session/close?session_id=	请求关闭会话（详见下方"延迟销毁"机制）
会话与资源管理机制
每个登录会话在内存中对应一条记录（scraper / status / lock / sse_queues / refresh_thread…），数据落盘在 data/sessions/<session_id>/。管理策略：

异步抓取：/api/login 立刻返回，抓取在后台线程进行，前端轮询 + SSE 获取进度
延迟销毁（重要）：前端页面跳转（记录页→详情页）也会触发 pagehide 发出 close 请求，若立即销毁会杀掉正在使用的会话。因此 close 只做时间标记，30 秒宽限期后确认无活动才释放浏览器；宽限期内任何 API 访问（打开详情页、SSE 重连）都会自动取消销毁
抓取保护：状态为 processing 时的 close 请求只标记 close_requested，等抓取线程完成存盘后再释放资源，数据不丢
周期刷新：抓取完成后启动 _refresh_loop（默认 600s 一次），增量抓取新对局并通过 SSE 推送
多重超时回收：
会话最大生存 SESSION_MAX_AGE_HOURS（默认 2 小时）
空闲超时 SESSION_IDLE_TIMEOUT_MINUTES（默认 30 分钟）
SSE 全部断开 5 分钟后自动退出刷新
janitor 巡检（每 5 分钟）：删除超过 DATA_TTL_HOURS 的会话目录、按 ARCHIVE_KEEP_N/ARCHIVE_TTL_DAYS 清理归档、强制回收浏览器僵尸进程（Windows 用 taskkill，类 Unix 用 pkill）
并发控制：SCRAPER_CONCURRENCY（信号量）限制同时存活的浏览器数量，超限返回 429
快速开始（本地运行）
前置要求
Python 3.10+
Google Chrome（本机安装版即可，Selenium Manager 会自动匹配 chromedriver）
Windows / macOS / Linux 均可
步骤

bash
# 1. 安装依赖
pip install -r web/requirements.txt

# 2. 启动服务（在项目根目录执行）
python -m web.app
# 或：uvicorn web.app:app --host 127.0.0.1 --port 8000

# 3. 浏览器打开
# http://127.0.0.1:8000
输入 gaggle.fun 的账号密码 → 等待 1~2 分钟（后端模拟登录 + 抓取）→ 查看对局记录。

停止服务：Windows 可直接执行 1键关闭.txt 中的 PowerShell 命令（杀掉占用 8000 端口的进程）。

注意：调试期间若修改 login.py，python -m web.app 的 --reload 在 Windows 上可能重载不彻底（旧进程占端口、跑旧代码），建议改完代码后完整重启服务。

Docker 部署

bash
docker compose up -d --build
镜像基于 python:3.11-slim，内置 Chromium + chromedriver + 中文字体（文泉驿/Noto CJK），shm_size: 1g 保证 Chrome 不因共享内存不足崩溃。代码与 data/ 以卷挂载，更新代码后重启容器即可。

服务器部署（systemd + Nginx）

bash
# 1. 克隆到 /opt/GooseGooseDuck，创建 venv 并安装依赖
# 2. 复制 deploy/ggd.env.example → /etc/ggd.env（按需修改）
# 3. 复制 deploy/ggd.service → /etc/systemd/system/ggd.service
sudo systemctl enable --now ggd
# 4.（可选）配置 deploy/nginx-site.example 到 Nginx 做反向代理
# 日常更新：bash scripts/deploy.sh
配置项（环境变量）
变量	默认值	说明
DATA_TTL_HOURS	24	会话数据目录保留时长（小时）
SESSION_MAX_AGE_HOURS	2	单会话最大生存时间
SESSION_IDLE_TIMEOUT_MINUTES	30	会话空闲超时
REFRESH_INTERVAL_SECONDS	600	后台自动刷新间隔（秒）
SCRAPER_CONCURRENCY	0（不限）	最大并发浏览器数，超限返回 429
SCRAPER_RETRY_AFTER	5	429 时建议的重试秒数
ARCHIVE_SEARCHMATCHES	false	是否把 SearchMatches 归档到"对局记录文件夹"
ARCHIVE_TTL_DAYS	7	归档保留天数
ARCHIVE_KEEP_N	100	归档最多保留份数
CHROME_BIN	自动	指定 Chrome/Chromium 可执行文件路径（Docker 内为 /usr/bin/chromium）
数据目录说明

text
data/
├── sessions/<session_id>/          # 每次登录一个目录
│   ├── cookies.json                # 登录 Cookie（供免登录复用）
│   ├── SearchMatches.json          # 对局列表接口原始 JSON
│   └── details/<matchId>.json      # 各对局详情原始 JSON
├── 对局记录文件夹/                  # 手动运行 python login.py 的输出 / 归档
├── debug/                          # game_stats_*.html / *.png 抓取失败诊断转储
├── role_logos/                     # 73 个角色头像
└── *.json                          # 角色 ID/中英文映射表
角色映射工具脚本
这些脚本是研究期的一次性工具，用于逆向"角色 ID → 英文名 → 中文名"映射关系，产出 data/game_role_id_mapping.json 等映射表。Web 服务运行时不依赖它们：

脚本	用途
extract_roles.py	登录后批量提取所有对局中的角色与后端 matchId
capture_role_mapping.py	访问详情页拦截 API 响应，提取角色 ID↔名称
get_game_role_mapping.py	用后端 JSON 的 nickname 与前端 player-name 对齐建立映射
build_role_mapping.py / analyze_role_mapping.py	从既有 JSON/HTML 数据分析归纳映射
find_role_mapping.py / batch_get_role_mapping.py	查找/批量获取映射
extract_role_id.py / parse_html_roles.py	从保存的 HTML 提取角色信息
常见问题排查
Q：登录成功但没有记录？ 按顺序检查：

服务端控制台是否出现 SearchMatches 响应已保存——没有说明抓取失败
data/debug/game_stats_*.html 是否为 0 字节（浏览器提前被杀或页面未渲染）
是否过早关闭了记录页（抓取需 1~2 分钟；现已支持中途离开，数据会存盘）
gaggle.fun 是否改版（下拉框选择器失效时自动走 JS 全量扫描兜底）
Q：日志反复出现 未找到游戏模式选择下拉框（statsGameMode）？ 若随后仍捕获到 SearchMatches 则无碍（页面加载本身也会触发查询）；若两条报错（下拉框 + 未捕获响应）同时出现，多为网站改版或 Cloudflare 拦截，查看 data/debug/ 的页面转储与截图。

Q：详情页打不开 / 提示"浏览器未就绪"？ 会话浏览器已被回收时会自动用缓存凭据重建；若仍失败（如并发满 429、Cookie 失效且未存密码），重新登录即可。

Q：Windows 下改代码后行为没变？ --reload 在 Windows 上可能残留旧进程，彻底停掉（1键关闭.txt）再启动。

Q：Chrome 报共享内存不足（Docker 环境）？ 确认 docker-compose.yml 的 shm_size: "1g" 生效。
