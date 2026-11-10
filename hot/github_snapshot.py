"""GitHub 模块快照：写入 data/github_snapshots/YYYYMMDD-HHMM.json（JST，精确到分钟），保留 48 小时。
也接受旧的 YYYYMMDD-HH.json，以免已有 cache 读不到。"""
import json
import os
import re
from datetime import timedelta
from pathlib import Path

from .common import JST, iso, parse_iso
from .snapshot import atomic_write

# 新文件精确到分钟，避免每小时第 23 与 53 分互相覆盖；旧的整点小时名仍能加载
GH_SNAP_RE = re.compile(r"^\d{8}-\d{2}(\d{2})?\.json$")

ITEM_KEYS = (
    "full_name", "name", "owner_login", "url", "description", "language", "topics", "tags",
    "stars", "stars_delta", "stars_window", "stars_7d", "rank", "board", "created_at",
    "forks_count", "license_spdx",
)
# last_complete_day 只写入快照 candidates，供 ≤26h 复用，不进入页面内嵌 JSON
SNAP_EXTRA = ("last_complete_day",)
TOP_KEYS = ("at", "prev_at", "gap_h", "failed", "window_note")


def public_item(row, extra=()):
    out = {}
    for k in ITEM_KEYS + extra:
        if k in row:
            v = row[k]
            if k == "topics":
                out[k] = list(v or [])
            elif k == "tags":
                out[k] = list(v or [])
            else:
                out[k] = v
    return out


def choose_prev(snaps, now, max_gap_h=3):
    """与最近一份 ≤ max_gap_h 小时内的快照比升降；超过视为首次。"""
    best = None
    for snap in snaps:
        at = parse_iso(snap.get("at"))
        if not at or at >= now:
            continue
        gap = (now - at).total_seconds() / 3600.0
        if gap > max_gap_h:
            continue
        if best is None or at > parse_iso(best.get("at")):
            best = snap
    return best


def load_snapshots(snap_dir):
    d = Path(snap_dir)
    if not d.is_dir():
        return []
    out = []
    for p in sorted(d.iterdir(), reverse=True):
        if p.is_symlink() or not p.is_file() or not GH_SNAP_RE.match(p.name):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except Exception:
            continue
        if isinstance(data, dict) and data.get("at"):
            out.append(data)
    return out


def attach_compare(boards, snaps, now):
    prev = choose_prev(snaps, now, max_gap_h=3)
    gap = None
    if prev:
        gap = round((now - parse_iso(prev["at"])).total_seconds() / 3600.0, 2)
    compared = {}
    for name, rows in boards.items():
        prev_names = set()
        prev_rank = {}
        if prev:
            for r in (prev.get("boards") or {}).get(name) or []:
                k = (r.get("full_name") or "").lower()
                prev_names.add(k)
                if r.get("rank") is not None:
                    prev_rank[k] = r["rank"]
        out = []
        for r in rows:
            d = dict(r)
            k = (d.get("full_name") or "").lower()
            if prev is None:
                d["is_new"] = False
                d["rank_delta"] = None
            elif k not in prev_names:
                d["is_new"] = True
                d["rank_delta"] = None
            else:
                d["is_new"] = False
                d["rank_delta"] = prev_rank.get(k) - d["rank"] if prev_rank.get(k) else None
            out.append(d)
        compared[name] = out
    return compared, prev, gap


def window_note(first, partial, stale_h=None):
    parts = []
    if stale_h is not None:
        parts.append(f"GitHub 项目数据已 {stale_h:.1f} 小时未更新")
    if first:
        parts.append("对比：无（首次快照）")
    if partial:
        parts.append("部分项目未取到星数历史")
    return "。".join(parts)


def failed_names(status):
    out = []
    for s in status.get("search") or []:
        if not s.get("ok"):
            out.append(s.get("name") or "search")
    return out


def write_snapshot(data_dir, now, boards, measured, status, prev_at, gap_h, note):
    snap_dir = Path(data_dir) / "github_snapshots"
    candidates = [public_item(c, extra=SNAP_EXTRA) for c in measured]
    doc = dict(
        at=iso(now),
        prev_at=prev_at,
        gap_h=gap_h,
        failed=failed_names(status),
        window_note=note,
        candidates=candidates,
        boards={k: [public_item(r) for r in (boards.get(k) or [])] for k in ("rising", "hot", "all")},
    )
    path = snap_dir / gh_snap_name(now)
    atomic_write(path, json.dumps(doc, ensure_ascii=False, separators=(",", ":")))
    return path


def prune(snap_dir, now, keep_hours=48, log=print):
    d = Path(snap_dir)
    if d.is_symlink():
        raise ValueError("快照目录是符号链接，拒绝 prune")
    if not d.is_dir():
        log("prune: github 快照目录不存在，跳过")
        return []
    files = sorted(p for p in d.iterdir() if not p.is_symlink() and p.is_file() and GH_SNAP_RE.match(p.name) and p.parent == d)
    cutoff = now.astimezone(JST) - timedelta(hours=keep_hours)
    old = []
    for p in files:
        try:
            ts = datetime_from_name(p.name)
        except ValueError:
            continue
        if ts < cutoff:
            old.append(p)
    log(f"prune: github 快照 {len(files)} 份，保留 {keep_hours} 小时，将删除 {len(old)} 份")
    for p in old:
        p.unlink()
    return [p.name for p in old]


def gh_snap_name(now):
    return now.astimezone(JST).strftime("%Y%m%d-%H%M") + ".json"


