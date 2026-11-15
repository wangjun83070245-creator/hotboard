"""Apply translation + quality gate before render. Failed items leave the main board."""
from datetime import datetime, timezone

from .common import JST
from .i18n_cache import (
    desc_hash,
    get_github,
    get_news,
    load_cache,
    news_src_hash,
    put_github,
    put_news,
    save_cache,
)
from .i18n_quality import already_chinese, clip_chars, i18n_cfg, quality_ok
from .i18n_translate import TranslationError, make_translator

EMPTY_INTRO = "暂无简介"


def _now_iso(now=None):
    t = now or datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(JST).isoformat(timespec="seconds")


def _clip_summary(text, cfg):
    return clip_chars((text or "").strip(), int(cfg.get("summary_max") or 50))


def _teaser_for(cluster, teasers):
    if not teasers:
        return ""
    urls = [cluster.get("url")] + [m.get("url") for m in (cluster.get("members") or [])]
    titles = [cluster.get("title")] + [m.get("title") for m in (cluster.get("members") or [])]
    for u in urls:
        if u and teasers.get(u):
            return teasers[u]
    for t in titles:
        if t and teasers.get("title:" + t):
            return teasers.get("title:" + t)
    return ""


def teasers_from_items(items):
    out = {}
    for it in items or []:
        te = (it.get("_teaser") or "").strip()
        if not te:
            continue
        if it.get("url"):
            out[it["url"]] = te
        if it.get("title"):
            out["title:" + it["title"]] = te
    return out


def _try_translate(tr, text):
    try:
        out = tr.translate(text)
    except TranslationError:
        return None
    except Exception:
        return None
    if out is None:
        return None
    return str(out)


def resolve_news_item(cluster, summaries, cache, tr, cfg, teasers, now_iso, calls):
    """Return (rec_or_None, failed_bool, reason). rec has title/summary/generated_at."""
    cid = cluster["id"]
    title = cluster.get("title") or ""
    family = cluster.get("family") or ""
    existing = (summaries or {}).get(cid) if isinstance(summaries, dict) else None
    if isinstance(existing, dict) and quality_ok(existing.get("title"), cfg) and quality_ok(existing.get("summary"), cfg):
        return {"title": existing["title"].strip(), "summary": existing["summary"].strip(),
                "generated_at": existing.get("generated_at") or now_iso}, False, "summaries"

    teaser = _teaser_for(cluster, teasers)
    cached = get_news(cache, cid, title)
    if cached and cached.get("src_hash") == news_src_hash(title, teaser) and quality_ok(cached.get("title"), cfg) and quality_ok(cached.get("summary"), cfg):
        return {"title": cached["title"], "summary": cached["summary"],
                "generated_at": cached.get("generated_at") or now_iso}, False, "cache"

    # Already Chinese title: reuse, still need a Chinese summary.
    if already_chinese(title, family, cfg):
        zh_title = title
    else:
        calls.append(("news-title", cid, title))
        zh_title = _try_translate(tr, title)
        if not quality_ok(zh_title, cfg):
            return None, True, "title"

    if teaser:
        if already_chinese(teaser, family, cfg):
            zh_sum = _clip_summary(teaser, cfg)
        else:
            calls.append(("news-teaser", cid, teaser))
            zh_sum = _try_translate(tr, teaser)
            zh_sum = _clip_summary(zh_sum or "", cfg)
        if not quality_ok(zh_sum, cfg):
            return None, True, "summary"
    else:
        zh_sum = _clip_summary(zh_title, cfg)
        if not quality_ok(zh_sum, cfg):
            return None, True, "summary"

    rec = {"title": zh_title.strip(), "summary": zh_sum, "generated_at": now_iso,
           "src_hash": news_src_hash(title, teaser), "engine": getattr(tr, "name", "") or ""}
    put_news(cache, cid, title, rec)
    return rec, False, "new"


def resolve_github(repo, summaries, cache, tr, cfg, now_iso, calls):
    fn = repo.get("full_name") or ""
    desc = (repo.get("description") or "").strip()
    existing = (summaries or {}).get(fn) if isinstance(summaries, dict) else None
    if isinstance(existing, dict) and quality_ok(existing.get("summary"), cfg):
        return {"summary": existing["summary"].strip(), "generated_at": existing.get("generated_at") or now_iso}, False, "summaries"

    cached = get_github(cache, fn, desc)
    if cached and quality_ok(cached.get("summary"), cfg):
        return {"summary": cached["summary"], "generated_at": cached.get("generated_at") or now_iso}, False, "cache"

    placeholder = (cfg.get("placeholder_intro") or EMPTY_INTRO)
    if not desc:
        rec = {"summary": placeholder, "generated_at": now_iso, "src_hash": desc_hash(""), "engine": "none"}
        if quality_ok(rec["summary"], cfg):
            put_github(cache, fn, rec)
            return rec, False, "placeholder"
        return None, True, "empty"

    if already_chinese(desc, None, cfg) and quality_ok(desc, cfg):
        rec = {"summary": desc, "generated_at": now_iso, "src_hash": desc_hash(desc), "engine": "source"}
        put_github(cache, fn, rec)
        return rec, False, "source-zh"

    calls.append(("gh", fn, desc))
    zh = _try_translate(tr, desc)
    if not quality_ok(zh, cfg):
        return None, True, "desc"
    rec = {"summary": zh.strip(), "generated_at": now_iso, "src_hash": desc_hash(desc),
           "engine": getattr(tr, "name", "") or ""}
    put_github(cache, fn, rec)
    return rec, False, "new"



