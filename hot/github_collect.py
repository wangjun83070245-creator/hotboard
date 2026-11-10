"""GitHub 候选池：Search 七次 + 快照增量筛选后再请求 stargazers/history。

只访问 api.github.com 的 /search/repositories 与 /repos/{owner}/{repo}/stargazers/history。
不请求点星人列表、不抓 trending 页。认证只用环境变量 GITHUB_TOKEN（未设置则匿名）；
请求头与日志都不打印令牌。history 的每一次 HTTP（含重试）都计入硬上限。
"""
import json
import os
import socket
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from .common import UTC, load_yaml, parse_iso

RETRYABLE = {429, 403, 500, 502, 503, 504}
MIN_BACKOFF = 2.0
API_HOST = "api.github.com"


class FetchError(Exception):
    def __init__(self, msg, http=None, remaining=None, resource=None):
        super().__init__(msg)
        self.http = http
        self.remaining = remaining
        self.resource = resource


def _cfg():
    w = load_yaml("weights.yaml")
    t = load_yaml("github_tags.yaml")
    return {
        "ua": w["user_agent"],
        "timeout": float(w.get("timeout_s", 20)),
        "backoff": max(MIN_BACKOFF, float(w.get("retry_backoff_s", 2.0))),
        "concurrency": int(w.get("concurrency", 8)),
        "api_version": str(t.get("api_version") or "2022-11-28"),
        "history_cap": int(t.get("history_cap") or 300),
        "e_max": int(t.get("e_max") or 200),
        "delta_24h_min": int(t.get("delta_24h_min") or 50),
        "delta_1h_min": int(t.get("delta_1h_min") or 5),
        "window_24h_min_h": float(t.get("window_24h_min_h") or 21),
        "window_24h_max_h": float(t.get("window_24h_max_h") or 27),
        "window_1h_min_min": float(t.get("window_1h_min_min") or 30),
        "window_1h_max_min": float(t.get("window_1h_max_min") or 90),
        "history_reuse_h": float(t.get("history_reuse_h") or 26),
    }


def search_plan(now):
    """七次 Search：A×1 + C7×2 + C30×2 + P×2。日期用 UTC 日历日。"""
    utc = now.astimezone(UTC)
    d7 = (utc - timedelta(days=7)).strftime("%Y-%m-%d")
    d30 = (utc - timedelta(days=30)).strftime("%Y-%m-%d")
    return [
        ("A", "fork:false archived:false stars:>1", "stars", 1),
        ("C7", f"fork:false archived:false created:>{d7} stars:>=50", "stars", 1),
        ("C7", f"fork:false archived:false created:>{d7} stars:>=50", "stars", 2),
        ("C30", f"fork:false archived:false created:>{d30} stars:>=100", "stars", 1),
        ("C30", f"fork:false archived:false created:>{d30} stars:>=100", "stars", 2),
        ("P", f"fork:false archived:false stars:1000..34000 pushed:>{d7}", "updated", 1),
        ("P", f"fork:false archived:false stars:1000..34000 pushed:>{d7}", "updated", 2),
    ]


def _headers(cfg, token):
    h = {
        "User-Agent": cfg["ua"],
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": cfg["api_version"],
    }
    if token:
        h["Authorization"] = "Bearer " + token
    return h


def _read_remaining(resp):
    try:
        rem = resp.headers.get("X-RateLimit-Remaining")
        return int(rem) if rem is not None else None
    except (TypeError, ValueError):
        return None


def _one_get(url, cfg, token, timeout):
    if urllib.parse.urlparse(url).hostname != API_HOST and not url.startswith("http://127.0.0.1"):
        raise FetchError("只允许请求 api.github.com", None)
    req = urllib.request.Request(url, headers=_headers(cfg, token))
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            body = r.read(5_000_000)
            return r.status, dict(r.headers), body, _read_remaining(r)
    except urllib.error.HTTPError as e:
        raw = b""
        try:
            raw = e.read(2000)
        except Exception:
            pass
        rem = None
        try:
            rem = int(e.headers.get("X-RateLimit-Remaining")) if e.headers else None
        except (TypeError, ValueError):
            rem = None
        raise FetchError(f"HTTP {e.code}", e.code, remaining=rem)
    except (socket.timeout, TimeoutError):
        raise FetchError("timeout", None)
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise FetchError("timeout", None)
        raise FetchError(f"URLError {type(e.reason).__name__}", None)


