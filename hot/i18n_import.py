"""Check and merge a translation staging file into the committed cache.

Incoming JSON is untrusted: only parsed, never executed. Types, lengths,
and field names are validated. Output paths must stay inside the project.
"""
import argparse
import hashlib
import json
import re
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

from .common import (
    JST, ROOT, UnsafePath, parse_iso, validate_allowed_write_path,
    validate_project_path,
)
from .i18n_cache import CACHE_VALUE_FIELDS, load_cache, news_title_key, save_cache
from .i18n_quality import i18n_cfg, quality_ok
from .snapshot import atomic_write

TEAM_ENGINE = "zh-v1"
STAGING_META_FIELDS = (
    "pending_generated_at", "source", "translated_at", "engine",
    "version", "generated_at",
)
STAGING_ITEM_FIELDS = ("key", "title_key", "title", "summary", "src_hash", "generated_at", "no_desc", "name", "full_name")
NEWS_TITLE_MIN, NEWS_TITLE_MAX = 4, 60
SUMMARY_MIN, SUMMARY_MAX = 1, 50
HARD_STR_MAX = 2000
STAGING_MAX_BYTES = 2_000_000
MERGED_MAX_BYTES = 1_000_000
NEW_ITEMS_MAX = 300
# Keys missing from the latest pending list are dropped once their
# translation is this old. Each 3-hourly round adds about 200 keys
# (news:id + news:title per item, ~80 KB); a 336 h window would need
# several MB, far over MERGED_MAX_BYTES, so keep about one day.
NEWS_TTL_HOURS = 24
KEY_NEWS_ID = re.compile(r"^news:id:.+$")
KEY_NEWS_TITLE = re.compile(r"^news:title:.+$")
KEY_GITHUB = re.compile(r"^gh:[a-z0-9._-]+/[a-z0-9._-]+$")
URL_RE = re.compile(r"https?://|\bwww\.", re.I)
EMAIL_RE = re.compile(r"[A-Za-z0-9._%+\-]+@[A-Za-z0-9.\-]+\.[A-Za-z]{2,}")
SECRET_WORD_RE = re.compile(r"(?i)\b(token|key|password)\b")
CTRL_RE = re.compile(
    r"[\x00-\x08\x0b-\x1f\x7f-\x9f\u061c\u200e\u200f\u2028\u2029\u202a-\u202e\u2066-\u2069\ufeff]"
)  # C0 except tab/newline; DEL; C1; ALM/LRM/RLM; line/para sep; bidi controls; BOM. U+200D (ZWJ) allowed.
TEXT_FIELDS = ("title", "summary", "title_key")


def normalize_tabs(text):
    """Tab becomes one space. Applied once, when a staging item is read, so
    --check and --merge (which reuses the checked records) see the same text."""
    return text.replace("\t", " ") if isinstance(text, str) else text

# Phrases the import checker rejects, escaped so public source stays clean.
_FORBIDDEN_PHRASES = (
    "\u7ffb\u8bd1\u5982\u4e0b",
    "\u4f5c\u4e3a AI",
    "\u6728\u6728",
    "\u8001\u9a6c\u56e2\u961f",
    "\u5976\u86d9",
)


class ImportError_(Exception):
    pass


def default_rejected_path(staging):
    """foo.json -> foo.rejected.json in the same directory."""
    p = Path(staging)
    name = p.name
    if name.lower().endswith(".json"):
        name = name[:-5]
    return p.with_name(name + ".rejected.json")


def _now_iso(now=None):
    t = now or datetime.now(timezone.utc)
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return t.astimezone(JST).isoformat(timespec="seconds")


def _is_news_key(key):
    return bool(KEY_NEWS_ID.match(key) or KEY_NEWS_TITLE.match(key))


def _is_gh_key(key):
    return bool(KEY_GITHUB.match(key or ""))


def _key_ok(key):
    return isinstance(key, str) and (_is_news_key(key) or _is_gh_key(key))


def _digits(text):
    return re.findall(r"\d+", text or "")


def load_pending(path):
    if not path:
        return {}, {}
    p = Path(path)
    try:
        data = json.loads(p.read_text(encoding="utf-8"))
    except Exception:
        return {}, {}
    if not isinstance(data, dict):
        return {}, {}
    by_key = {}
    for bucket in ("news", "github"):
        rows = data.get(bucket)
        if not isinstance(rows, list):
            continue
        for row in rows:
            if not isinstance(row, dict):
                continue
            key = row.get("key")
            if isinstance(key, str) and key:
                by_key[key] = row
            tkey = row.get("title_key")
            if isinstance(tkey, str) and tkey:
                by_key[tkey] = row
    return data, by_key


