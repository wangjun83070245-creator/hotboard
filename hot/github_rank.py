"""三榜排序、过滤、类别标签。完整日算法只看 history JSON 与注入的 now。"""
import re
from datetime import datetime

from .common import UTC, load_yaml, parse_iso
from .github_collect import _stars_at

FOOTER = (
    "GitHub 项目排序依据：总榜为当前星数；热度榜为官方星数历史近 7 个完整日新增；"
    "飙升榜在有小时快照时为约 24 小时星数净变化，否则为官方星数历史最近一个完整日新增。"
    "日界不保证对齐 UTC。不含下载量或点击率。"
)


def _cfg():
    return load_yaml("github_tags.yaml")


def tags_of(repo, cfg=None):
    """topics 精确小写匹配，再 language；保留表序，最多 max_tags；未命中 → 其他。"""
    cfg = cfg or _cfg()
    topics = {str(t).lower() for t in (repo.get("topics") or [])}
    lang = repo.get("language")
    hits = []
    for cat in cfg["categories"]:
        if any(t in topics for t in cat.get("topics") or []):
            hits.append(cat["id"])
            continue
        if lang and lang in (cat.get("languages") or []):
            hits.append(cat["id"])
    if not hits:
        hits = [cfg.get("other") or "其他"]
    return hits[: int(cfg.get("max_tags") or 4)]


def category_ids(cfg=None):
    cfg = cfg or _cfg()
    return [c["id"] for c in cfg["categories"]] + [cfg.get("other") or "其他"]


def page_public(cfg=None):
    """How many rows each board keeps in the public page JSON (shown 20 plus reserve)."""
    cfg = cfg or _cfg()
    n = int(cfg.get("page_public") or 60)
    return n if n > 0 else 0


def weekday_index(week, now):
    start = datetime.fromtimestamp(int(week), tz=UTC)
    return (now.astimezone(UTC) - start).days


def complete_days(weeks, now):
    """返回 {last_complete_day, last_complete_ok, stars_7d}；days 长度不是 7 则返回 None（本轮不进飙升/热度）。"""
    if not weeks:
        return None
    cleaned = []
    for w in weeks:
        days = w.get("days") if isinstance(w, dict) else None
        if not isinstance(days, list) or len(days) != 7:
            return None
        cleaned.append(w)
    cur = cleaned[0]
    i = weekday_index(cur["week"], now)
    if i < 0:
        i = 0
    if i > 6:
        i = 6
    if i == 0:
        if len(cleaned) < 2:
            return dict(last_complete_day=0, last_complete_ok=False, stars_7d=0)
        last = int(cleaned[1]["days"][6] or 0)
        buckets = [int(x or 0) for x in reversed(cleaned[1]["days"])]
        return dict(last_complete_day=last, last_complete_ok=True, stars_7d=sum(buckets[:7]))
    seq = [int(x or 0) for x in reversed(cur["days"][:i])]
    if len(cleaned) >= 2:
        seq.extend(int(x or 0) for x in reversed(cleaned[1]["days"]))
    while len(seq) < 7:
        seq.append(0)
    last = int(cur["days"][i - 1] or 0)
    return dict(last_complete_day=last, last_complete_ok=True, stars_7d=sum(seq[:7]))


def _age_h(repo, now):
    created = parse_iso(repo.get("created_at"))
    if not created:
        return 10**9
    if created > now:
        created = now
    return (now - created).total_seconds() / 3600.0


def is_spam(repo, delta, now, cfg=None):
    cfg = cfg or _cfg()
    spam = cfg.get("spam") or {}
    if _age_h(repo, now) >= float(spam.get("max_age_h") or 48):
        return False
    if delta is None or delta <= int(spam.get("min_delta") or 2000):
        return False
    if int(repo.get("forks_count") or 0) >= int(spam.get("max_forks") or 5):
        return False
    topics = repo.get("topics") or []
    desc = repo.get("description")
    if topics:
        return False
    if desc:
        return False
    return True


def excluded(repo):
    return bool(repo.get("fork") or repo.get("archived") or repo.get("disabled"))


def block_config(cfg=None):
    """Terms, patterns, and repo lists from config/github_tags.yaml. No hardcoded words."""
    cfg = cfg or _cfg()
    def _strs(key):
        out = []
        for t in cfg.get(key) or []:
            s = str(t).strip()
            if s:
                out.append(s)
        return out
    return {
        "terms": _strs("block_terms"),
        "need_signal": _strs("block_terms_need_signal"),
        "patch_signals": _strs("block_patch_signals"),
        "patch_signal_patterns": _strs("block_patch_signal_patterns"),
        "allowlist": _strs("allowlist"),
        "blocklist_repos": _strs("blocklist_repos"),
        "name_terms": _strs("block_name_terms"),
        "topic_free_terms": _strs("block_topic_free_terms"),
        "description_patterns": _strs("block_description_patterns"),
    }