def fetch_with_policy(url, cfg, token, timeout, backoff, log, lock, kind, remaining_box, cost_box=None,
                      track_remaining=False):
    """429/403/超时/5xx 最多重试 1 次、间隔 ≥2 秒。每次 HTTP 都记入 log；cost_box 每次 HTTP 减 1。
    track_remaining 只应对 history/core 打开，避免把 Search 桶的 remaining 当成 core。"""
    backoff = max(MIN_BACKOFF, float(backoff))
    attempt = 0
    while True:
        attempt += 1
        if cost_box is not None:
            with lock:
                if cost_box["n"] < 1:
                    raise FetchError("history 已达本轮上限", None)
                cost_box["n"] -= 1
        try:
            status, headers, body, rem = _one_get(url, cfg, token, timeout)
            with lock:
                log.append(dict(kind=kind, url=_safe_url(url), attempt=attempt, http=status, err=None))
                if track_remaining and rem is not None:
                    remaining_box["n"] = rem
            return status, headers, body, rem
        except FetchError as e:
            with lock:
                log.append(dict(kind=kind, url=_safe_url(url), attempt=attempt, http=e.http, err=str(e)))
                if track_remaining and e.remaining is not None:
                    remaining_box["n"] = e.remaining
            retryable = e.http in RETRYABLE or str(e) == "timeout"
            if attempt >= 2 or not retryable:
                raise
            time.sleep(backoff)


def _safe_url(url):
    p = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((p.scheme, p.netloc, p.path, p.query, ""))


def search_url(base, q, sort, page, per_page=100):
    qs = urllib.parse.urlencode({"q": q, "sort": sort, "order": "desc", "per_page": per_page, "page": page})
    return f"{base}/search/repositories?{qs}"


def history_url(base, owner, repo):
    o = urllib.parse.quote(owner)
    r = urllib.parse.quote(repo)
    return f"{base}/repos/{o}/{r}/stargazers/history?per_page=2"


def _item_from_search(it, source):
    fn = it.get("full_name") or ""
    owner = ((it.get("owner") or {}).get("login")) or (fn.split("/")[0] if "/" in fn else "")
    lic = it.get("license") or {}
    return {
        "full_name": fn,
        "name": it.get("name") or (fn.split("/")[-1] if fn else ""),
        "owner_login": owner,
        "url": it.get("html_url") or "",
        "description": it.get("description"),
        "language": it.get("language"),
        "topics": list(it.get("topics") or []),
        "stars": int(it.get("stargazers_count") or 0),
        "forks_count": int(it.get("forks_count") or 0),
        "fork": bool(it.get("fork")),
        "archived": bool(it.get("archived")),
        "disabled": bool(it.get("disabled")),
        "created_at": it.get("created_at"),
        "pushed_at": it.get("pushed_at"),
        "license_spdx": lic.get("spdx_id") if isinstance(lic, dict) else None,
        "sources": {source},
    }


def merge_candidates(rows, log=None):
    """按 full_name 小写去重；星数取较大值；来源标记取并集。"""
    by = {}
    for c in rows:
        fn = (c.get("full_name") or "").strip()
        if not fn:
            continue
        k = fn.lower()
        if k not in by:
            d = dict(c)
            d["sources"] = set(c.get("sources") or [])
            by[k] = d
            continue
        old = by[k]
        old["sources"] |= set(c.get("sources") or [])
        if int(c.get("stars") or 0) > int(old.get("stars") or 0):
            if log is not None:
                log.append(dict(kind="dedup", url=k, attempt=0, http=None,
                                err=f"stargazers_count 不一致，取较大值 {old.get('stars')} -> {c.get('stars')}"))
            old["stars"] = int(c["stars"])
    return list(by.values())


def e_from_snapshots(snaps, now, limit):
    """cache 里过去 7 天出现过的候选，最多 limit 个（不额外打 Search）。"""
    cutoff = now - timedelta(days=7)
    seen, out = set(), []
    for snap in snaps:
        at = parse_iso(snap.get("at"))
        if at and at < cutoff:
            continue
        for row in snap.get("candidates") or []:
            k = (row.get("full_name") or "").lower()
            if not k or k in seen:
                continue
            seen.add(k)
            d = dict(row)
            d["sources"] = set(row.get("sources") or []) | {"E"}
            out.append(d)
            if len(out) >= limit:
                return out
    return out


def _stars_at(snaps, full_name, now, lo_h, hi_h):
    """在 [now-hi_h, now-lo_h] 内找该仓的快照点，取最接近窗口中点的。"""
    k = full_name.lower()
    lo, hi = timedelta(hours=lo_h), timedelta(hours=hi_h)
    mid = now - timedelta(hours=(lo_h + hi_h) / 2)
    best, best_d = None, None
    for snap in snaps:
        at = parse_iso(snap.get("at"))
        if not at or at < now - hi or at > now - lo:
            continue
        for row in snap.get("candidates") or []:
            if (row.get("full_name") or "").lower() == k and "stars" in row:
                d = abs((at - mid).total_seconds())
                if best_d is None or d < best_d:
                    best, best_d = (int(row["stars"]), at), d
                break
    return best


