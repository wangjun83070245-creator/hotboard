"""公共：路径、配置、时间、URL 规范化、分词。"""
import re
from datetime import datetime, timezone, timedelta
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode
import yaml

ROOT = Path(__file__).resolve().parent.parent
JST = timezone(timedelta(hours=9))
UTC = timezone.utc


def load_yaml(name, cfg_dir=None):
    d = Path(cfg_dir) if cfg_dir else ROOT / "config"
    with open(d / name, encoding="utf-8") as f:
        return yaml.safe_load(f)


def iso(dt):
    return dt.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z")


def parse_iso(s):
    if not s:
        return None
    try:
        d = datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except ValueError:
        return None
    return d if d.tzinfo else d.replace(tzinfo=UTC)


_DROP_Q = re.compile(r"^(utm_.*|fbclid|gclid|mc_cid|mc_eid|ref|ref_src|cmpid|ocid)$", re.I)


def canon_url(u):
    """URL 规范化：去 utm 等跟踪参数、去 www、去尾斜杠、去 #片段、host 小写、http/https 统一。"""
    if not u:
        return ""
    try:
        p = urlsplit(u.strip())
    except ValueError:
        return u.strip().lower()
    host = (p.hostname or "").lower()
    if host.startswith("www."):
        host = host[4:]
    if p.port and p.port not in (80, 443):
        host = f"{host}:{p.port}"
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not _DROP_Q.match(k)]
    path = p.path.rstrip("/")
    return urlunsplit(("", host, path, urlencode(sorted(q)), "")).lstrip("/")


_STOP = {"the", "and", "for", "with", "from", "that", "this", "after", "over", "into", "new", "says",
         "will", "its", "are", "has", "was", "how", "why", "what", "you", "your", "not", "but", "can"}


def tokens(t):
    t = (t or "").lower()
    en = set(re.findall(r"[a-z0-9]{3,}", t)) - _STOP
    zh = {t[i:i + 2] for i in range(len(t) - 1) if re.fullmatch(r"[\u4e00-\u9fff]{2}", t[i:i + 2])}
    return en | zh


def similar(tk_a, tk_b, jmin=0.34, shared_min=3):
    inter = len(tk_a & tk_b)
    return inter >= shared_min and inter / max(1, len(tk_a | tk_b)) >= jmin


_ENT_STOP = {"The", "A", "An", "And", "Or", "But", "For", "With", "From", "That", "This", "After", "Over", "Into", "New",
             "Says", "Will", "Its", "Are", "Has", "How", "Why", "What", "When", "Who", "As", "At", "By", "In", "On", "Of",
             "To", "Up", "Is", "Be", "It", "Not", "Can", "Could", "May", "More", "Most", "Than", "Amid", "Over", "Out",
             "Report", "Reports", "Breaking", "Live", "Update", "Updates", "Exclusive", "Analysis", "Opinion", "Here", "Now"}


def entities(t):
    """主体实体近似（Q3）：大写开头/全大写的英文词（去常见虚词）、含数字的型号、中文标题里的英文名。
    不理解语义；中文专名无法可靠抽取 → 返回空集时由调用方按“无实体信息”处理。"""
    t = t or ""
    ents = set()
    for w in re.findall(r"[A-Za-z][A-Za-z0-9&.\-]*", t):
        w2 = w.strip(".-")
        if len(w2) < 2 or w2 in _ENT_STOP:
            continue
        if w2[0].isupper() or any(ch.isdigit() for ch in w2):
            ents.add(w2.lower())
    return ents


def same_event(tk_a, tk_b, ent_a, ent_b, jmin=0.34, shared_min=3):
    """标题相似 且 主体实体至少 1 个相同（两边都没有可抽取实体时只看相似度）。"""
    if not similar(tk_a, tk_b, jmin, shared_min):
        return False
    if ent_a and ent_b:
        return bool(ent_a & ent_b)
    return True
