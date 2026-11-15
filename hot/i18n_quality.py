"""Chinese quality gate and “already Chinese” skip rules."""
import re

from .common import load_yaml

HAN = re.compile(r"[\u4e00-\u9fff]")
KANA = re.compile(r"[\u3040-\u30ff]")
LATIN = re.compile(r"[A-Za-z]")
URL_RE = re.compile(r"https?://\S+", re.I)


def i18n_cfg(cfg=None):
    return cfg if cfg is not None else load_yaml("i18n.yaml")


def proper_nouns(cfg=None):
    return list((i18n_cfg(cfg).get("proper_nouns") or []))


def _noun_re(words):
    parts = []
    for w in words:
        w = (w or "").strip()
        if not w:
            continue
        parts.append(re.escape(w))
    if not parts:
        return None
    parts.sort(key=len, reverse=True)
    return re.compile(r"(?<![A-Za-z0-9_])(?:" + "|".join(parts) + r")(?![A-Za-z0-9_])", re.I)


def preprocess(text, cfg=None):
    s = "" if text is None else str(text)
    s = URL_RE.sub(" ", s)
    rx = _noun_re(proper_nouns(cfg))
    if rx:
        s = rx.sub(" ", s)
    return s


def has_kana(text):
    return bool(KANA.search(text or ""))


def already_chinese(text, family=None, cfg=None):
    """Source text that must not be sent to en→zh: has Han, no kana, family is not nhk."""
    s = (text or "").strip()
    if not s:
        return False
    if (family or "").lower() == "nhk" or has_kana(s):
        return False
    return bool(HAN.search(s))


def quality_ok(text, cfg=None):
    """Return True if text may appear as a Chinese title, summary, or intro."""
    s = "" if text is None else str(text)
    if not s.strip():
        return False
    if has_kana(s):
        return False
    prep = preprocess(s, cfg)
    c = len(HAN.findall(prep))
    letters = LATIN.findall(prep)
    l = len(letters)
    t = c + l
    if t == 0:
        return True
    if (c / t) < 0.30 and (l / t) > 0.50:
        return False
    if l >= 12 and c == 0:
        return False
    return True


def clip_chars(text, n):
    chars = list(text or "")
    n = int(n)
    if len(chars) <= n:
        return "".join(chars)
    return "".join(chars[:n])
