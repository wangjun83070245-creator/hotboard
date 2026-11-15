"""On-disk translation cache. Values are whitelist fields only."""
import hashlib
import json
import re
from pathlib import Path

from .snapshot import atomic_write

CACHE_VALUE_FIELDS = ("title", "summary", "generated_at", "src_hash", "engine")

# Query-string form like ?token=... must not appear in public pending values.
QUERY_RE = re.compile(r"\?[^\s#]*=[^\s#]*")


def strip_query_string(text):
    if not text:
        return ""
    return QUERY_RE.sub("", str(text))


def norm_title(title):
    return re.sub(r"\s+", " ", (title or "").strip())


def src_hash(text):
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()


def news_id_key(item_id):
    return "news:id:" + str(item_id or "")


def news_title_key(title):
    return "news:title:" + norm_title(title)


def github_key(full_name):
    return "gh:" + (full_name or "").strip().lower()


def news_src_hash(title, teaser=""):
    """sha256(norm_title(title) + newline + teaser.strip())."""
    title = strip_query_string(title)
    teaser = strip_query_string(teaser).strip()
    return src_hash(norm_title(title) + "\n" + teaser)


def desc_hash(description):
    return src_hash(strip_query_string(description).strip())


def load_cache(path):
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(data, dict):
        return {}
    out = {}
    for k, v in data.items():
        if not isinstance(k, str) or not isinstance(v, dict):
            continue
        rec = {f: v[f] for f in CACHE_VALUE_FIELDS if isinstance(v.get(f), str)}
        out[k] = rec
    return out


def save_cache(path, cache):
    clean = {}
    for k, v in (cache or {}).items():
        if not isinstance(k, str) or not isinstance(v, dict):
            continue
        rec = {f: v[f] for f in CACHE_VALUE_FIELDS if isinstance(v.get(f), str)}
        if rec:
            clean[k] = rec
    atomic_write(Path(path), json.dumps(clean, ensure_ascii=False, indent=2, sort_keys=True) + "\n")
    return Path(path)


def get_news(cache, item_id, title):
    rec = (cache or {}).get(news_id_key(item_id))
    if rec:
        return rec
    return (cache or {}).get(news_title_key(title))


def put_news(cache, item_id, title, rec):
    cache[news_id_key(item_id)] = dict(rec)
    if norm_title(title):
        cache[news_title_key(title)] = dict(rec)


def get_github(cache, full_name, description=None):
    rec = (cache or {}).get(github_key(full_name))
    if not rec:
        return None
    if description is not None and rec.get("src_hash") and rec["src_hash"] != desc_hash(description):
        return None
    return rec


def put_github(cache, full_name, rec):
    cache[github_key(full_name)] = dict(rec)
