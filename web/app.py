"""
GooseGooseDuck 游戏记录查询 - Web 后端（前后端分离）
FastAPI 提供 /api/fetch 接口，前端在 static/index.html 中调用
"""

from pathlib import Path
from fastapi import FastAPI
from fastapi import HTTPException
from fastapi import Body, Query
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, RedirectResponse
from pydantic import BaseModel
from typing import Optional
import os
import shutil
import time
import threading
import uvicorn

# from web.scraper import GaggleScraper  # 注释：停用基于前端 DOM 的抓取
from login import GaggleFunScraper
import uuid
import json
from datetime import datetime, timezone

BASE_DIR = Path(__file__).parent.resolve()
PROJECT_DIR = BASE_DIR.parent.resolve()

# ---- 抓取并发闸配置 ----
SCRAPER_CONCURRENCY = int(os.getenv("SCRAPER_CONCURRENCY", "3"))
SCRAPER_RETRY_AFTER = int(os.getenv("SCRAPER_RETRY_AFTER", "5"))  # 秒
SCRAPER_SEM = threading.BoundedSemaphore(SCRAPER_CONCURRENCY if SCRAPER_CONCURRENCY > 0 else 1)

app = FastAPI(title="GooseGooseDuck 游戏记录 - API")
app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
app.mount("/assets/role_logos", StaticFiles(directory=str(PROJECT_DIR / "data" / "role_logos")), name="role_logos")


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


def _latest_searchmatches_file():
    """返回 data/ 目录下最新的 SearchMatches_*.json 文件路径（Path 或 None）。"""
    data_dir = PROJECT_DIR / 'data'
    try:
        files = sorted(data_dir.glob('SearchMatches_*.json'), key=lambda p: p.stat().st_mtime, reverse=True)
        return files[0] if files else None
    except Exception:
        return None

# 对局详情保存目录（旧路径，保留兼容）
DETAIL_DIR = PROJECT_DIR / 'data' / '对局详情jsonl'

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

def _write_session_meta(session_id: str):
    meta_path = _session_dir(session_id) / '.meta.json'
    try:
        with open(meta_path, 'w', encoding='utf-8') as f:
            json.dump({'created_at': datetime.now(timezone.utc).isoformat()}, f, ensure_ascii=False)
    except Exception:
        pass

def _save_match_detail_json(session_id: Optional[str], match_id: str, detail_data: dict) -> Path:
    """保存单个对局详情到会话目录，若无 session_id 则落旧目录。"""
    if session_id:
        out_path = _session_detail_path(session_id, match_id)
        try:
            _session_dir(session_id)  # ensure
            with open(out_path, 'w', encoding='utf-8') as f:
                json.dump({'match_id': match_id, 'data': detail_data}, f, ensure_ascii=False, indent=2)
        except Exception:
            pass
        return out_path
    # 兼容旧路径
    try:
        DETAIL_DIR.mkdir(parents=True, exist_ok=True)
    except Exception:
        pass
    out_path = DETAIL_DIR / f"{match_id}.json"
    try:
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
    scraper = GaggleFunScraper(headless=True)
    try:
        # 停用：前端 DOM 预加载
        # scraper.preload_login_page()
        # 改为直接打开登录页，等待后续 /api/login 使用
        scraper.driver.get(scraper.LOGIN_URL)
        SESSIONS[session_id] = {"scraper": scraper, "status": "ready", "data": None}
        return {"session_id": session_id, "status": "ready"}
    except Exception as e:
        try:
            scraper.close()
        except Exception:
            pass
        raise HTTPException(status_code=500, detail=f"预加载失败: {e}")