def block_config_public(cfg=None):
    """Subset injected into the page as #gh-block (not a #gh top-level key)."""
    return block_config(cfg)


def _name_key(fn):
    return (fn or "").strip().lower()


def _in_name_list(fn, names):
    k = _name_key(fn)
    return any(_name_key(x) == k for x in (names or []))


def _split_nameish(text):
    return re.sub(r"[-_.]+", " ", text or "")


def _ascii_term(term):
    return bool(re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9\- ]*", term or ""))


def _term_re(term):
    parts = [p for p in re.split(r"\s+", term.strip()) if p]
    body = r"\s+".join(re.escape(p) for p in parts)
    return re.compile(r"(?<![A-Za-z0-9_])" + body + r"(?![A-Za-z0-9_])", re.I)


def field_term_hit(text, term):
    """Return the matched substring, or None."""
    if text is None or term is None:
        return None
    text = str(text)
    term = str(term)
    if not text or not term:
        return None
    if _ascii_term(term):
        m = _term_re(term).search(text)
        return m.group(0) if m else None
    i = text.casefold().find(term.casefold())
    return text[i:i + len(term)] if i >= 0 else None


def _need_signal(term, cfg_block):
    want = {s.casefold() for s in cfg_block.get("need_signal") or []}
    return (term or "").casefold() in want


def _topic_free(term, field, cfg_block):
    if field != "topics":
        return False
    want = {s.casefold() for s in cfg_block.get("topic_free_terms") or []}
    return (term or "").casefold() in want


def _companion_hit(text, cfg_block):
    for s in cfg_block.get("patch_signals") or []:
        if field_term_hit(text, s):
            return True
    for pat in cfg_block.get("patch_signal_patterns") or []:
        try:
            if re.search(pat, text or "", re.I):
                return True
        except re.error:
            continue
    return False


def _iter_block_fields(repo):
    yield "description", repo.get("description") or ""
    for t in repo.get("topics") or []:
        yield "topics", str(t)


def _snip(text):
    text = text or ""
    return text if len(text) <= 240 else text[:240] + "…"


def _rule_hits(repo, cfg_block):
    """Term/phrase/name hits, ignoring allowlist and blocklist_repos."""
    hits = []
    for field, text in _iter_block_fields(repo or {}):
        if not text:
            continue
        for term in cfg_block["terms"]:
            match = field_term_hit(text, term)
            if not match and field == "topics":
                match = field_term_hit(_split_nameish(text), _split_nameish(term))
            if not match:
                continue
            if _need_signal(term, cfg_block) and not _topic_free(term, field, cfg_block) and not _companion_hit(text, cfg_block):
                # topics: free terms skip companion; also check companion on split form? keep on raw topic text
                continue
            rule = "topic_free" if (field == "topics" and _topic_free(term, field, cfg_block)) else "term"
            hits.append({"term": term, "field": field, "match": match, "snippet": _snip(text), "rule": rule})
        if field == "description":
            for pat in cfg_block.get("description_patterns") or []:
                try:
                    m = re.search(pat, text, re.I)
                except re.error:
                    continue
                if m:
                    hits.append({"term": pat, "field": "description", "match": m.group(0), "snippet": _snip(text), "rule": "description_pattern"})
    fn = (repo or {}).get("full_name") or ""
    if fn:
        hay = _split_nameish(fn)
        for term in cfg_block.get("name_terms") or []:
            match = field_term_hit(hay, _split_nameish(term))
            if match:
                hits.append({"term": term, "field": "full_name", "match": match, "snippet": fn, "rule": "name_term"})
    return hits


def block_decision(repo, cfg=None):
    """Apply blocklist_repos, then allowlist, then term/phrase/name rules."""
    cfg_block = block_config(cfg)
    fn = (repo or {}).get("full_name") or ""
    in_block = _in_name_list(fn, cfg_block.get("blocklist_repos"))
    in_allow = _in_name_list(fn, cfg_block.get("allowlist"))
    if in_block:
        hits = [{"term": "blocklist_repos", "field": "full_name", "match": fn, "snippet": fn, "rule": "blocklist_repos"}]
        # keep any other hits for the evidence file
        hits.extend(_rule_hits(repo, cfg_block))
        return {"blocked": True, "hits": hits, "allowlist_conflict": in_allow}
    if in_allow:
        return {"blocked": False, "hits": [], "allowlist_conflict": False}
    hits = _rule_hits(repo, cfg_block)
    return {"blocked": bool(hits), "hits": hits, "allowlist_conflict": False}