def _has_any_snapshot(snaps, full_name):
    k = full_name.lower()
    for snap in snaps:
        for row in snap.get("candidates") or []:
            if (row.get("full_name") or "").lower() == k:
                return True
    return False


def reuse_history(snaps, full_name, now, reuse_h):
    """≤ reuse_h 小时内上次算好的 last_complete_day / stars_7d。"""
    k = full_name.lower()
    cutoff = now - timedelta(hours=reuse_h)
    for snap in snaps:
        at = parse_iso(snap.get("at"))
        if not at or at < cutoff:
            continue
        for row in snap.get("candidates") or []:
            if (row.get("full_name") or "").lower() != k:
                continue
            s7 = row.get("stars_7d")
            lcd = row.get("last_complete_day")
            if lcd is None and row.get("stars_window") == "last_complete_day":
                lcd = row.get("stars_delta")
            if s7 is None and lcd is None:
                return None
            return dict(stars_7d=s7, last_complete_day=lcd, last_complete_ok=lcd is not None, reused=True, at=at)
    return None


def history_queue(cands, snaps, now, cfg):
    """阈值：24h 增量 / 1h 增量 / C7·C30 新发现。返回 (queued_with_priority, skipped_reason)。"""
    queued = []
    for c in cands:
        src = set(c.get("sources") or [])
        fn = c["full_name"]
        stars = int(c.get("stars") or 0)
        p24 = _stars_at(snaps, fn, now, cfg["window_24h_min_h"], cfg["window_24h_max_h"])
        p1 = _stars_at(snaps, fn, now, cfg["window_1h_min_min"] / 60.0, cfg["window_1h_max_min"] / 60.0)
        d24 = (stars - p24[0]) if p24 else None
        d1 = (stars - p1[0]) if p1 else None
        no_snap = not _has_any_snapshot(snaps, fn)
        reason, prio, inc = None, None, d24 if d24 is not None else (d1 if d1 is not None else 0)
        if p24 and d24 is not None and d24 >= cfg["delta_24h_min"]:
            reason = "d24"
        elif (not p24) and p1 and d1 is not None and d1 >= cfg["delta_1h_min"]:
            reason = "d1"
        elif (("C7" in src) or ("C30" in src)) and no_snap:
            reason = "new"
        if not reason:
            continue
        if reason == "new" and "C7" in src:
            prio = 1
        elif "C7" in src and reason in ("d24", "d1"):
            prio = 2
        elif reason == "new" and "C30" in src:
            prio = 3
        elif "C30" in src and reason in ("d24", "d1"):
            prio = 4
        elif reason == "d24":
            prio = 5
        else:
            prio = 6
        queued.append((prio, -int(inc or 0), -stars, fn.lower(), c, reason, d24, d1))
    queued.sort()
    return queued


def parse_history(body):
    data = json.loads(body.decode("utf-8") if isinstance(body, (bytes, bytearray)) else body)
    if isinstance(data, list):
        return data
    if isinstance(data, dict) and isinstance(data.get("history"), list):
        return data["history"]
    raise FetchError("history 响应不是列表", None)