@app.post("/api/login")
def api_login(req: LoginReq = Body(...)):
    token_acquired = SCRAPER_SEM.acquire(blocking=False)
    if not token_acquired:
        raise HTTPException(status_code=429, detail="当前访问较多，请稍后重试", headers={"Retry-After": str(SCRAPER_RETRY_AFTER)})
    # 允许无会话直接登录：若无 session_id 或 session 不存在，则创建新会话与浏览器
    session_id = req.session_id or uuid.uuid4().hex[:12]
    s = SESSIONS.get(session_id)
    created_new = False
    if not s:
        scraper = GaggleFunScraper(headless=True)
        s = {"scraper": scraper, "status": "ready", "data": None}
        SESSIONS[session_id] = s
        created_new = True
    elif not s.get("scraper"):
        # 旧会话但浏览器已释放，按需重建
        s["scraper"] = GaggleFunScraper(headless=True)

    scraper: GaggleFunScraper = s["scraper"]
    try:
        ok = scraper.login(req.email, req.password)
        if not ok:
            s["status"] = "error"
            # 根据爬虫内部错误标记返回更清晰的信息
            try:
                err = getattr(scraper, 'last_error', None)
            except Exception:
                err = None
            if err == 'invalid_credentials':
                raise HTTPException(status_code=401, detail="用户名或密码错误")
            raise HTTPException(status_code=401, detail="登录失败")

        # 停用：基于前端 DOM 的抓取
        # headers, rows = scraper.fetch()
        # 改为：调用后端接口抓取，生成 data/SearchMatches_*.json
        scraper.fetch_game_records()
        # 将抓取的最新 SearchMatches_* 复制到会话目录
        latest = _latest_searchmatches_file()
        sess_dir = _session_dir(session_id)
        _write_session_meta(session_id)
        search_dst = _session_searchmatches_path(session_id)
        if latest and latest.exists():
            try:
                shutil.copy2(latest, search_dst)
            except Exception:
                # 回退：直接引用最新文件
                search_dst = latest
        else:
            search_dst = latest if latest else None
        s["data"] = {"searchMatchesFile": str(search_dst) if search_dst else None}

        # 从 SearchMatches 取前5个 matchId，抓取对局详情并保存
        match_details = []
        try:
            if latest and latest.exists():
                with open(latest, 'r', encoding='utf-8') as f:
                    payload = json.load(f)
                latest_matches = (payload or {}).get('data', {}).get('body', {}).get('latestMatches', [])
                match_ids = [m.get('matchId') for m in latest_matches if isinstance(m, dict) and m.get('matchId')]
                # 缓存匹配到的全部 matchId 以及登录凭据（仅会话内存使用）
                s["match_ids"] = match_ids
                s["auth"] = {"email": req.email, "password": req.password}
                for mid in match_ids[:5]:
                    detail = scraper.fetch_match_detail(mid)
                    if detail is not None:
                        _save_match_detail_json(session_id, mid, detail)
                        match_details.append({"matchId": mid, "data": detail})
        except Exception:
            pass
        if match_details:
            s["match_details"] = match_details
        s["status"] = "done"
        return {"ok": True, "session_id": session_id}
    finally:
        try:
            scraper.close()
        except Exception:
            pass
        s["scraper"] = None
        try:
            SCRAPER_SEM.release()
        except Exception:
            pass


@app.get("/api/records")
def api_records(session_id: str = Query(...)):
    s = SESSIONS.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
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
    maps_values = []
    modes_values = []
    try:
        maps_values = list((EN_CN_MAPPING.get('MAPS') or {}).values())
    except Exception:
        maps_values = []
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
                if isinstance(map_idx, int) and map_idx >= 1 and map_idx <= len(maps_values):
                    map_cn = maps_values[map_idx - 1]
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
    result = {"headers": headers, "rows": rows, "summary": {"total": total, "wins": wins, "losses": losses, "win_rate": win_rate}, "extras": extras}
    # 缓存标准结果，便于后续重复请求
    s["data"] = result
    return result


@app.get("/api/record_detail")
def api_record_detail(session_id: str = Query(...), index: int = Query(0)):
    """返回对局详情（从会话中缓存的原始JSON转换为前端所需结构）。"""
    s = SESSIONS.get(session_id)
    if not s:
        raise HTTPException(status_code=404, detail="会话不存在")
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
        # 若仍无详情，则进行按需网络抓取
        if index >= len(details) or not details[index]:
            auth = s.get("auth") or {}
            email = auth.get("email")
            password = auth.get("password")
            if not email or not password:
                raise HTTPException(status_code=400, detail="会话未保存认证信息，无法按需抓取")
            # 按需实例化 scraper 抓取该条详情
            token_acquired = SCRAPER_SEM.acquire(blocking=False)
            if not token_acquired:
                raise HTTPException(status_code=429, detail="当前访问较多，请稍后重试", headers={"Retry-After": str(SCRAPER_RETRY_AFTER)})
            scraper = GaggleFunScraper(headless=True)
            try:
                if not scraper.login(email, password):
                    raise HTTPException(status_code=401, detail="登录失败")
                detail = scraper.fetch_match_detail(mid)
                if detail is None:
                    raise HTTPException(status_code=500, detail="抓取对局详情失败")
                _save_match_detail_json(session_id, mid, detail)
                # 将结果放入会话缓存，保持索引对齐
                if index >= len(details):
                    details.extend([None] * (index - len(details) + 1))
                details[index] = {"matchId": mid, "data": detail}
                s["match_details"] = details
            finally:
                try:
                    scraper.close()
                except Exception:
                    pass
                try:
                    SCRAPER_SEM.release()
                except Exception:
                    pass
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
        stop_evt.wait(1800)  # 30 分钟巡检一次

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
