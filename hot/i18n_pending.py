"""Build the public i18n_pending.json list.

The file is written into the Pages artifact (site/). It only contains
already-public source titles, teasers, and GitHub descriptions, plus
keys, hashes, and ranks. No URL fields, logs, or config.
"""
import json
from pathlib import Path

from .i18n_apply import _teaser_for
from .i18n_cache import (
    desc_hash, github_key, news_id_key, news_src_hash, news_title_key,
    strip_query_string,
)
from .i18n_quality import already_chinese, i18n_cfg, quality_ok
from .snapshot import atomic_write

PENDING_VERSION = 1
PENDING_MAX_BYTES = 200_000
NEWS_FIELDS = ("key", "title_key", "title", "teaser", "src_hash", "rank")
GITHUB_FIELDS = ("key", "description", "topics", "src_hash", "rank", "no_desc", "name", "full_name")
TOP_FIELDS = ("version", "generated_at", "news", "github")


def _int_rank(row):
    try:
        return int(row.get("rank") or 0)
    except (TypeError, ValueError):
        return 0


def _clean_text(text):
    return strip_query_string(text).strip() if text else ""


def _clip_topics(raw, limit=16, each=32):
    out = []
    if not isinstance(raw, (list, tuple)):
        return out
    for t in raw:
        if not isinstance(t, str):
            continue
        s = _clean_text(t)
        if not s:
            continue
        out.append(s[:each])
        if len(out) >= limit:
            break
    return out


def _clusters_by_id(clusters):
    out = {}
    for c in clusters or []:
        cid = c.get("id")
        if cid:
            out[cid] = c
    return out


def collect_news_pending(view, clusters, teasers, pool=40):
    """Union of the first `pool` rows of each news tab, unique by id, best rank."""
    by_id = _clusters_by_id(clusters)
    items = (view or {}).get("items") or {}
    best = {}
    for rows in ((view or {}).get("cats") or {}).values():
        for row in rows or []:
            cid = row.get("id")
            if not cid:
                continue
            rank = _int_rank(row)
            if rank < 1 or rank > int(pool):
                continue
            cl = by_id.get(cid) or {}
            title = cl.get("title") or (items.get(cid) or {}).get("title") or row.get("title") or ""
            rec = best.get(cid)
            if rec is None or rank < rec["rank"]:
                teaser = _teaser_for(cl or {"title": title, "url": (items.get(cid) or {}).get("url") or row.get("url") or ""}, teasers)
                title = _clean_text(title)
                teaser = _clean_text(teaser)
                best[cid] = {
                    "key": news_id_key(cid),
                    "title_key": news_title_key(title),
                    "title": title,
                    "teaser": teaser,
                    "src_hash": news_src_hash(title, teaser),
                    "rank": rank,
                }
    out = list(best.values())
    out.sort(key=lambda r: (r["rank"], r["key"]))
    return out


def collect_github_pending(gh_view, summaries, cfg, page_public=60):
    """60 published repos per board, minus already-Chinese or already-summarized."""
    cfg = i18n_cfg(cfg)
    best = {}
    for rows in ((gh_view or {}).get("boards") or {}).values():
        for row in rows or []:
            fn = (row.get("full_name") or "").strip()
            if not fn:
                continue
            rank = _int_rank(row)
            if rank < 1 or rank > int(page_public):
                continue
            desc = _clean_text(row.get("description") or "")
            existing = (summaries or {}).get(fn) if isinstance(summaries, dict) else None
            if isinstance(existing, dict) and quality_ok(existing.get("summary"), cfg):
                continue
            if desc and already_chinese(desc, None, cfg):
                continue
            key = github_key(fn)
            rec = best.get(key)
            if rec is None or rank < rec["rank"]:
                name = _clean_text(row.get("name") or "")
                full_name = _clean_text(fn)
                # Unified field set for every GitHub row. no_desc is true only
                # when the source description is empty; src_hash is still
                # sha256(strip(description)), so an empty desc hashes to sha256("").
                best[key] = {
                    "key": key,
                    "description": desc,
                    "topics": _clip_topics(row.get("topics")),
                    "src_hash": desc_hash(desc),
                    "rank": rank,
                    "no_desc": (not bool(desc)),
                    "name": name,
                    "full_name": full_name,
                }
    out = list(best.values())
    out.sort(key=lambda r: (r["rank"], r["key"]))
    return out


def _dump(payload):
    return json.dumps(payload, ensure_ascii=False, indent=2) + "\n"


def _trim_to_budget(news, github, generated_at, max_bytes):
    """Drop highest-rank items first until the UTF-8 size is within budget."""
    news = list(news)
    github = list(github)
    dropped = 0
    while True:
        payload = {
            "version": PENDING_VERSION,
            "generated_at": generated_at,
            "news": news,
            "github": github,
        }
        raw = _dump(payload).encode("utf-8")
        if len(raw) <= max_bytes:
            return payload, raw, dropped
        if not news and not github:
            return payload, raw, dropped
        # Highest rank first; at a tie drop github before news.
        candidates = []
        if news:
            worst_n = max(news, key=lambda r: (r["rank"], r["key"]))
            candidates.append((worst_n["rank"], 1, "news", worst_n))
        if github:
            worst_g = max(github, key=lambda r: (r["rank"], r["key"]))
            candidates.append((worst_g["rank"], 0, "github", worst_g))
        _rank, _pref, kind, rec = max(candidates, key=lambda x: (x[0], x[1], x[3]["key"]))
        if kind == "news":
            news.remove(rec)
        else:
            github.remove(rec)
        dropped += 1


def build_pending(view, gh_view, clusters, teasers, github_summaries=None,
                  now_iso="", cfg=None, max_bytes=PENDING_MAX_BYTES, pool=None, page_public=60):
    cfg = i18n_cfg(cfg)
    pool = int(pool if pool is not None else (cfg.get("pool") or 40))
    news = collect_news_pending(view, clusters, teasers, pool=pool)
    github = collect_github_pending(gh_view, github_summaries, cfg, page_public=page_public)
    payload, raw, dropped = _trim_to_budget(news, github, now_iso, int(max_bytes))
    return payload, raw, dropped


def write_pending(path, view, gh_view, clusters, teasers, github_summaries=None,
                  now_iso="", cfg=None, max_bytes=PENDING_MAX_BYTES, pool=None, page_public=60):
    payload, raw, dropped = build_pending(
        view, gh_view, clusters, teasers, github_summaries=github_summaries,
        now_iso=now_iso, cfg=cfg, max_bytes=max_bytes, pool=pool, page_public=page_public,
    )
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(dest, raw.decode("utf-8"))
    return dest, payload, len(raw), dropped
