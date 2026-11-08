"""快照：Clusters + 历史快照 → data/snapshots/YYYYMMDD-HH.json（JST）、latest.json、升降/NEW/轨迹。
公开字段白名单：id,title,url,source,family,rank,heat,time,category。原子写入；只删固定目录+固定文件名。"""
import json
import os
import re
import tempfile
from datetime import datetime
from pathlib import Path

from .common import JST, UTC, canon_url, iso, parse_iso
from .match import conflict, features, same
from .score import in_tab

PUBLIC_FIELDS = ("id", "title", "url", "source", "family", "rank", "heat", "time", "category",
                 "delta", "trend", "engagement", "E", "D", "k", "families")   # 只放标题、链接和自算数字；不放正文/片段
PUBLIC_TOP = ("at", "prev_at", "gap_h", "failed", "rows")
SNAP_RE = re.compile(r"^\d{8}-\d{2}\.json$")   # 固定文件名格式


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
        if not SNAP_RE.match(p.name):
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
            assert isinstance(data.get("rows"), list) and data.get("at")
        except Exception:
            continue
        hour = datetime.strptime(p.name[:11], "%Y%m%d-%H").replace(tzinfo=JST)
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


def compare(clusters, snaps, now, tabs, w):
    """返回 view 片段：每个 tab 前 page_top 条的 rank/delta/hist，以及 prev_at、gap_h。"""
    prev, gap = choose_prev(snaps, now, int(w["max_gap_h"]))
    cur_hour = now.astimezone(JST).replace(minute=0, second=0, microsecond=0)
    hist_snaps = [(h, d) for h, d in snaps if h < cur_hour][-(int(w["hist_len"]) - 1):]
    res = {}
    for tab in tabs:
        lst = [c for c in clusters if in_tab(c, tab)][: int(w["page_top"])]
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
    files = sorted(p for p in d.iterdir() if not p.is_symlink() and p.is_file() and SNAP_RE.match(p.name) and p.parent == d)
    old = files[:-keep] if len(files) > keep else []
    log(f"prune: 快照 {len(files)} 份，保留 {keep}，将删除 {len(old)} 份")
    for p in old:
        p.unlink()
    return [p.name for p in old]


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