def collect_github(now, snaps=None, token=None, base="https://api.github.com", timeout=None,
                   backoff=None, concurrency=None, history_cap=None):
    """返回 candidates（已去重、带 sources / history 字段）、status、request_log、counts。"""
    cfg = _cfg()
    if timeout is not None:
        cfg["timeout"] = float(timeout)
    if backoff is not None:
        cfg["backoff"] = max(MIN_BACKOFF, float(backoff))
    if concurrency is not None:
        cfg["concurrency"] = int(concurrency)
    if history_cap is not None:
        cfg["history_cap"] = int(history_cap)
    if token is None:
        token = os.environ.get("GITHUB_TOKEN") or None
        if token is not None and not str(token).strip():
            token = None
    snaps = list(snaps or [])
    log, lock = [], threading.Lock()
    remaining_box = {"n": None}
    search_status = []
    raw = []
    for source, q, sort, page in search_plan(now):
        url = search_url(base, q, sort, page)
        st = dict(name=f"search:{source}:{page}", ok=False, http=None, err=None, n=0)
        try:
            status, _h, body, _rem = fetch_with_policy(
                url, cfg, token, cfg["timeout"], cfg["backoff"], log, lock, f"search:{source}", remaining_box)
            st["http"] = status
            data = json.loads(body.decode("utf-8"))
            items = data.get("items") or []
            for it in items:
                raw.append(_item_from_search(it, source))
            st.update(ok=True, n=len(items))
        except FetchError as e:
            st.update(http=e.http, err=str(e)[:120])
        except Exception as e:
            st.update(err=f"{type(e).__name__}: {str(e)[:100]}")
        search_status.append(st)

    raw.extend(e_from_snapshots(snaps, now, cfg["e_max"]))
    cands = merge_candidates(raw, log)
    queued = history_queue(cands, snaps, now, cfg)
    cap = cfg["history_cap"]
    # 每一次 HTTP（含重试）计入上限，保证每小时 2 轮 × 每轮 ≤300 ≤ 1000
    http_left = {"n": cap}
    stop_remaining = {"on": False}
    histories = {}

    def run_one(item):
        _prio, _inc, _st, _k, c, reason, d24, d1 = item
        fn = c["full_name"]
        owner, _, repo = fn.partition("/")
        if not owner or not repo:
            return fn, None, "bad_name"
        with lock:
            if stop_remaining["on"]:
                return fn, None, "ratelimit"
            if http_left["n"] < 1:
                return fn, None, "cap"
            rem = remaining_box["n"]
            if rem is not None and rem < 1:
                stop_remaining["on"] = True
                return fn, None, "ratelimit"
        url = history_url(base, owner, repo)
        try:
            status, _h, body, _rem = fetch_with_policy(
                url, cfg, token, cfg["timeout"], cfg["backoff"], log, lock, "history", remaining_box,
                cost_box=http_left, track_remaining=True)
            weeks = parse_history(body)
            return fn, weeks, None
        except FetchError as e:
            return fn, None, str(e)[:120]
        except Exception as e:
            return fn, None, f"{type(e).__name__}: {str(e)[:100]}"

    # 先按优先序截到 cap（上限按「请求次数」而不是仓数；仓数不会超过 cap）
    todo = queued[:cap]
    skipped_cap = max(0, len(queued) - len(todo))
    workers = max(1, min(cfg["concurrency"], len(todo) or 1))
    if todo:
        with ThreadPoolExecutor(workers) as ex:
            for fn, weeks, err in ex.map(run_one, todo):
                histories[fn.lower()] = dict(weeks=weeks, err=err)

    hist_ok = sum(1 for v in histories.values() if v["weeks"] is not None)
    hist_fail = sum(1 for v in histories.values() if v["weeks"] is None and v["err"] not in ("cap", "ratelimit"))
    hist_skip_rl = sum(1 for v in histories.values() if v.get("err") == "ratelimit")
    hist_skip_cap = skipped_cap + sum(1 for v in histories.values() if v.get("err") == "cap")

    by = {c["full_name"].lower(): c for c in cands}
    for c in cands:
        k = c["full_name"].lower()
        h = histories.get(k)
        if h and h["weeks"] is not None:
            c["history"] = h["weeks"]
            c["history_err"] = None
        else:
            reused = reuse_history(snaps, c["full_name"], now, cfg["history_reuse_h"])
            c["history"] = None
            c["history_err"] = (h or {}).get("err")
            c["history_reuse"] = reused

    search_ok = sum(1 for s in search_status if s["ok"])
    hist_http = cap - http_left["n"]
    status = dict(
        search=search_status,
        search_ok=search_ok,
        search_n=len(search_status),
        history_ok=hist_ok,
        history_fail=hist_fail,
        history_skipped_cap=hist_skip_cap,
        history_skipped_remaining=hist_skip_rl,
        history_http=hist_http,
        history_queued=len(queued),
        candidates=len(cands),
        partial_history=bool(hist_skip_rl or hist_skip_cap or search_ok < len(search_status)),
        token_present=bool(token),
    )
    return cands, status, log


def request_budget(runs_per_hour=2):
    """按每小时 runs 次运行估算请求量（core 桶 vs search 桶）。"""
    search_per_run, history_cap = 7, 300
    other = 0
    search_hour = search_per_run * runs_per_hour
    # history 上限含重试，故每轮 HTTP ≤300，每小时 ≤600
    history_hour = history_cap * runs_per_hour
    core_hour = history_hour + other * runs_per_hour
    return dict(
        runs_per_hour=runs_per_hour,
        search_per_run=search_per_run,
        search_per_hour=search_hour,
        search_bucket="authenticated 30/min (Actions GITHUB_TOKEN); unauthenticated 10/min",
        history_cap_per_run=history_cap,
        history_cap_includes_retries=True,
        history_per_hour_max=history_hour,
        other_per_run=other,
        core_per_hour_max=core_hour,
        core_limit_github_token=1000,
        core_remaining=1000 - core_hour,
        within_1000=core_hour <= 1000,
    )