def _file_level_reject(reason, raw_note=""):
    rec = {"key": "", "reasons": [reason]}
    if raw_note:
        rec["note"] = raw_note[:200]
    return rec


def _read_staging(path):
    p = Path(path)
    try:
        raw = p.read_bytes()
    except OSError as e:
        raise ImportError_(f"cannot read staging: {type(e).__name__}") from e
    if len(raw) > STAGING_MAX_BYTES:
        return None, [_file_level_reject("1: staging file too large")]
    try:
        data = json.loads(raw.decode("utf-8"))
    except Exception:
        return None, [_file_level_reject("1: JSON does not parse")]
    if not isinstance(data, dict):
        return None, [_file_level_reject("1: staging root must be an object")]
    meta = data.get("meta")
    items = data.get("items")
    if not isinstance(meta, dict) or not isinstance(items, list):
        return None, [_file_level_reject("1: structure must have meta object and items list")]
    extra_top = set(data) - {"meta", "items"}
    if extra_top:
        return None, [_file_level_reject("1: unknown top-level fields")]
    extra_meta = set(meta) - set(STAGING_META_FIELDS)
    if extra_meta:
        return None, [_file_level_reject("1: unknown meta fields")]
    if "version" in meta and meta.get("version") != 1:
        return None, [_file_level_reject("1: meta.version must be 1")]
    src = meta.get("source")
    if src is not None and not (isinstance(src, str) and src.strip() and len(src) <= 40):
        return None, [_file_level_reject("1: meta.source is invalid")]
    return data, []


def _check_item(item, pending_by_key, cfg):
    reasons = []
    if not isinstance(item, dict):
        return ["1: item is not an object"], {}
    extra = set(item) - set(STAGING_ITEM_FIELDS)
    if extra:
        reasons.append("1: unknown fields")
    rec = {}
    required = {"key", "src_hash", "summary"}
    for f in STAGING_ITEM_FIELDS:
        if f not in item:
            if f in required:
                reasons.append(f"1: missing field {f}")
            elif f == "no_desc":
                rec[f] = False
            else:
                rec[f] = ""
            continue
        v = item.get(f)
        if f == "no_desc":
            if isinstance(v, bool):
                rec[f] = v
            elif isinstance(v, str) and v.strip().lower() in {"true", "false", "1", "0", "yes", "no"}:
                rec[f] = v.strip().lower() in {"true", "1", "yes"}
            else:
                reasons.append("1: field no_desc must be a boolean")
            continue
        if not isinstance(v, str):
            reasons.append(f"1: field {f} must be a string")
            continue
        if len(v) > HARD_STR_MAX:
            reasons.append(f"1: field {f} is too long")
            continue
        rec[f] = normalize_tabs(v) if f in TEXT_FIELDS else v
    key = rec.get("key") or ""
    if not _key_ok(key):
        reasons.append("1: key format is invalid")
        return reasons, rec
    is_news = _is_news_key(key)
    is_gh = _is_gh_key(key)

    pending = pending_by_key.get(key)
    src_hash = rec.get("src_hash") or ""
    if not pending:
        reasons.append("2: key is not in the pending list")
    elif (pending.get("src_hash") or "") != src_hash:
        reasons.append("2: src_hash does not match the pending list")

    title = rec.get("title") or ""
    summary = rec.get("summary") or ""
    if is_gh and title:
        reasons.append("4: github item must not have a title")
    if is_news:
        if not quality_ok(title, cfg):
            reasons.append("3: title fails the quality gate")
        if not quality_ok(summary, cfg):
            reasons.append("3: summary fails the quality gate")
        n_title, n_sum = len(title), len(summary)
        if not (NEWS_TITLE_MIN <= n_title <= NEWS_TITLE_MAX):
            reasons.append("4: title length must be 4-60")
        if not (SUMMARY_MIN <= n_sum <= SUMMARY_MAX):
            reasons.append("4: summary length must be 1-50")
    elif is_gh:
        if not quality_ok(summary, cfg):
            reasons.append("3: summary fails the quality gate")
        if not (SUMMARY_MIN <= len(summary) <= SUMMARY_MAX):
            reasons.append("4: summary length must be 1-50")

    combined = title + "\n" + summary
    if CTRL_RE.search(title or "") or CTRL_RE.search(summary or ""):
        reasons.append("1: translation contains a control character")
    tkey_raw = rec.get("title_key") or ""
    if isinstance(tkey_raw, str) and CTRL_RE.search(tkey_raw):
        reasons.append("1: title_key contains a control character")
    if URL_RE.search(combined):
        reasons.append("5: translation contains a URL")
    if EMAIL_RE.search(combined):
        reasons.append("5: translation contains an email")
    if SECRET_WORD_RE.search(combined):
        reasons.append("5: translation contains a secret-like word")
    for phrase in _FORBIDDEN_PHRASES:
        if phrase and phrase in combined:
            reasons.append("5: translation contains a forbidden phrase")
            break

    if pending:
        # Rule 6 checks only the text that is translated: the news title
        # (teaser digits are not required) and the GitHub description.
        # no_desc repos have no description, so there is nothing to check.
        if is_news:
            source = pending.get("title") or ""
        elif pending.get("no_desc"):
            source = ""
        else:
            source = pending.get("description") or ""
        dest = title + summary
        for num in _digits(source):
            if num not in dest:
                reasons.append("6: source digits are missing in the translation")
                break
    return reasons, rec