def _orig_top_failed(groups, key, failed, page_top):
    """Unique failed ids/names that originally sat in ranks 1..page_top of any group."""
    out = set()
    for rows in groups:
        for r in rows or []:
            try:
                rank = int(r.get("rank") or 0)
            except (TypeError, ValueError):
                rank = 0
            if rank < 1 or rank > page_top:
                continue
            ident = r.get(key) or ""
            if ident and ident in failed:
                out.add(ident)
    return out


def apply_news(view, clusters, summaries, cache, tr, cfg, teasers, now=None):
    """Filter each tab to page_top passing items; return updated summaries and drop count."""
    by = {c["id"]: c for c in clusters}
    now_iso = _now_iso(now)
    page_top = int(cfg.get("page_top") or 20)
    new_summ = dict(summaries or {})
    new_cats = {}
    failed_ids = set()
    seen_ok = set()
    calls = []
    orig_cats = view.get("cats") or {}
    # Unique candidate ids in the pool (all tabs)
    cand_ids = []
    for tab, rows in orig_cats.items():
        for r in rows:
            if r["id"] not in cand_ids:
                cand_ids.append(r["id"])

    resolved = {}
    for cid in cand_ids:
        c = by.get(cid)
        if not c:
            failed_ids.add(cid)
            continue
        rec, failed, _why = resolve_news_item(c, new_summ, cache, tr, cfg, teasers, now_iso, calls)
        if failed or not rec:
            failed_ids.add(cid)
            continue
        resolved[cid] = rec
        new_summ[cid] = {"title": rec["title"], "summary": rec["summary"], "generated_at": rec["generated_at"]}
        seen_ok.add(cid)

    for tab, rows in (view.get("cats") or {}).items():
        kept = []
        for r in rows:
            if r["id"] in resolved:
                kept.append(dict(r))
            # else withdrawn
        # re-rank 1..n
        out = []
        for i, r in enumerate(kept[:page_top], 1):
            d = dict(r)
            d["rank"] = i
            out.append(d)
        new_cats[tab] = out

    view = dict(view)
    view["cats"] = new_cats
    # Drop unused items from the public view so withdrawn English titles are not in #data
    keep_ids = {r["id"] for rows in new_cats.values() for r in rows}
    items = view.get("items") or {}
    view["items"] = {k: v for k, v in items.items() if k in keep_ids}
    view["zh_dropped"] = len(_orig_top_failed(orig_cats.values(), "id", failed_ids, page_top))
    return view, new_summ, failed_ids, calls


def apply_github(gh_view, summaries, cache, tr, cfg, now=None):
    if not gh_view or not isinstance(gh_view, dict):
        return gh_view, dict(summaries or {}), set(), []
    now_iso = _now_iso(now)
    new_summ = dict(summaries or {})
    calls = []
    failed = set()
    boards = gh_view.get("boards") or {}
    # resolve every unique repo in the boards (the 60-per-board pool)
    repos = {}
    for rows in boards.values():
        for r in rows or []:
            fn = r.get("full_name") or ""
            if fn and fn not in repos:
                repos[fn] = r

    ok = {}
    for fn, r in repos.items():
        rec, bad, _why = resolve_github(r, new_summ, cache, tr, cfg, now_iso, calls)
        if bad or not rec:
            failed.add(fn)
            continue
        ok[fn] = rec
        new_summ[fn] = {"summary": rec["summary"], "generated_at": rec["generated_at"]}

    page_top = int(cfg.get("page_top") or 20)
    new_boards = {}
    for name, rows in boards.items():
        passed = [dict(r) for r in (rows or []) if (r.get("full_name") or "") in ok]
        # Keep passed first (already in rank order), then do not include failed in the visible 20;
        # retain only passing rows in the published list used for the visible board.
        out = []
        for i, r in enumerate(passed, 1):
            d = dict(r)
            d["rank"] = i
            out.append(d)
        new_boards[name] = out  # may be >20; frontend still shows 20. All remaining have Chinese intros.

    view = dict(gh_view)
    view["boards"] = new_boards
    view["zh_dropped"] = len(_orig_top_failed(boards.values(), "full_name", failed, page_top))
    return view, new_summ, failed, calls


def apply_all(view, gh_view, clusters, news_summaries, github_summaries, cache_path,
              teasers=None, translator=None, cfg=None, now=None, items=None):
    cfg = i18n_cfg(cfg)
    tr = translator or make_translator(cfg=cfg)
    cache = load_cache(cache_path)
    teasers = teasers if teasers is not None else teasers_from_items(items)
    banner = cfg.get("banner") or "本轮有 {n} 条未能译成中文，已撤下"
    news_view, news_summ, news_fail, news_calls = apply_news(
        view, clusters, news_summaries, cache, tr, cfg, teasers, now=now)
    gh_out, gh_summ, gh_fail, gh_calls = apply_github(
        gh_view, github_summaries, cache, tr, cfg, now=now)
    n_news = int(news_view.get("zh_dropped") or 0)
    n_gh = int((gh_out or {}).get("zh_dropped") or 0)
    news_view["zh_banner"] = banner.format(n=n_news) if n_news else ""
    if gh_out is not None:
        gh_out["zh_banner"] = banner.format(n=n_gh) if n_gh else ""
    if cache_path:
        save_cache(cache_path, cache)
    return {
        "view": news_view,
        "github": gh_out,
        "news_summaries": news_summ,
        "github_summaries": gh_summ,
        "news_failed": news_fail,
        "github_failed": gh_fail,
        "news_calls": news_calls,
        "github_calls": gh_calls,
        "cache": cache,
    }
