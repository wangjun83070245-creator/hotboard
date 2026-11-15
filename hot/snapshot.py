"""快照：Clusters + 历史快照 → data/snapshots/YYYYMMDD-HH.json（JST）、latest.json、升降/NEW/轨迹。
公开字段白名单：id,title,url,source,family,rank,heat,time,category。原子写入；只删固定目录+固定文件名。"""
import json
import os
import re
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

from .common import JST, UTC, canon_url, iso, parse_iso
from .match import conflict, features, same
from .score import in_tab

PUBLIC_FIELDS = ("id", "title", "url", "source", "family", "rank", "heat", "time", "category",
                 "delta", "trend", "engagement", "E", "D", "k", "families")   # 只放标题、链接和自算数字；不放正文/片段
PUBLIC_TOP = ("at", "prev_at", "gap_h", "failed", "rows")
SNAP_RE = re.compile(r"[0-9]{8}-[0-9]{2}\.json", re.ASCII)   # 固定文件名格式，只用 fullmatch


def snap_name(now):
    return now.astimezone(JST).strftime("%Y%m%d-%H") + ".json"


def atomic_write(path, text):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=path.parent, prefix=".tmp-", suffix=".part")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(text)
            f.flush()
            os.fsync(f.fileno())
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.unlink(tmp)
        raise


def public_rows(clusters, tabs, top):
    rows = []
    for tab in tabs:
        lst = [c for c in clusters if in_tab(c, tab)][:top]
        for i, c in enumerate(lst):
            rows.append(dict(id=c["id"], title=c["title"], url=c["url"], source=c["source"], family=c["family"],
                             rank=i + 1, heat=c["H"], time=c["first_pub"], category=tab))
    return rows


def load_snapshots(snap_dir):
    """读快照；损坏/半写的当作缺失。返回 [(hour_dt_jst, data)] 升序。"""
    out = []
    d = Path(snap_dir)
    if not d.is_dir():
        return out
    for p in sorted(d.iterdir()):
        if not SNAP_RE.fullmatch(p.name):
            continue
        try:
            hour = datetime.strptime(p.name[:11], "%Y%m%d-%H").replace(tzinfo=JST)
        except ValueError:
            continue   # 格式对但日期非法（如 13 月），跳过
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            assert isinstance(data.get("rows"), list) and data.get("at")
        except Exception:
            continue
        out.append((hour, data))
    return out


def _match(c, row):
    if row["id"] == c["id"]:
        return True
    cu = canon_url(row["url"])
    if cu and cu in c["urls"]:
        return True
    # 逐个成员标题比较，不用簇内并集；与代表标题冲突则不认为是同一条
    if conflict(features(c["title"]), features(row["title"])):
        return False
    titles = [c["title"]] + [m.get("title", "") for m in c.get("members", [])]
    return any(same(t, row["title"]) for t in titles if t)


def find(c, data, tab):
    for r in data["rows"]:
        if r["category"] == tab and _match(c, r):
            return r
    return None


def choose_prev(snaps, now, max_gap_h):
    cur_hour = now.astimezone(JST).replace(minute=0, second=0, microsecond=0)
    older = [(h, d) for h, d in snaps if h < cur_hour]
    if not older:
        return None, None
    h, d = older[-1]
    gap = int(round((cur_hour - h).total_seconds() / 3600))
    if gap > max_gap_h:
        return None, None
    return (h, d), gap


def compare(clusters, snaps, now, tabs, w, top=None):
    """返回 view 片段：每个 tab 前 top 条（默认 page_top）的 rank/delta/hist，以及 prev_at、gap_h。"""
    prev, gap = choose_prev(snaps, now, int(w["max_gap_h"]))
    cur_hour = now.astimezone(JST).replace(minute=0, second=0, microsecond=0)
    hist_snaps = [(h, d) for h, d in snaps if h < cur_hour][-(int(w["hist_len"]) - 1):]
    res = {}
    n = int(top if top is not None else w["page_top"])
    for tab in tabs:
        lst = [c for c in clusters if in_tab(c, tab)][:n]
        rows = []
        for i, c in enumerate(lst):
            rank = i + 1
            if prev is None:
                delta = None
            else:
                r = find(c, prev[1], tab)
                if r is None or r["rank"] > int(w["new_threshold"]):
                    delta = "new"
                else:
                    delta = r["rank"] - rank
            hist = []
            for h, d in hist_snaps:
                r = find(c, d, tab)
                hist.append(dict(at=d["at"], rank=r["rank"] if r else None, heat=r["heat"] if r else None))
            hist.append(dict(at=iso(now), rank=rank, heat=c["H"]))
            trend = None
            for p in hist[:-1]:
                dt = (now - parse_iso(p["at"])).total_seconds() / 3600
                if 2.5 <= dt <= 3.5 and p["heat"] is not None:
                    trend = round(c["H"] - p["heat"], 2)
            rows.append(dict(id=c["id"], rank=rank, delta=delta, trend=trend, hist=hist))
        res[tab] = rows
    return dict(cats=res, prev_at=prev[1]["at"] if prev else None, gap_h=gap, snaps=[d["at"] for _, d in hist_snaps] + [iso(now)])