def datetime_from_name(name):
    from datetime import datetime
    stem = name[:-5] if name.endswith(".json") else name
    if len(stem) >= 13 and stem[9:13].isdigit():
        return datetime.strptime(stem[:13], "%Y%m%d-%H%M").replace(tzinfo=JST)
    return datetime.strptime(stem[:11], "%Y%m%d-%H").replace(tzinfo=JST)


def visible_items(rows, marked, limit=20):
    """Page contract: skip rows whose full_name (case-insensitive) is marked, keep order, take limit, re-rank from 1.
    marked is a dict keyed by full_name (or lowercased), or a set of names. Empty/false / unknown values are ignored."""
    names = set()
    if isinstance(marked, dict):
        for k, v in marked.items():
            if not k:
                continue
            if isinstance(v, dict):
                st = v.get("state")
                if st in ("interested", "not_interested", "seen"):
                    names.add(str(k).lower())
            elif v in ("interested", "not_interested", "seen") or v is True:
                names.add(str(k).lower())
    elif marked:
        names = {str(k).lower() for k in marked if k}
    out = []
    for r in rows or []:
        fn = r.get("full_name") or ""
        if not fn or fn.lower() in names:
            continue
        d = dict(r)
        d["orig_rank"] = r.get("rank")
        d["rank"] = len(out) + 1
        out.append(d)
        if len(out) >= int(limit):
            break
    return out


def public_view(boards, now, prev_at, gap_h, note, page_public=None, stale_h=None, status=None):
    """写入页面的结构：条目字段只用白名单（不含 is_new / last_complete_day）。
    Each board list is cut to page_public (default 60) so the page can refill after local marks."""
    if page_public is None:
        from .github_rank import page_public as _page_public
        cut_n = _page_public()
    else:
        cut_n = int(page_public)
    cut = {}
    for name in ("rising", "hot", "all"):
        rows = []
        for r in (boards.get(name) or [])[:cut_n]:
            rows.append(public_item(r))
        cut[name] = rows
    return dict(
        at=iso(now),
        prev_at=prev_at,
        gap_h=gap_h,
        failed=failed_names(status or {}),
        window_note=note,
        boards=cut,
    )


def load_prev_view(data_dir):
    p = Path(data_dir) / "github_latest.json"
    try:
        d = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return None
    return d if isinstance(d, dict) and d.get("at") else None


def save_latest_view(data_dir, view):
    p = Path(data_dir) / "github_latest.json"
    atomic_write(p, json.dumps(view, ensure_ascii=False, separators=(",", ":")))
    return p


def run_module(now, data_dir, log=print, base="https://api.github.com", skip_network=False,
               token=None, timeout=None, backoff=None, concurrency=None, history_cap=None):
    """采集 → 打分 → 写快照 → 页面视图。失败时返回上一份成功视图（带过期说明），不抛给新闻流水线。"""
    from .github_collect import collect_github
    from .github_rank import rank_boards, page_public as page_public_of

    data_dir = Path(data_dir)
    snap_dir = data_dir / "github_snapshots"
    prev_view = load_prev_view(data_dir)
    pub_n = page_public_of()
    empty_boards = {k: [] for k in ("rising", "hot", "all")}
    if skip_network:
        return public_view(empty_boards, now, None, None, window_note(True, False), page_public=pub_n)
    try:
        snaps = load_snapshots(snap_dir)
        cands, status, _log = collect_github(
            now, snaps, token=token, base=base, timeout=timeout, backoff=backoff,
            concurrency=concurrency, history_cap=history_cap)
        search_failed = status.get("search_ok", 0) == 0
        prev_all = None
        if search_failed and snaps:
            prev_all = (snaps[0].get("boards") or {}).get("all")
        ranked = rank_boards(cands, snaps, now, search_failed=search_failed, prev_all=prev_all)
        board3 = {k: ranked[k] for k in ("rising", "hot", "all")}
        compared, prev, gap = attach_compare(board3, snaps, now)
        first = prev is None
        note = window_note(first, status.get("partial_history"))
        prev_at = prev.get("at") if prev else None
        has_rows = any(compared.get(k) for k in ("rising", "hot", "all"))
        if search_failed and status.get("history_ok", 0) == 0 and not has_rows:
            raise RuntimeError("GitHub 采集失败且本轮无上榜条目")
        write_snapshot(data_dir, now, compared, ranked["measured"], status, prev_at, gap, note)
        prune(snap_dir, now, keep_hours=48, log=log)
        view = public_view(compared, now, prev_at, gap, note, page_public=pub_n, status=status)
        save_latest_view(data_dir, view)
        blocked = ranked.get("blocked") or []
        names = [b.get("full_name") or "" for b in blocked]
        log("github block: " + str(len(blocked)) + ((": " + ", ".join(n for n in names if n)) if names else ""))
        conflicts = [b.get("full_name") or "" for b in blocked if b.get("allowlist_conflict")]
        if conflicts:
            log("github block: allowlist overridden by blocklist_repos: " + ", ".join(conflicts))
        log(f"github: candidates {status.get('candidates')} search {status.get('search_ok')}/{status.get('search_n')} "
            f"history_ok {status.get('history_ok')} history_http {status.get('history_http')}")
        if status.get("partial_history"):
            log("部分项目未取到星数历史")
        return view
    except Exception as e:
        log(f"github 模块失败：{type(e).__name__}: {str(e)[:160]}")
        if prev_view:
            at = parse_iso(prev_view.get("at"))
            stale = (now - at).total_seconds() / 3600.0 if at else None
            v = dict(prev_view)
            v["window_note"] = window_note(False, False, stale_h=stale)
            v.pop("stale_h", None)
            v.pop("cats", None)
            v.pop("footer", None)
            return v
        return public_view(empty_boards, now, None, None, window_note(True, True), page_public=pub_n)