def check_staging(staging_path, pending_path, cfg=None, cache=None):
    cfg = i18n_cfg(cfg)
    data, file_rejects = _read_staging(staging_path)
    accepted, rejected = [], list(file_rejects)
    if data is None:
        return {"accepted": accepted, "rejected": rejected, "meta": {},
                "new_count": 0, "item7": False}
    _, pending_by_key = load_pending(pending_path)
    seen = set()
    for item in data.get("items") or []:
        reasons, rec = _check_item(item, pending_by_key, cfg)
        key = rec.get("key") or ""
        if key and key in seen:
            reasons = list(reasons) + ["1: duplicate key"]
        if key:
            seen.add(key)
        if reasons:
            rejected.append({"key": key, "reasons": reasons})
        else:
            accepted.append(rec)
    item7 = False
    existing = cache if cache is not None else {}
    new_count = sum(1 for rec in accepted if rec["key"] not in existing)
    if new_count > NEW_ITEMS_MAX:
        item7 = True
        rejected.append(_file_level_reject(
            f"7: new items this round exceed {NEW_ITEMS_MAX} ({new_count})"
        ))
        for rec in accepted:
            rejected.append({"key": rec.get("key") or "", "reasons": [
                f"7: new items this round exceed {NEW_ITEMS_MAX}"
            ]})
        accepted = []
    return {
        "accepted": accepted,
        "rejected": rejected,
        "meta": data.get("meta") or {},
        "new_count": new_count,
        "item7": item7,
    }


def _is_stale(generated_at, now):
    """True when generated_at is at least NEWS_TTL_HOURS old."""
    at = parse_iso(generated_at)
    if at is None:
        return True
    if at.tzinfo is None:
        at = at.replace(tzinfo=timezone.utc)
    ref = now
    if ref.tzinfo is None:
        ref = ref.replace(tzinfo=timezone.utc)
    return (ref - at) >= timedelta(hours=NEWS_TTL_HOURS)


def _cleanup(cache, pending_by_key, now):
    """Drop keys missing from the latest list after NEWS_TTL_HOURS;
    also drop gh: keys that are in the list but whose src_hash no longer matches.
    An empty or unreadable list prunes nothing (it would look like every key
    had left the board).
    """
    removed = []
    if not pending_by_key:
        return removed
    for key in list(cache):
        rec = cache.get(key) or {}
        if key.startswith("news:") or key.startswith("gh:"):
            if key not in pending_by_key and _is_stale(rec.get("generated_at"), now):
                removed.append(key)
                del cache[key]
                continue
        if key.startswith("gh:"):
            pend = pending_by_key.get(key)
            if pend and (pend.get("src_hash") or "") != (rec.get("src_hash") or ""):
                if key not in removed:
                    removed.append(key)
                    del cache[key]
    return removed