def prune(snap_dir, keep, log=print):
    """只在固定快照目录里删，只匹配 YYYYMMDD-HH.json，删前打印数量。"""
    d = Path(snap_dir)
    if d.is_symlink():
        raise ValueError("快照目录是符号链接，拒绝 prune")
    files = sorted(p for p in d.iterdir() if not p.is_symlink() and p.is_file() and SNAP_RE.fullmatch(p.name) and p.parent == d)
    old = files[:-keep] if len(files) > keep else []
    log(f"prune: 快照 {len(files)} 份，保留 {keep}，将删除 {len(old)} 份")
    for p in old:
        p.unlink()
    return [p.name for p in old]


# Actions cache: data/snapshots + data/github_snapshots + data/github_latest.json.
# 32MB is insurance only: going over it writes a log line, nothing required is
# deleted. i18n_cache.json keeps its own 1MB hard limit in i18n_import (unchanged).
#
# What the readers need (kept set must equal what they would read unpruned):
# - news heat trajectory / previous-hour delta: last hist_len valid hourly files
#   older than the current hour (compare / choose_prev), 3h trend is taken from
#   that same list (2.5-3.5h);
# - GitHub: 24h compare picks, per repository, the file closest to 24h inside
#   [now-27h, now-21h]; 1h compare uses [now-90min, now-30min]; rank delta uses
#   <=3h; history reuse looks back 26h. Any file younger than 27h will fall into
#   a later run's 24h window, so every GitHub file up to GH_KEEP_H is kept.
#   Thinning inside that range would change which file a later run picks.
SNAPSHOT_CACHE_MAX_BYTES = 32_000_000
NEWS_TREND_MIN_H = 2.5
NEWS_TREND_MAX_H = 3.5
NEWS_FUTURE_SLACK_H = 0.0
GH_24H_MIN_H = 21.0
GH_24H_MAX_H = 27.0
GH_KEEP_H = GH_24H_MAX_H + 0.5
GH_SNAP_NAME_RE = re.compile(r"[0-9]{8}-[0-9]{2}(?:[0-9]{2})?\.json", re.ASCII)


def _snap_sort_key(path):
    name = path.name
    stem = name[:-5] if name.endswith(".json") else name
    return (stem, name)


def snap_file_when(path):
    """Timestamp implied by a snapshot filename, in JST. News is hour-only.

    Returns None for names that are not exact ASCII snapshot names or that hold
    an impossible date; such files are neither read as history nor deleted.
    """
    name = Path(path).name
    if not (SNAP_RE.fullmatch(name) or GH_SNAP_NAME_RE.fullmatch(name)):
        return None
    stem = name[:-5]
    try:
        if len(stem) == 13:
            return datetime.strptime(stem, "%Y%m%d-%H%M").replace(tzinfo=JST)
        return datetime.strptime(stem, "%Y%m%d-%H").replace(tzinfo=JST)
    except ValueError:
        return None


def _file_size(path):
    try:
        return path.stat().st_size
    except OSError:
        return 0


def _list_snap_files(d, pat):
    p = Path(d)
    if not p.is_dir() or p.is_symlink():
        return []
    out = []
    for f in p.iterdir():
        if f.is_symlink() or not f.is_file():
            continue
        if pat.fullmatch(f.name) and snap_file_when(f) is not None:
            out.append(f)
    return out


def _news_valid(path):
    """Same check as load_snapshots: unreadable files do not count as history."""
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
        return isinstance(data.get("rows"), list) and bool(data.get("at"))
    except Exception:
        return False


def needed_snapshot_paths(news_dir, gh_dir, now, hist_len=12, max_gap_h=3, gh_keep_h=GH_KEEP_H):
    """Paths later runs will read; everything else in the two dirs may go.

    News: walking back from now, keep files until hist_len valid ones are
    kept (broken files met on the way are kept too, they are skipped by the
    reader anyway), plus any file in the 2.5-3.5h trend band. Files dated after
    now are kept but do not count toward hist_len, so they cannot push real
    history out; the count-based prune (keep_snapshots) still bounds them.
    GitHub: every file with age <= gh_keep_h (and any future-dated file).
    """
    now = now.astimezone(JST) if now.tzinfo else now.replace(tzinfo=JST)
    needed = set()
    future_cut = now + timedelta(hours=NEWS_FUTURE_SLACK_H)
    news_timed = []
    for f in _list_snap_files(news_dir, SNAP_RE):
        when = snap_file_when(f)
        if when > future_cut:
            needed.add(f)
        else:
            news_timed.append((when, f))
    news_timed.sort(key=lambda x: x[0], reverse=True)
    hist_len = max(1, int(hist_len))
    valid = 0
    for when, f in news_timed:
        if valid >= hist_len:
            break
        needed.add(f)
        if _news_valid(f):
            valid += 1
    for when, f in news_timed:
        dt = (now - when).total_seconds() / 3600.0
        if NEWS_TREND_MIN_H - 1.0 <= dt <= NEWS_TREND_MAX_H:
            needed.add(f)   # hourly name; its "at" may be up to 59 min later

    keep_h = max(float(gh_keep_h), float(max_gap_h) + 0.5)
    for f in _list_snap_files(gh_dir, GH_SNAP_NAME_RE):
        age = (now - snap_file_when(f)).total_seconds() / 3600.0
        if age <= keep_h:
            needed.add(f)
    return needed


