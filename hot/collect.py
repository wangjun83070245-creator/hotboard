"""采集：config/sources.yaml → (items, source_status, request_log)。
规则：并发 ≤8、单源超时 20s；Reddit 每 2 小时 1 次、429 直接跳过不重试；
其他源 429/403/超时/5xx 最多重试 1 次、退避 ≥2 秒；UA 不冒充浏览器；不保留 raw。"""
import html
import json
import re
import socket
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

import feedparser

from .common import UTC, iso, load_yaml, parse_iso

RETRYABLE = {429, 403, 500, 502, 503, 504}
MAX_CONCURRENCY = 8
MIN_BACKOFF = 2.0


class FetchError(Exception):
    def __init__(self, msg, http=None):
        super().__init__(msg)
        self.http = http


def _one_request(url, ua, timeout):
    req = urllib.request.Request(url, headers={"User-Agent": ua, "Accept": "*/*"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.headers.get("Content-Type", ""), r.read(5_000_000)
    except urllib.error.HTTPError as e:
        raise FetchError(f"HTTP {e.code}", e.code)
    except (socket.timeout, TimeoutError):
        raise FetchError("timeout", None)
    except urllib.error.URLError as e:
        if isinstance(e.reason, (socket.timeout, TimeoutError)):
            raise FetchError("timeout", None)
        raise FetchError(f"URLError {type(e.reason).__name__}", None)


def is_reddit(src):
    return src.get("family") == "reddit"


def fetch_with_policy(src, ua, timeout, backoff, log, lock):
    """按重试规则取一个源。返回 (http, ctype, body)，失败抛 FetchError。log 记每次请求。"""
    backoff = max(MIN_BACKOFF, float(backoff))
    attempt = 0
    while True:
        attempt += 1
        t0 = time.monotonic()
        try:
            res = _one_request(src["url"], ua, timeout)
            with lock:
                log.append(dict(source=src["name"], attempt=attempt, t=round(t0, 3), http=res[0], err=None))
            return res
        except FetchError as e:
            with lock:
                log.append(dict(source=src["name"], attempt=attempt, t=round(t0, 3), http=e.http, err=str(e)))
            if is_reddit(src) and e.http == 429:
                raise FetchError("429 限流，本轮跳过（Reddit 不重试）", 429)
            retryable = e.http in RETRYABLE or str(e) == "timeout"
            if attempt >= 2 or not retryable:
                raise
            time.sleep(backoff)


def _rss_items(body, kind):
    f = feedparser.parse(body)
    if not f.entries:
        raise FetchError("不是 RSS 或为空（可能是 WAF 页）")
    out = []
    entries = f.entries[:40]
    for i, e in enumerate(entries):
        t = html.unescape(e.get("title", "") or "").strip()
        pub = None
        for k in ("published_parsed", "updated_parsed"):
            if e.get(k):
                pub = datetime(*e[k][:6], tzinfo=UTC)
                break
        m = {"position": i + 1}
        rel = 1
        if kind == "gnews":
            t = re.sub(r"\s+-\s+[^-]+$", "", t)
            rel = max(1, len(re.findall(r"<li>", e.get("summary", "") or "")))
            m["related"] = rel
        n = len(entries)
        out.append(dict(title=t, url=e.get("link", ""), pub=pub, metrics=m,
                        _eng=(n - i) / n * (1 + 0.15 * (rel - 1)), disc=None))
    return out


def parse(kind, body, ctype=""):
    if kind in ("algolia", "lobsters", "hf"):
        try:
            data = json.loads(body)
        except ValueError:
            raise FetchError("返回不是 JSON（可能是 WAF 页）")
    out = []
    if kind == "algolia":
        for h in data.get("hits", []):
            disc = f"https://news.ycombinator.com/item?id={h['objectID']}"
            p, c = h.get("points") or 0, h.get("num_comments") or 0
            out.append(dict(title=h.get("title") or "", url=h.get("url") or disc, pub=parse_iso(h.get("created_at")),
                            metrics={"points": p, "comments": c}, _eng=p + 2 * c, disc=disc))
    elif kind == "lobsters":
        for h in data:
            s, c = h.get("score") or 0, h.get("comment_count") or 0
            out.append(dict(title=h.get("title") or "", url=h.get("url") or h.get("short_id_url"),
                            pub=parse_iso(h.get("created_at")), metrics={"score": s, "comments": c},
                            _eng=s + 2 * c, disc=h.get("short_id_url")))
    elif kind == "hf":
        for d in data[:40]:
            p = d.get("paper", {}) or {}
            up = p.get("upvotes", 0) or 0
            out.append(dict(title=d.get("title") or p.get("title") or "", url=f"https://huggingface.co/papers/{p.get('id')}",
                            pub=parse_iso(d.get("publishedAt")), metrics={"upvotes": up}, _eng=up, disc=None))
    else:
        out = _rss_items(body, kind)
    return out


def due(src, now):
    every = int(src.get("every_hours", 1) or 1)
    return now.astimezone(UTC).hour % every == 0


def collect(now=None, sources=None, cfg=None, timeout=None, backoff=None):
    """返回 items, status, log。任一源失败不抛异常。"""
    now = now or datetime.now(UTC)
    cfg = cfg or load_yaml("weights.yaml")
    sources = sources if sources is not None else load_yaml("sources.yaml")["sources"]
    ua = cfg["user_agent"]
    assert not ua.lower().startswith("mozilla"), "UA 不能冒充浏览器"
    timeout = timeout if timeout is not None else cfg["timeout_s"]
    backoff = backoff if backoff is not None else cfg["retry_backoff_s"]
    log, lock = [], threading.Lock()
    max_age = timedelta(hours=cfg["max_age_h"])

    def run(src):
        t0 = time.monotonic()
        st = dict(name=src["name"], family=src["family"], ok=False, http=None, err=None, n=0, ms=0, skipped=False)
        if not due(src, now):
            st.update(skipped=True, err=f"每 {src.get('every_hours')} 小时抓 1 次，本轮不抓")
            return st, []
        try:
            http, ctype, body = fetch_with_policy(src, ua, timeout, backoff, log, lock)
            st["http"] = http
            raw_items = parse(src["kind"], body, ctype)
            items = []
            for it in raw_items:
                if not it["title"] or not it["url"]:
                    continue
                pub = it["pub"] or now
                if pub > now:          # 未来时间截到 now
                    pub = now
                if now - pub > max_age:  # 丢弃 >48h
                    continue
                it["pub"] = pub
                items.append(it)
            # 源内百分位
            order = sorted(range(len(items)), key=lambda i: -items[i]["_eng"])
            N = len(items)
            for r, i in enumerate(order):
                items[i]["norm"] = round(1 - r / N, 4)
            out = []
            for it in items:
                out.append(dict(title=it["title"], url=it["url"], published=iso(it["pub"]), source=src["name"],
                                family=src["family"], weight=float(src["weight"]), cats=list(src.get("cats") or []),
                                metrics=it["metrics"], norm=it["norm"], disc=it["disc"]))
            st.update(ok=True, n=len(out))
            return st, out
        except FetchError as e:
            st.update(http=e.http, err=str(e)[:120])
        except Exception as e:  # 解析异常等，不影响其他源
            st.update(err=f"{type(e).__name__}: {str(e)[:100]}")
        finally:
            st["ms"] = int((time.monotonic() - t0) * 1000)
        return st, []

    with ThreadPoolExecutor(min(MAX_CONCURRENCY, int(cfg.get("concurrency", 8)))) as ex:
        res = list(ex.map(run, sources))
    items = [o for _, out in res for o in out]
    status = [s for s, _ in res]
    return items, status, log