def _build_record(item, now_iso):
    rec = {
        "title": item.get("title") or "",
        "summary": item.get("summary") or "",
        "generated_at": item.get("generated_at") or now_iso,
        "src_hash": item.get("src_hash") or "",
        "engine": TEAM_ENGINE,
    }
    if _is_gh_key(item.get("key") or ""):
        rec.pop("title", None)
        # keep only whitelist fields that apply; title may stay empty string
        rec = {k: rec[k] for k in CACHE_VALUE_FIELDS if k in rec and isinstance(rec[k], str)}
        rec.pop("title", None)
        rec["engine"] = TEAM_ENGINE
    return rec



def _fallback_title_key(item, pending_by_key):
    """news:title: key for a news item.

    Adopt staging title_key only when it is exactly equal to the pending
    item's title_key; otherwise always use the pending value (or, if that
    is empty, derive from the pending title).
    """
    if not _is_news_id_key(item.get("key") or ""):
        return ""
    pend = pending_by_key.get(item.get("key") or "") or {}
    staging_key = normalize_tabs(item.get("title_key") or "").strip()
    pending_key = normalize_tabs(pend.get("title_key") or "").strip()
    if staging_key and staging_key == pending_key:
        tkey = staging_key
    else:
        tkey = pending_key
        if not (tkey and KEY_NEWS_TITLE.match(tkey)):
            title = pend.get("title") or ""
            tkey = news_title_key(title) if title else ""
    if not tkey or not KEY_NEWS_TITLE.match(tkey):
        return ""
    if CTRL_RE.search(tkey):
        return ""
    rest = tkey[len("news:title:"):]
    if not rest.strip():
        return ""
    return tkey


def _is_news_id_key(key):
    return bool(KEY_NEWS_ID.match(key or ""))


