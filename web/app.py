"""
GooseGooseDuck 游戏记录查询 - Web 后端（前后端分离）
FastAPI 提供 /api/fetch 接口，前端在 static/index.html 中调用
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Body, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse, StreamingResponse
from pydantic import BaseModel
from typing import Optional
import os
import shutil
import time
import threading
import uvicorn
from queue import Queue, Empty

# from web.scraper import GaggleScraper  # 注释：停用基于前端 DOM 的抓取
from login import GaggleFunScraper
import uuid
import json
from datetime import datetime, timezone

BASE_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = BASE_DIR.parent.resolve()

# ---- 抓取并发闸配置 ----
# ---- 抓取并发闸配置 ----
SCRAPER_CONCURRENCY = int(os.getenv("SCRAPER_CONCURRENCY", "0"))
SCRAPER_RETRY_AFTER = int(os.getenv("SCRAPER_RETRY_AFTER", "10"))  # 秒
SCRAPER_SEM = threading.Semaphore(SCRAPER_CONCURRENCY if SCRAPER_CONCURRENCY > 0 else 1000000000)

app = FastAPI(title="GooseGooseDuck 游戏记录 - API", docs_url=None, redoc_url=None, openapi_url=None)
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/assets/role_logos", StaticFiles(directory=str(PROJECT_DIR / "data" / "role_logos")), name="role_logos")
app.mount("/data/role_logos", StaticFiles(directory=str(PROJECT_DIR / "data" / "role_logos")), name="role_logos_compat")
app.mount("/assets/audio", StaticFiles(directory=str(PROJECT_DIR / "data" / "audio")), name="audio")


@app.get("/favicon.png")
def serve_favicon():
    return FileResponse(str(PROJECT_DIR / "data" / "gaggle-logo.png"), media_type="image/png")


class FetchReq(BaseModel):
    email: str
    password: str

class LoginReq(BaseModel):
    session_id: Optional[str] = None
    email: str
    password: str

# 内存会话存储：{session_id: { 'scraper': GaggleScraper|None, 'status': str, 'data': dict|None }}
SESSIONS = {}

# 角色映射
def _load_role_map() -> dict:
    path = PROJECT_DIR / 'data' / 'game_role_id_mapping.json'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

ROLE_MAP = _load_role_map()

# 事件类型映射
def _load_event_map() -> dict:
    path = PROJECT_DIR / 'data' / 'event_id_mapping.json'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

EVENT_MAP = _load_event_map()

def _load_basic_role_cn_map() -> dict:
    path = PROJECT_DIR / 'data' / 'game_role_id.json'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

BASIC_ROLE_CN = _load_basic_role_cn_map()

# 角色中文->英文键映射（用于logo文件名）
def _load_cn_en_map() -> dict:
    path = PROJECT_DIR / 'data' / 'role_en_ch_maping.json'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            raw = json.load(f)
            inv = {}
            for en, cn in raw.items():
                if isinstance(cn, str) and cn:
                    inv.setdefault(cn, en)  # 简单反转，重复时保留首次
            return inv
    except Exception:
        return {}

CN2EN_ROLE = _load_cn_en_map()
ROLE_LOGO_DIR = PROJECT_DIR / 'data' / 'role_logos'

def _load_en_cn_mapping() -> dict:
    path = PROJECT_DIR / 'data' / 'en_cn_mapping.json'
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return json.load(f)
    except Exception:
        return {}

EN_CN_MAPPING = _load_en_cn_mapping()


# ---- 归档与清理策略（可选） ----
# 是否在每次保存会话 SearchMatches 后，同时归档一份到 data/对局记录文件夹/
ARCHIVE_SEARCHMATCHES = os.getenv("ARCHIVE_SEARCHMATCHES", "false").lower() in ("1", "true", "yes")
# 归档文件的 TTL（天）；超过则参与清理
ARCHIVE_TTL_DAYS = int(os.getenv("ARCHIVE_TTL_DAYS", "7"))
# 始终保留的最新归档文件数量上限（在 TTL 清理基础上再次裁剪）
ARCHIVE_KEEP_N = int(os.getenv("ARCHIVE_KEEP_N", "100"))

def _archive_dir() -> Path:
    return PROJECT_DIR / 'data' / '对局记录文件夹'

def _maybe_archive_searchmatches(src_path: Path):
    """按需将会话内的 SearchMatches.json 复制归档为带时间戳的文件。"""
    try:
        if not ARCHIVE_SEARCHMATCHES:
            return
        if not src_path or (not Path(src_path).exists()):
            return
        out_dir = _archive_dir()
        out_dir.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime('%Y%m%d_%H%M%S')
        dst = out_dir / f'SearchMatches_{ts}.json'
        try:
            shutil.copy2(src_path, dst)
        except Exception:
            # 忽略复制失败
            pass
    except Exception:
        pass

def _cleanup_archive():
    """清理归档目录中过期或过多的文件。"""
    try:
        out_dir = _archive_dir()
        if not out_dir.exists():
            return
        files = sorted(out_dir.glob('SearchMatches_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        if not files:
            return
        now = time.time()
        ttl_secs = max(0, ARCHIVE_TTL_DAYS) * 86400
        # 先清理超过 TTL 的
        for p in list(files):
            try:
                if ttl_secs > 0 and (now - p.stat().st_mtime) > ttl_secs:
                    p.unlink(missing_ok=True)
            except Exception:
                pass
        # 重新列一次，保证有序
        files = sorted(out_dir.glob('SearchMatches_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        # 保留最新 ARCHIVE_KEEP_N 个，其余删除
        if ARCHIVE_KEEP_N >= 0 and len(files) > ARCHIVE_KEEP_N:
            for p in files[ARCHIVE_KEEP_N:]:
                try:
                    p.unlink(missing_ok=True)
                except Exception:
                    pass
    except Exception:
        pass

def _latest_searchmatches_file():
 
    data_dir = PROJECT_DIR / 'data'
    records_dir = data_dir / '对局记录文件夹'
    try:
        files_records = []
        try:
            files_records = sorted(records_dir.glob('SearchMatches_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        except Exception:
            files_records = []
        if files_records:
            return files_records[0]
        return None
    except Exception:
        return None

# 会话数据根目录
SESS_ROOT = PROJECT_DIR / 'data' / 'sessions'

def _session_dir(session_id: str) -> Path:
    p = SESS_ROOT / session_id
    try:
        (p / 'details').mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    return p

def _session_searchmatches_path(session_id: str) -> Path:
    return _session_dir(session_id) / 'SearchMatches.json'

def _session_detail_path(session_id: str, match_id: str) -> Path:
    return _session_dir(session_id) / 'details' / f"{match_id}.json"

def _session_cookies_path(session_id: str) -> Path:
    return _session_dir(session_id) / 'cookies.json'

def _write_session_meta(session_id: str):
    meta_path = _session_dir(session_id) / '.meta.json'
    try:
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump({'created_at': datetime.now(timezone.utc).isoformat()}, f, ensure_ascii=False)
    except Exception:
        pass

def _mark_active(session_id: str):
    try:
        s = SESSIONS.get(session_id)
        if s is not None:
            s["last_active"] = time.time()
    except Exception:
        pass

def _save_match_detail_json(session_id: Optional[str], match_id: str, detail_data: dict) -> Path:
    """保存单个对局详情到会话目录；需要有效的 session_id。"""
    if not session_id:
        raise HTTPException(status_code=400, detail="需要 session_id")
    out_path = _session_detail_path(session_id, match_id)
    try:
        _session_dir(session_id)  # ensure
        with open(out_path, 'w', encoding='utf-8') as f:
            json.dump({'match_id': match_id, 'data': detail_data}, f, ensure_ascii=False, indent=2)
    except Exception:
        pass
    return out_path


@app.get("/")
def serve_login():
    # 将根路径重定向到 /static/login.html，便于前端页面相对路径以 /static/ 为基准
    return RedirectResponse(url="/static/login.html", status_code=307)


@app.post("/api/preload")
def api_preload():
    # 创建会话并预加载登录页
    session_id = uuid.uuid4().hex[:12]
    token_acquired = SCRAPER_SEM.acquire(blocking=False)
    if not token_acquired:
        raise HTTPException(status_code=429, detail="当前访问较多，请稍后重试", headers={"Retry-After": str(SCRAPER_RETRY_AFTER)})
    scraper = GaggleFunScraper(headless=True)
    try:
        # 停用：前端 DOM 预加载
        # scraper.preload_login_page()
        # 改为直接打开登录页，等待后续 /api/login 使用
        scraper.driver.get(scraper.LOGIN_URL)
        SESSIONS[session_id] = {
            "scraper": scraper,
            "status": "ready",
            "data": None,
            "lock": threading.Lock(),
            "sse_queues": [],
            "refresh_thread": None,
            "refresh_stop": None,
            "last_active": time.time(),
        }
        return {"session_id": session_id, "status": "ready"}
    except Exception as e:
        try:
            scraper.close()
        except Exception:
            pass
        try:
            SCRAPER_SEM.release()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"预加载失败: {e}")


@app.post("/api/login")
def api_login(req: LoginReq = Body(...)):
    # 允许无会话直接登录：若无 session_id 或会话不存在，则创建新会话与浏览器（占用并发令牌）
    session_id = req.session_id or uuid.uuid4().hex[:12]
    s = SESSIONS.get(session_id)
    created_new = False
    if not s:
        # 创建新浏览器需要占用一个并发令牌
        token_acquired = SCRAPER_SEM.acquire(blocking=False)
        if not token_acquired:
            raise HTTPException(status_code=429, detail="当前访问较多，请稍后重试", headers={"Retry-After": str(SCRAPER_RETRY_AFTER)})
        scraper = GaggleFunScraper(headless=True)
        s = {
            "scraper": scraper,
            "status": "ready",
            "data": None,
            "lock": threading.Lock(),
            "sse_queues": [],
            "refresh_thread": None,
            "refresh_stop": None,
            "last_active": time.time(),
        }
        SESSIONS[session_id] = s
        created_new = True
    elif not s.get("scraper"):
        token_acquired = SCRAPER_SEM.acquire(blocking=False)
        if not token_acquired:
            raise HTTPException(status_code=429, detail="当前访问较多，请稍后重试", headers={"Retry-After": str(SCRAPER_RETRY_AFTER)})
        s["scraper"] = GaggleFunScraper(headless=True)

    scraper: GaggleFunScraper = s["scraper"]
    cookies_path = _session_cookies_path(session_id)
    try:
        # 优先尝试 Cookie 免登录
        ok = False
        try:
            if cookies_path.exists():
                ok = scraper.try_cookie_login(str(cookies_path))
        except Exception:
            ok = False
        if not ok:
            ok = scraper.login(req.email, req.password)
            if not ok:
                s["status"] = "error"
                try:
                    err = getattr(scraper, 'last_error', None)
                except Exception:
                    err = None
                if err == 'invalid_credentials':
                    raise HTTPException(status_code=401, detail="用户名或密码错误")
                raise HTTPException(status_code=401, detail="登录失败")
            try:
                scraper.save_cookies(str(cookies_path))
            except Exception:
                pass

        # 缓存认证信息以便后续重建/重登
        s["auth"] = {"email": req.email, "password": req.password}
        _mark_active(session_id)

        # 非阻塞初始化：后台抓取并保存到会话文件，完成后设置状态并启动刷新线程
        s["status"] = "processing"
        def _post_login_init():
            try:
                sess_dir = _session_dir(session_id)
                _write_session_meta(session_id)
                search_path = _session_searchmatches_path(session_id)
                lock = s.get("lock")
                if lock:
                    with lock:
                        scraper.fetch_game_records(save_path=str(search_path))
                else:
                    scraper.fetch_game_records(save_path=str(search_path))
                # 缓存会话内文件路径
                s["data"] = {"searchMatchesFile": str(search_path)}
                # 可选：归档并清理
                _maybe_archive_searchmatches(search_path)
                _cleanup_archive()
                # 解析 matchIds 并降低首轮详情预取
                match_details = []
                try:
                    if search_path.exists():
                        with open(search_path, 'r', encoding='utf-8') as f:
                            payload = json.load(f)
                        latest_matches = (payload or {}).get('data', {}).get('body', {}).get('latestMatches', [])
                        match_ids = [m.get('matchId') for m in latest_matches if isinstance(m, dict) and m.get('matchId')]
                        s["match_ids"] = match_ids
                        # 首轮预取前2条详情
                        for mid in match_ids[:2]:
                            if lock:
                                with lock:
                                    detail = scraper.fetch_match_detail(mid)
                            else:
                                detail = scraper.fetch_match_detail(mid)
                            if detail is not None:
                                _save_match_detail_json(session_id, mid, detail)
                                match_details.append({"matchId": mid, "data": detail})
                except Exception:
                    pass
                if match_details:
                    s["match_details"] = match_details
                s["status"] = "done"
                # 启动后台刷新线程（若未启动）
                if not s.get("refresh_thread"):
                    stop_evt = threading.Event()
                    s["refresh_stop"] = stop_evt
                    t = threading.Thread(target=_refresh_loop, args=(session_id, stop_evt), daemon=True)
                    s["refresh_thread"] = t
                    t.start()
                # 通知前端
                _broadcast_sse(session_id, "records", {"version": int(time.time())})
                if match_details:
                    _broadcast_sse(session_id, "detail", {"type": "added"})
            except Exception:
                s["status"] = "error"

        threading.Thread(target=_post_login_init, daemon=True).start()
        return {"ok": True, "session_id": session_id, "status": s.get("status")}
    except Exception:
        # 出错时，如是新建会话则回收资源
        if created_new:
            try:
                scraper.close()
            except Exception:
                pass
            SESSIONS.pop(session_id, None)
            try:
                SCRAPER_SEM.release()
            except Exception:
                pass
        raise


@app.get("/api/records")
def api_records(session_id: str = Query(...)):
    s = SESSIONS.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    _mark_active(session_id)
    if s.get("status") != "done" or not s.get("data"):
        return {"status": s.get("status", "unknown")}
    data = s.get("data", {})
    # 优先使用会话目录中的 SearchMatches.json
    search_file = data.get("searchMatchesFile")
    if not search_file:
        path_in_session = _session_searchmatches_path(session_id)
        if path_in_session.exists():
            search_file = str(path_in_session)
        else:
            latest = _latest_searchmatches_file()
            search_file = str(latest) if latest else None
    if not search_file:
        return {"status": "no_searchmatches"}
    try:
        with open(search_file, 'r', encoding='utf-8') as f:
            payload = json.load(f)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"读取 SearchMatches 失败: {e}")

    latest_matches = (
        (payload or {}).get('data', {}).get('body', {}).get('latestMatches', [])
    )
    if not isinstance(latest_matches, list):
        raise HTTPException(status_code=500, detail="SearchMatches 结构不符合预期: latestMatches 非列表")

    # 缓存 matchIds
    try:
        s["match_ids"] = [m.get('matchId') for m in latest_matches if isinstance(m, dict) and m.get('matchId')]
    except Exception:
        pass

    headers = ['玩家角色', '日期', '玩家人数', '存活回合', '胜负']
    rows = []
    extras = []  # 与 rows 同索引：{roleLogo, mode, map}
    wins = 0
    losses = 0
    maps_conf = {}
    modes_values = []
    try:
        maps_conf = EN_CN_MAPPING.get('MAPS') or {}
    except Exception:
        maps_conf = {}
    try:
        modes_values = list((EN_CN_MAPPING.get('GAME_MODES') or {}).values())
    except Exception:
        modes_values = []
    for item in latest_matches:
        try:
            role_id = item.get('role')
            role_name = ROLE_MAP.get(str(role_id)) or BASIC_ROLE_CN.get(str(role_id)) or f"角色{role_id}"
            created_at = item.get('createdAt', '')
            date_str = created_at.split('T', 1)[0] if isinstance(created_at, str) else ''
            num_players = item.get('numOfPlayers', '')
            turns_survived = item.get('turnsSurvived', '')
            win_bool = bool(item.get('win', False))
            win_text = '胜利' if win_bool else '失败'
            if win_bool:
                wins += 1
            else:
                losses += 1
            rows.append([role_name, str(date_str), str(num_players), str(turns_survived), win_text])

            # 附加信息：角色Logo、模式、地图中文
            logo_url = None
            en_key = CN2EN_ROLE.get(role_name)
            if en_key:
                logo_path = ROLE_LOGO_DIR / f"{en_key}.png"
                if logo_path.exists():
                    logo_url = f"../assets/role_logos/{en_key}.png"
            mode_idx = item.get('mode')
            map_idx = item.get('map')
            map_cn = '-'
            try:
                maps_obj = maps_conf
                if isinstance(map_idx, int):
                    if isinstance(maps_obj, dict) and any(str(k).isdigit() for k in maps_obj.keys()):
                        inner = maps_obj.get(str(map_idx))
                        if isinstance(inner, dict) and inner:
                            map_cn = next(iter(inner.values()))
                    else:
                        vals = list((maps_obj or {}).values())
                        if map_idx >= 1 and map_idx <= len(vals):
                            map_cn = vals[map_idx - 1]
            except Exception:
                pass
            mode_cn = '-'
            try:
                if isinstance(mode_idx, int) and (mode_idx - 2) >= 0 and (mode_idx - 2) < len(modes_values):
                    mode_cn = modes_values[mode_idx - 2]
            except Exception:
                pass
            extras.append({"roleLogo": logo_url, "mode": mode_cn, "map": map_cn})
        except Exception:
            # 跳过异常项，继续
            try:
                extras.append({"roleLogo": None, "mode": None, "map": '-'})
            except Exception:
                pass
            continue

    total = len(rows)
    win_rate = round(wins / (wins + losses) * 100, 1) if (wins + losses) > 0 else 0
    result = {"headers": headers, "rows": rows, "summary": {"total": total, "wins": wins, "losses": losses, "win_rate": win_rate}, "extras": extras, "version": int(time.time())}
    # 缓存标准结果，便于后续重复请求
    s["data"] = result
    return result


@app.get("/api/record_detail")
def api_record_detail(session_id: str = Query(...), index: int = Query(0)):
    """返回对局详情（从会话中缓存的原始JSON转换为前端所需结构）。"""
    s = SESSIONS.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    _mark_active(session_id)
    details = s.get("match_details") or []
    if not isinstance(index, int) or index < 0:
        raise HTTPException(status_code=400, detail="index 越界")
    # 若该 index 尚无缓存，按需抓取
    need_fetch = index >= len(details) or not details[index]
    if need_fetch:
        match_ids = s.get("match_ids")
        # 如果会话中无 matchIds，尝试从最新 SearchMatches 恢复
        if not match_ids:
            latest = _latest_searchmatches_file()
            if latest and latest.exists():
                try:
                    with open(latest, 'r', encoding='utf-8') as f:
                        payload = json.load(f)
                    latest_matches = (payload or {}).get('data', {}).get('body', {}).get('latestMatches', [])
                    match_ids = [m.get('matchId') for m in latest_matches if isinstance(m, dict) and m.get('matchId')]
                    s["match_ids"] = match_ids
                except Exception:
                    match_ids = None
        if not match_ids or index >= len(match_ids):
            raise HTTPException(status_code=404, detail="未找到对应的 matchId")
        mid = match_ids[index]
        # 优先尝试本地缓存文件
        try:
            local_path = _session_detail_path(session_id, mid)
            if local_path.exists():
                with open(local_path, 'r', encoding='utf-8') as f:
                    jd = json.load(f)
                local_data = jd.get('data') if isinstance(jd, dict) else None
                if local_data is None and isinstance(jd, dict):
                    local_data = jd
                if local_data is not None:
                    if index >= len(details):
                        details.extend([None] * (index - len(details) + 1))
                    details[index] = {"matchId": mid, "data": local_data}
                    s["match_details"] = details
        except Exception:
            pass
        # 若仍无详情，则使用会话内持久化浏览器按需抓取
        if index >= len(details) or not details[index]:
            scraper = s.get("scraper")
            if not scraper:
                raise HTTPException(status_code=503, detail="浏览器未就绪，请稍后重试或重新登录")
            lock = s.get("lock")
            if lock:
                with lock:
                    detail = scraper.fetch_match_detail(mid)
            else:
                detail = scraper.fetch_match_detail(mid)
            if detail is None:
                raise HTTPException(status_code=500, detail="抓取对局详情失败")
            _save_match_detail_json(session_id, mid, detail)
            # 将结果放入会话缓存，保持索引对齐
            if index >= len(details):
                details.extend([None] * (index - len(details) + 1))
            details[index] = {"matchId": mid, "data": detail}
            s["match_details"] = details
    raw = details[index] or {}
    match = raw.get('data') or {}

    # 元信息
    mode_val = match.get('mode')
    map_val = match.get('map')
    start_at = match.get('startAt')
    end_at = match.get('endAt')

    # 玩家
    players_obj = match.get('playerData') or {}
    players = []
    by_uid = {}
    for p in players_obj.values():
        role_id = p.get('role')
        role_name = ROLE_MAP.get(str(role_id)) or BASIC_ROLE_CN.get(str(role_id), f"角色{role_id}")
        logo_url = None
        en_key = CN2EN_ROLE.get(role_name)
        if en_key:
            logo_path = ROLE_LOGO_DIR / f"{en_key}.png"
            if logo_path.exists():
                logo_url = f"../assets/role_logos/{en_key}.png"
        rec = {
            'userId': p.get('userId'),
            'nickname': p.get('nickname', ''),
            'roleId': role_id,
            'roleName': role_name,
            'roleLogo': logo_url,
            'win': bool(p.get('win', False)),
            'correctVotes': p.get('correctVotes', 0),
            'kills': p.get('kills', 0),
            'turnsSurvived': p.get('turnsSurvived', '-')
        }
        players.append(rec)
        by_uid[p.get('userId')] = rec

    # 时长（秒）
    duration_seconds = None
    try:
        if isinstance(start_at, (int, float)) and isinstance(end_at, (int, float)) and end_at >= start_at:
            duration_seconds = int((end_at - start_at) / 1000)
    except Exception:
        pass

    # 轮次与时间线/会议（若有）
    rounds_raw = match.get('rounds') or []
    rounds = []
    for i, rnd in enumerate(rounds_raw, start=1):
        timeline_raw = rnd.get('timeline') if isinstance(rnd, dict) else None
        has_timeline = timeline_raw is not None
        timeline = timeline_raw or []
        events = []
        for ev in timeline:
            etype = ev.get('type')
            label = EVENT_MAP.get(str(etype), str(etype) if etype is not None else '-')
            uid = ev.get('uid')
            tid = ev.get('targetId')
            uinfo = by_uid.get(uid, {}) if uid else {}
            tinfo = by_uid.get(tid, {}) if tid else {}
            events.append({
                'timestamp': ev.get('timestamp'),
                'type': etype,
                'typeLabel': label,
                'uid': uid,
                'uNickname': uinfo.get('nickname', ''),
                'uRoleName': uinfo.get('roleName', ''),
                'targetId': tid,
                'tNickname': tinfo.get('nickname', ''),
                'tRoleName': tinfo.get('roleName', ''),
            })
        meeting_info = rnd.get('meetingInfo') if isinstance(rnd, dict) else None
        rounds.append({
            'index': i,
            'events': events,
            'meetingInfo': meeting_info,
            'hasTimeline': has_timeline,
            'hasMeeting': meeting_info is not None,
        })

    return {
        'meta': {
            'mode': mode_val,
            'map': map_val,
            'playerCount': len(players),
            'startAt': start_at,
            'endAt': end_at,
            'durationSeconds': duration_seconds,
        },
        'players': players,
        'rounds': rounds
    }


@app.post("/api/fetch")
def fetch(req: FetchReq = Body(...)):
    # 兼容旧接口：一次性登录并返回数据
    token_acquired = SCRAPER_SEM.acquire(blocking=False)
    if not token_acquired:
        raise HTTPException(status_code=429, detail="当前访问较多，请稍后重试", headers={"Retry-After": str(SCRAPER_RETRY_AFTER)})
    scraper = GaggleFunScraper(headless=True)
    try:
        if not scraper.login(req.email, req.password):
            raise HTTPException(status_code=401, detail="登录失败")
        # 停用：前端 DOM 抓取
        # headers, rows = scraper.fetch()
        # 改为：触发生成 SearchMatches JSON
        scraper.fetch_game_records()
        latest = _latest_searchmatches_file()
        return {"ok": True, "searchMatchesFile": str(latest) if latest else None}
    finally:
        try:
            scraper.close()
        except Exception:
            pass
        try:
            SCRAPER_SEM.release()
        except Exception:
            pass


# ---- 实时刷新与 SSE 推送 ----
REFRESH_INTERVAL_SECONDS = int(os.getenv("REFRESH_INTERVAL_SECONDS", "600"))

def _broadcast_sse(session_id: str, event: str, data: dict):
    s = SESSIONS.get(session_id)
    if not s:
        return
    queues = list(s.get("sse_queues", []))
    payload = json.dumps(data, ensure_ascii=False)
    for q in queues:
        try:
            q.put_nowait({"event": event, "data": payload})
        except Exception:
            pass

@app.get("/api/sse")
def api_sse(session_id: str = Query(...)):
    s = SESSIONS.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    q = Queue()
    try:
        s.setdefault("sse_queues", []).append(q)
    except Exception:
        pass
    _mark_active(session_id)
    def event_stream():
        try:
            while True:
                try:
                    item = q.get(timeout=15)
                    yield f"event: {item.get('event')}\n"
                    yield f"data: {item.get('data')}\n\n"
                except Empty:
                    yield ": keep-alive\n\n"
        finally:
            try:
                queues = s.get("sse_queues", [])
                if q in queues:
                    queues.remove(q)
                if not queues:
                    try:
                        if s.get("refresh_stop"):
                            s["refresh_stop"].set()
                    except Exception:
                        pass
                    try:
                        t = s.get("refresh_thread")
                        if t:
                            t.join(timeout=2)
                    except Exception:
                        pass
                    s["refresh_thread"] = None
                    s["refresh_stop"] = None
            except Exception:
                pass
    headers = {"Cache-Control": "no-cache"}
    return StreamingResponse(event_stream(), media_type="text/event-stream", headers=headers)

def _ensure_session_scraper(session_id: str):
    s = SESSIONS.get(session_id)
    if not s:
        return
    if s.get("scraper"):
        return
    token_acquired = SCRAPER_SEM.acquire(blocking=False)
    if not token_acquired:
        raise HTTPException(status_code=429, detail="当前访问较多，请稍后重试", headers={"Retry-After": str(SCRAPER_RETRY_AFTER)})
    scraper = GaggleFunScraper(headless=True)
    s["scraper"] = scraper
    # 使用 cookies 免登录或回退到账号登录
    ok = False
    cookies_path = _session_cookies_path(session_id)
    try:
        if cookies_path.exists():
            ok = scraper.try_cookie_login(str(cookies_path))
    except Exception:
        ok = False
    if not ok:
        auth = s.get("auth") or {}
        email = auth.get("email")
        password = auth.get("password")
        if not email or not password:
            # 回收已占用的并发
            try:
                SCRAPER_SEM.release()
            except Exception:
                pass
            s["scraper"] = None
            raise HTTPException(status_code=400, detail="会话未保存认证信息")
        ok = scraper.login(email, password)
        if not ok:
            try:
                SCRAPER_SEM.release()
            except Exception:
                pass
            s["scraper"] = None
            raise HTTPException(status_code=401, detail="登录失败")
        try:
            scraper.save_cookies(str(cookies_path))
        except Exception:
            pass

def _refresh_loop(session_id: str, stop_evt: threading.Event):
    while not stop_evt.is_set():
        try:
            s = SESSIONS.get(session_id)
            if not s:
                return
            queues = s.get("sse_queues", [])
            if not queues:
                break
            try:
                la = s.get("last_active")
            except Exception:
                la = None
            if la is not None and (time.time() - la) >= 1800:
                break
            _ensure_session_scraper(session_id)
            scraper: GaggleFunScraper = s.get("scraper")
            if not scraper:
                return
            # 抓取最新 SearchMatches（直写会话文件）
            search_dst = _session_searchmatches_path(session_id)
            lock = s.get("lock")
            if lock:
                with lock:
                    scraper.fetch_game_records(save_path=str(search_dst))
            else:
                scraper.fetch_game_records(save_path=str(search_dst))
            # 可选：归档并清理
            _maybe_archive_searchmatches(search_dst)
            _cleanup_archive()
            # 比对 matchIds，抓取新增详情
            try:
                if (search_dst and Path(search_dst).exists()):
                    with open(search_dst, 'r', encoding='utf-8') as f:
                        payload = json.load(f)
                    latest_matches = (payload or {}).get('data', {}).get('body', {}).get('latestMatches', [])
                    new_ids = [m.get('matchId') for m in latest_matches if isinstance(m, dict) and m.get('matchId')]
                else:
                    new_ids = []
            except Exception:
                new_ids = []
            old_ids = s.get("match_ids") or []
            added = [mid for mid in new_ids if mid not in set(old_ids)]
            s["match_ids"] = new_ids
            any_detail = False
            for mid in added:
                try:
                    if lock:
                        with lock:
                            detail = scraper.fetch_match_detail(mid)
                    else:
                        detail = scraper.fetch_match_detail(mid)
                    if detail is not None:
                        _save_match_detail_json(session_id, mid, detail)
                        any_detail = True
                except Exception:
                    pass
            # 通知前端 records/detail 更新
            _broadcast_sse(session_id, "records", {"version": int(time.time())})
            if any_detail:
                _broadcast_sse(session_id, "detail", {"type": "added"})
        except Exception:
            pass
        stop_evt.wait(REFRESH_INTERVAL_SECONDS)
    try:
        s = SESSIONS.get(session_id)
        if s:
            try:
                if s.get("scraper"):
                    s["scraper"].close()
            except Exception:
                pass
            try:
                if s.get("scraper") is not None:
                    SCRAPER_SEM.release()
            except Exception:
                pass
            s["scraper"] = None
            s["refresh_thread"] = None
            s["refresh_stop"] = None
    except Exception:
        pass

@app.post("/api/refresh_now")
def refresh_now(session_id: str = Query(...)):
    s = SESSIONS.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        _mark_active(session_id)
        _ensure_session_scraper(session_id)
        scraper: GaggleFunScraper = s.get("scraper")
        search_path = _session_searchmatches_path(session_id)
        lock = s.get("lock")
        if lock:
            with lock:
                scraper.fetch_game_records(save_path=str(search_path))
        else:
            scraper.fetch_game_records(save_path=str(search_path))
        # 可选：归档并清理
        _maybe_archive_searchmatches(search_path)
        _cleanup_archive()
        # 解析新增 matchId 并抓取详情
        try:
            if (search_path and Path(search_path).exists()):
                with open(search_path, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                latest_matches = (payload or {}).get('data', {}).get('body', {}).get('latestMatches', [])
                new_ids = [m.get('matchId') for m in latest_matches if isinstance(m, dict) and m.get('matchId')]
            else:
                new_ids = []
        except Exception:
            new_ids = []
        old_ids = s.get("match_ids") or []
        added = [mid for mid in new_ids if mid not in set(old_ids)]
        s["match_ids"] = new_ids
        any_detail = False
        for mid in added:
            try:
                if lock:
                    with lock:
                        detail = scraper.fetch_match_detail(mid)
                else:
                    detail = scraper.fetch_match_detail(mid)
                if detail is not None:
                    _save_match_detail_json(session_id, mid, detail)
                    any_detail = True
            except Exception:
                pass
        _broadcast_sse(session_id, "records", {"version": int(time.time())})
        if any_detail:
            _broadcast_sse(session_id, "detail", {"type": "added"})
        return {"accepted": True, "detailUpdated": any_detail}
    except HTTPException:
        raise
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/refresh_stop")
def refresh_stop(session_id: str = Query(...)):
    s = SESSIONS.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        try:
            if s.get("refresh_stop"):
                s["refresh_stop"].set()
        except Exception:
            pass
        try:
            t = s.get("refresh_thread")
            if t:
                t.join(timeout=2)
        except Exception:
            pass
        s["refresh_thread"] = None
        s["refresh_stop"] = None
        return {"stopped": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/api/session/close")
def session_close(session_id: str = Query(...)):
    s = SESSIONS.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
    try:
        try:
            if s.get("refresh_stop"):
                s["refresh_stop"].set()
        except Exception:
            pass
        try:
            t = s.get("refresh_thread")
            if t:
                t.join(timeout=2)
        except Exception:
            pass
        try:
            if s.get("scraper"):
                s["scraper"].close()
        except Exception:
            pass
        try:
            SCRAPER_SEM.release()
        except Exception:
            pass
        SESSIONS.pop(session_id, None)
        return {"closed": True}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


if __name__ == "__main__":
    uvicorn.run("web.app:app", host="127.0.0.1", port=8000, reload=True)

# ---- 后台清理任务：删除超过 TTL 的会话目录 ----
DATA_TTL_HOURS = int(os.getenv("DATA_TTL_HOURS", "24"))

def _session_age_hours(p: Path) -> float:
    try:
        meta = p / '.meta.json'
        if meta.exists():
            with open(meta, 'r', encoding='utf-8') as f:
                info = json.load(f)
            ts = info.get('created_at')
            if ts:
                try:
                    dt = datetime.fromisoformat(ts)
                except Exception:
                    dt = datetime.now(timezone.utc)
                now = datetime.now(dt.tzinfo or timezone.utc)
                return (now - dt).total_seconds() / 3600.0
        # 回退：使用 mtime
        return (time.time() - p.stat().st_mtime) / 3600.0
    except Exception:
        return DATA_TTL_HOURS + 1

def _janitor_loop(stop_evt: threading.Event):
    try:
        SESS_ROOT.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    while not stop_evt.is_set():
        try:
            for d in SESS_ROOT.iterdir():
                if d.is_dir() and _session_age_hours(d) > DATA_TTL_HOURS:
                    shutil.rmtree(d, ignore_errors=True)
        except Exception:
            pass
        # 清理内存会话与浏览器
        try:
            remove_keys = []
            now = time.time()
            for sid, s in list(SESSIONS.items()):
                try:
                    sd = _session_dir(sid)
                    # 检查 30 分钟无活动
                    la = s.get("last_active")
                    inactive_30min = la is not None and (now - la) >= 1800
                    # 检查 24 小时过期
                    expired_24h = (not sd.exists()) or (_session_age_hours(sd) > DATA_TTL_HOURS)

                    if inactive_30min or expired_24h:
                        try:
                            if s.get("refresh_stop"):
                                s["refresh_stop"].set()
                        except Exception:
                            pass
                        try:
                            if s.get("scraper"):
                                s["scraper"].close()
                        except Exception:
                            pass
                        try:
                            if s.get("scraper") is not None:
                                SCRAPER_SEM.release()
                        except Exception:
                            pass
                        remove_keys.append(sid)
                except Exception:
                    pass
            for sid in remove_keys:
                SESSIONS.pop(sid, None)
        except Exception:
            pass
        # 定期清理归档目录
        try:
            _cleanup_archive()
        except Exception:
            pass
        stop_evt.wait(300)  # 5 分钟巡检一次

@app.on_event("startup")
def _start_janitor():
    app.state._janitor_stop = threading.Event()
    t = threading.Thread(target=_janitor_loop, args=(app.state._janitor_stop,), daemon=True)
    t.start()

@app.on_event("shutdown")
def _stop_janitor():
    try:
        app.state._janitor_stop.set()
    except Exception:
        pass