def cache_snapshot_bytes(data_dir):
    """Total bytes of the three Actions-cache paths that exist."""
    data_dir = Path(data_dir)
    n = 0
    for rel in ("snapshots", "github_snapshots"):
        d = data_dir / rel
        if not d.is_dir() or d.is_symlink():
            continue
        for f in d.iterdir():
            if f.is_file() and not f.is_symlink():
                n += _file_size(f)
    latest = data_dir / "github_latest.json"
    if latest.is_file() and not latest.is_symlink():
        n += _file_size(latest)
    return n


def prune_snapshot_cache(data_dir, now, w=None, max_bytes=SNAPSHOT_CACHE_MAX_BYTES, log=print):
    """Keep the snapshots the three history features need; thin the rest.

    max_bytes is insurance: if required files already exceed it, they are kept
    and the overflow is logged. github_latest.json is never deleted.
    """
    data_dir = Path(data_dir)
    news_dir = data_dir / "snapshots"
    gh_dir = data_dir / "github_snapshots"
    latest = data_dir / "github_latest.json"
    w = w or {}
    hist_len = int(w.get("hist_len") or 12)
    max_gap_h = int(w.get("max_gap_h") or 3)
    needed = needed_snapshot_paths(
        news_dir, gh_dir, now, hist_len=hist_len, max_gap_h=max_gap_h,
    )
    removable = []
    for d, pat in ((news_dir, SNAP_RE), (gh_dir, GH_SNAP_NAME_RE)):
        for f in _list_snap_files(d, pat):
            if f not in needed:
                removable.append(f)
    removable.sort(key=_snap_sort_key)
    removed = []
    for f in removable:
        try:
            size = _file_size(f)
            f.unlink()
            removed.append(f.name)
            log(f"prune cache keep: 抽稀删除 {f.name}（{size} 字节）")
        except OSError as e:
            log(f"prune cache keep: 无法删除 {f.name}: {type(e).__name__}")
    total = cache_snapshot_bytes(data_dir)
    n_news = len(_list_snap_files(news_dir, SNAP_RE))
    n_gh = len(_list_snap_files(gh_dir, GH_SNAP_NAME_RE))
    log(f"prune cache keep: 新闻 {n_news} 份，GitHub {n_gh} 份，合计 {total} 字节（保险上限 {int(max_bytes)}）")
    if total > int(max_bytes):
        log(f"prune cache keep: 必需文件合计 {total} 超过保险上限 {int(max_bytes)}，未删必需文件")
    return removed


def prune_cache_to_bytes(dirs, extra_files=(), max_bytes=SNAPSHOT_CACHE_MAX_BYTES, log=print, now=None, w=None):
    """Back-compat wrapper: infer data_dir and apply keep-needed pruning."""
    data_dir = None
    for d in dirs:
        p = Path(d)
        if p.name in {"snapshots", "github_snapshots"}:
            data_dir = p.parent
            break
    if data_dir is None:
        log("prune cache keep: 无法推断 data 目录，跳过")
        return []
    if now is None:
        now = datetime.now(JST)
    return prune_snapshot_cache(data_dir, now, w=w, max_bytes=max_bytes, log=log)


def write_snapshot(clusters, status, now, data_dir, tabs, w):
    data_dir = Path(data_dir)
    snap_dir = data_dir / "snapshots"
    rows = public_rows(clusters, tabs + ["finance"], int(w["snapshot_top"]))
    doc = dict(at=iso(now), failed=[s["name"] for s in status if not s["ok"] and not s.get("skipped")], rows=rows)
    path = snap_dir / snap_name(now)
    atomic_write(path, json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    return path


def write_latest(clusters, status, now, data_dir, tabs, w, cmp):
    """latest.json：每类前 page_top，字段只用 PUBLIC_FIELDS。cmp 为 compare() 结果（cache 丢失时为首次）。"""
    by = {c["id"]: c for c in clusters}
    rows = []
    for tab in tabs:
        for r in cmp["cats"].get(tab, []):
            c = by[r["id"]]
            rows.append(dict(id=c["id"], title=c["title"], url=c["url"], source=c["source"], family=c["family"],
                             rank=r["rank"], heat=c["H"], time=c["first_pub"], category=tab, delta=r["delta"], trend=r["trend"],
                             engagement=[dict(source=m["source"], metrics=m["metrics"]) for m in c["members"]],
                             E=c["E"], D=c["D"], k=c["k"], families=c["families"]))
    doc = dict(at=iso(now), prev_at=cmp["prev_at"], gap_h=cmp["gap_h"],
               failed=[s["name"] for s in status if not s["ok"] and not s.get("skipped")], rows=rows)
    atomic_write(Path(data_dir) / "latest.json", json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