def merge_staging(staging_path, pending_path, cache_path, now=None, cfg=None, max_bytes=MERGED_MAX_BYTES):
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    now_iso = _now_iso(now)
    cache = load_cache(cache_path)
    before_keys = set(cache)
    result = check_staging(staging_path, pending_path, cfg=cfg, cache=cache)
    if result["item7"]:
        return {"ok": False, "reason": "item7", "result": result, "added": 0,
                "updated": 0, "cleaned": 0, "samples": [], "cache": cache}
    _, pending_by_key = load_pending(pending_path)
    added, updated = 0, 0
    changed_keys = []
    for item in result["accepted"]:
        key = item["key"]
        rec = _build_record(item, now_iso)
        prev = cache.get(key)
        if prev is None:
            added += 1
            cache[key] = rec
            changed_keys.append(key)
        else:
            same = all(prev.get(f) == rec.get(f) for f in ("title", "summary", "src_hash") if f in rec)
            cache[key] = rec
            if not same:
                updated += 1
                changed_keys.append(key)
        # Also write news:title: fallback. Not counted in added/updated (same item).
        tkey = _fallback_title_key(item, pending_by_key)
        if tkey:
            cache[tkey] = dict(rec)
    cleaned_keys = _cleanup(cache, pending_by_key, now)
    raw = json.dumps(cache, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if len(raw.encode("utf-8")) > int(max_bytes):
        result["item7"] = True
        result["rejected"].append(_file_level_reject("7: merged cache would exceed 1000000 bytes"))
        return {"ok": False, "reason": "item7", "result": result, "added": 0,
                "updated": 0, "cleaned": 0, "samples": [], "cache": load_cache(cache_path)}
    save_cache(cache_path, cache)
    samples = _sample_items(changed_keys, result["accepted"], pending_by_key, cache, n=5)
    return {
        "ok": True,
        "reason": "",
        "result": result,
        "added": added,
        "updated": updated,
        "cleaned": len(cleaned_keys),
        "cleaned_keys": cleaned_keys,
        "samples": samples,
        "cache": cache,
        "before": len(before_keys),
        "after": len(cache),
    }


def _sample_items(changed_keys, accepted, pending_by_key, cache, n=5):
    if not changed_keys:
        return []
    seed = hashlib.sha256(("\n".join(sorted(changed_keys))).encode("utf-8")).hexdigest()
    order = sorted(changed_keys, key=lambda k: hashlib.sha256((seed + k).encode("utf-8")).hexdigest())
    by_key = {it["key"]: it for it in accepted}
    out = []
    for key in order[:n]:
        rec = cache.get(key) or {}
        pend = pending_by_key.get(key) or {}
        out.append({
            "key": key,
            "source_title": pend.get("title") or "",
            "source_teaser": pend.get("teaser") or "",
            "source_description": pend.get("description") or "",
            "title": rec.get("title") or "",
            "summary": rec.get("summary") or "",
        })
    return out


def format_diff(merge_result):
    lines = [
        "i18n cache merge summary",
        "added: {}".format(merge_result.get("added") or 0),
        "updated: {}".format(merge_result.get("updated") or 0),
        "cleaned: {}".format(merge_result.get("cleaned") or 0),
        "rejected: {}".format(len((merge_result.get("result") or {}).get("rejected") or [])),
        "samples:",
    ]
    for s in merge_result.get("samples") or []:
        lines.append("- key: " + s["key"])
        if s.get("source_title") or s.get("source_teaser"):
            lines.append("  source title: " + (s.get("source_title") or ""))
            if s.get("source_teaser"):
                lines.append("  source teaser: " + s["source_teaser"])
        if s.get("source_description"):
            lines.append("  source description: " + s["source_description"])
        if s.get("title"):
            lines.append("  title: " + s["title"])
        lines.append("  summary: " + (s.get("summary") or ""))
    return "\n".join(lines) + "\n"


def write_rejected(path, rejected):
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(dest, json.dumps(rejected, ensure_ascii=False, indent=2) + "\n")
    return dest


def write_diff(path, text):
    dest = Path(path)
    dest.parent.mkdir(parents=True, exist_ok=True)
    atomic_write(dest, text)
    return dest


def _resolve_cli_path(value, root):
    return validate_project_path(value, root=root)


def main(argv=None, root=None):
    root = Path(root) if root is not None else ROOT
    ap = argparse.ArgumentParser(prog="hot.i18n_import")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--check", metavar="STAGING")
    g.add_argument("--merge", metavar="STAGING")
    ap.add_argument("--pending", default=None, help="this round's i18n_pending.json")
    ap.add_argument("--cache", default=None, help="cache file for --merge (and new-count for --check)")
    ap.add_argument("--rejected", default=None)
    ap.add_argument("--diff", default=None)
    ap.add_argument("--now", default=None)
    a = ap.parse_args(argv)
    try:
        staging = _resolve_cli_path(a.check or a.merge, root)
        pending = _resolve_cli_path(a.pending, root) if a.pending else None
        cache_path = _resolve_cli_path(a.cache, root) if a.cache else (root / "data" / "i18n_cache.json")
        if a.cache is None and a.merge:
            cache_path = _resolve_cli_path(root / "data" / "i18n_cache.json", root)
        rejected_path = a.rejected
        if rejected_path is None:
            rejected_path = default_rejected_path(staging)
        rejected_path = validate_allowed_write_path(rejected_path, root=root)
        if a.cache:
            cache_path = validate_allowed_write_path(a.cache, root=root) if a.merge else cache_path
        elif a.merge:
            cache_path = validate_allowed_write_path(root / "data" / "i18n_cache.json", root=root)
    except UnsafePath as e:
        print("unsafe path: " + str(e), file=sys.stderr)
        return 2
    if a.check:
        cache = load_cache(cache_path) if cache_path and Path(cache_path).is_file() else {}
        result = check_staging(staging, pending, cache=cache)
        write_rejected(rejected_path, result["rejected"])
        n_ok, n_bad = len(result["accepted"]), len(result["rejected"])
        print(f"check: accepted {n_ok}, rejected {n_bad}")
        return 0 if n_bad == 0 else 1
    now = parse_iso(a.now) if a.now else datetime.now(timezone.utc)
    merged = merge_staging(staging, pending, cache_path, now=now)
    write_rejected(rejected_path, (merged["result"] or {}).get("rejected") or [])
    if not merged["ok"]:
        print("merge refused: " + (merged.get("reason") or "item7"), file=sys.stderr)
        return 1
    text = format_diff(merged)
    diff_path = a.diff
    if diff_path is None:
        # keep next to staging, but only if that lands under data/ or selftest/
        p = Path(staging)
        name = p.name
        if name.lower().endswith(".json"):
            name = name[:-5]
        diff_path = p.with_name(name + ".diff.md")
    try:
        diff_path = validate_allowed_write_path(diff_path, root=root)
    except UnsafePath as e:
        print("unsafe path: " + str(e), file=sys.stderr)
        return 2
    write_diff(diff_path, text)
    sys.stdout.write(text)
    return 0 if not (merged["result"] or {}).get("rejected") else 1


if __name__ == "__main__":
    sys.exit(main())