def block_hits(repo, cfg=None):
    """Hits that actually block this repo. Empty if allowlisted or no rule hits."""
    dec = block_decision(repo, cfg)
    return dec["hits"] if dec["blocked"] else []


def is_blocked(repo, cfg=None):
    return block_decision(repo, cfg)["blocked"]




def attach_metrics(repo, snaps, now, cfg=None):
    """给候选补 stars_delta / stars_window / stars_7d / last_complete_*。不修改传入字典，返回新 dict。"""
    cfg = cfg or _cfg()
    c = dict(repo)
    lo, hi = float(cfg.get("window_24h_min_h") or 21), float(cfg.get("window_24h_max_h") or 27)
    p24 = _stars_at(snaps, c.get("full_name") or "", now, lo, hi)
    hist = c.get("history")
    stats = complete_days(hist, now) if hist else None
    if stats is None and c.get("history_reuse"):
        ru = c["history_reuse"]
        stats = dict(
            last_complete_day=ru.get("last_complete_day") if ru.get("last_complete_day") is not None else 0,
            last_complete_ok=bool(ru.get("last_complete_ok")),
            stars_7d=ru.get("stars_7d") if ru.get("stars_7d") is not None else 0,
        )
        if ru.get("stars_7d") is None and not ru.get("last_complete_ok"):
            stats = None
    if p24:
        c["stars_delta"] = int(c.get("stars") or 0) - int(p24[0])
        c["stars_window"] = "24h_snapshot"
    elif stats and stats.get("last_complete_ok"):
        c["stars_delta"] = int(stats["last_complete_day"])
        c["stars_window"] = "last_complete_day"
    else:
        c["stars_delta"] = None
        c["stars_window"] = None
    if stats:
        c["stars_7d"] = int(stats["stars_7d"] or 0)
        c["last_complete_day"] = int(stats["last_complete_day"] or 0)
        c["last_complete_ok"] = bool(stats["last_complete_ok"])
    else:
        c["stars_7d"] = None
        c["last_complete_day"] = None
        c["last_complete_ok"] = False
    c["tags"] = tags_of(c, cfg)
    return c


def _sort_rising(rows):
    return sorted(rows, key=lambda r: (-int(r["stars_delta"]), -int(r.get("stars") or 0), (r.get("full_name") or "").lower()))


def _sort_hot(rows):
    return sorted(rows, key=lambda r: (-int(r["stars_7d"]), -int(r.get("stars") or 0), (r.get("full_name") or "").lower()))


def _sort_all(rows):
    return sorted(rows, key=lambda r: (-int(r.get("stars") or 0), (r.get("full_name") or "").lower()))


def rank_boards(candidates, snaps, now, search_failed=False, prev_all=None, cfg=None):
    """输出三榜（各最多 snapshot_top 条）。search_failed 时总榜沿用 prev_all，不写新列表。"""
    cfg = cfg or _cfg()
    top = int(cfg.get("snapshot_top") or 30)
    rising_min = int(cfg.get("rising_min_delta") or 50)
    hot_min = int(cfg.get("hot_min_7d") or 50)
    measured = [attach_metrics(c, snaps, now, cfg) for c in candidates]
    blocked = []
    seen_block = set()
    usable = []
    for c in measured:
        if excluded(c):
            continue
        dec = block_decision(c, cfg)
        if dec["blocked"]:
            fn = c.get("full_name") or ""
            key = fn.lower()
            if key not in seen_block:
                seen_block.add(key)
                blocked.append({"full_name": fn, "hits": dec["hits"], "allowlist_conflict": dec["allowlist_conflict"]})
            continue
        usable.append(c)

    rising = []
    for c in usable:
        d = c.get("stars_delta")
        if d is None or d < rising_min:
            continue
        if is_spam(c, d, now, cfg):
            continue
        rising.append(c)
    rising = _sort_rising(rising)[:top]

    hot = []
    for c in usable:
        s7 = c.get("stars_7d")
        if s7 is None or s7 < hot_min:
            continue
        hot.append(c)
    hot = _sort_hot(hot)[:top]

    def _mark(rows, name):
        out = []
        for i, r in enumerate(rows, 1):
            d = dict(r)
            d["rank"] = i
            d["board"] = name
            out.append(d)
        return out

    if search_failed:
        prev_f = [r for r in (prev_all or []) if not is_blocked(r, cfg)]
        all_board = _mark(list(prev_f)[:top], "all")
    else:
        all_board = _mark(_sort_all(usable)[:top], "all")
    rising = _mark(rising, "rising")
    hot = _mark(hot, "hot")
    return dict(rising=rising, hot=hot, all=all_board, measured=measured, blocked=blocked)
