"""同事件判定。只看标题、词表近似，不理解语义。

流程：标题 → 特征（词、实体、具名主体、地点、年份、事件类型、立场方向）
      → 冲突检查（主体 / 地点 / 年份 / 事件类型 / 立场，任一冲突即不合并）
      → 相似门槛（A：共同实体≥2+共同词≥3+J≥0.25；C：共同实体≥3且具名主体≥2+共同词≥3；
        D：同一具体事件类型+共同词≥3+J≥0.25；B：无旁证时共同词≥3+J≥0.34）。
词表在 config/merge.yaml，不含样本编号或原始标题。
"""
import functools
import re
from pathlib import Path

import yaml

_CFG_PATH = Path(__file__).resolve().parent.parent / "config" / "merge.yaml"

_STOP = {"the", "and", "for", "with", "from", "that", "this", "after", "over", "into", "new", "says", "say",
         "will", "its", "are", "has", "was", "how", "why", "what", "you", "your", "not", "but", "can", "could",
         "does", "mean", "set", "as", "at", "by", "in", "on", "of", "to", "is", "be", "it", "an", "a", "or",
         "here", "his", "her", "their", "they", "who", "when", "more", "than", "amid", "even", "all", "out",
         "about", "per", "via", "may", "might", "would", "should", "now", "just", "get", "gets", "take", "takes",
         "back", "it’s", "it's", "here's", "here’s", "across", "big", "major"}


@functools.lru_cache(maxsize=1)
def cfg():
    c = yaml.safe_load(_CFG_PATH.read_text(encoding="utf-8"))
    c["_generic"] = set(c["generic_entities"])
    c["_named"] = set(c["named"])
    c["_places"] = set(c["places"])
    c["_events"] = {k: set(v) for k, v in c["event_types"].items()}
    c["_pos"] = set(c["stance_pos"])
    c["_neg"] = set(c["stance_neg"])
    return c


def _stem(w):
    if len(w) > 4 and w.endswith("ies"):
        return w[:-3] + "y"
    if len(w) > 3 and w.endswith("s") and not w.endswith("ss") and not w.endswith("us"):
        return w[:-1]
    return w


def _norm(w, al):
    w = w.lower().replace("’", "'")
    if w.endswith("'s"):
        w = w[:-2]
    w = w.strip("'.")
    if w in al:
        return al[w]
    c = cfg()
    if w in c["_named"] or w in c["_places"] or w in c["_generic"]:
        return w
    s = _stem(w)
    return al.get(s, s)


_WORD = re.compile(r"[A-Za-z0-9][A-Za-z0-9&’'.]*")


@functools.lru_cache(maxsize=4096)
def features(title):
    c = cfg()
    al = c["aliases"]
    t = (title or "").replace("—", " ").replace("–", " ")
    raw = []
    for chunk in _WORD.findall(t):
        chunk = chunk.rstrip(".")
        if re.fullmatch(r"(?:[A-Za-z]\.){2,}", chunk + "."):   # U.S. → us
            raw.append(chunk + ".")
            continue
        raw.extend(p for p in re.split(r"-", chunk) if p)
    words = [(r, _norm(r, al)) for r in raw]
    longw = [r for r, _ in words[1:] if len(r) >= 4 and r[0].isalpha()]
    title_case = bool(longw) and sum(r[0].isupper() for r in longw) / len(longw) >= 0.6
    toks, lower_raw, named, ents = set(), set(), set(), set()
    for i, (r, n) in enumerate(words):
        lr = r.lower().replace("’", "'")
        lower_raw.add(lr)
        lower_raw.add(n)
        if n in _STOP or lr in _STOP:
            continue
        if len(n) >= 3 or n in c["_generic"]:
            toks.add(n)
        letters = re.sub(r"[^A-Za-z]", "", r)
        is_named = False
        if n in c["_named"]:
            is_named = True
        elif n in c["_generic"] or n in c["_places"]:
            is_named = False
        elif re.search(r"[a-z][A-Z]", r):                        # SpaceX / xAI / iPhone
            is_named = True
        elif len(letters) >= 2 and letters.isupper():            # AMD / AT&T
            is_named = True
        elif i > 0 and not title_case and r[0].isupper() and len(n) >= 3:
            is_named = True
        if is_named:
            named.add(n)
        if is_named or n in c["_generic"] or n in c["_places"]:
            ents.add(n)
    zh = {t[i:i + 2] for i in range(len(t) - 1) if re.fullmatch(r"[\u4e00-\u9fff]{2}", t[i:i + 2])}
    toks |= zh
    places = {n for _, n in words if n in c["_places"]}
    years = set(re.findall(r"\b(?:19|20)\d{2}\b", t))
    allw = lower_raw
    evs = {k for k, v in c["_events"].items() if allw & v}
    pos, neg = bool(allw & c["_pos"]), bool(allw & c["_neg"])
    stance = "+" if pos and not neg else "-" if neg and not pos else ""
    return dict(tok=frozenset(toks), raw=frozenset(lower_raw), named=frozenset(named), ent=frozenset(ents),
                places=frozenset(places), years=frozenset(years), events=frozenset(evs), stance=stance)


def conflict(fa, fb):
    """返回冲突原因字符串；无冲突返回 ''。"""
    na, nb = fa["named"], fb["named"]
    a_in_b = bool(na & fb["raw"])
    b_in_a = bool(nb & fa["raw"])
    if na and nb and not (na & nb) and not a_in_b and not b_in_a:
        return "主体冲突"
    if na and not nb and not a_in_b:
        return "主体不对称"
    if nb and not na and not b_in_a:
        return "主体不对称"
    if fa["places"] and fb["places"] and not (fa["places"] & fb["places"]):
        return "地点冲突"
    if fa["years"] and fb["years"] and not (fa["years"] & fb["years"]):
        return "时间冲突"
    if fa["events"] and fb["events"] and not (fa["events"] & fb["events"]):
        return "事件类型冲突"
    if {fa["stance"], fb["stance"]} == {"+", "-"}:
        return "立场相反"
    return ""


def decide(title_a, title_b):
    """返回 (是否同事件, 原因)。"""
    c = cfg()
    fa, fb = features(title_a), features(title_b)
    ta, tb = fa["tok"], fb["tok"]
    inter = len(ta & tb)
    j = inter / max(1, len(ta | tb))
    why = conflict(fa, fb)
    if why:
        return False, f"{why}(共同词{inter},J={j:.2f})"
    ec = len(fa["ent"] & fb["ent"])
    if ec >= c["a_entities_min"] and inter >= c["a_shared_min"] and j >= c["a_jaccard_min"]:
        return True, f"规则A(实体{ec},共同词{inter},J={j:.2f})"
    nc = len(fa["named"] & fb["named"])
    if ec >= c["c_entities_min"] and nc >= c["c_named_min"] and inter >= c["a_shared_min"]:
        return True, f"规则C(实体{ec},具名{nc},共同词{inter},J={j:.2f})"
    ev = (fa["events"] & fb["events"]) - {"market"}
    if ev and inter >= c["d_shared_min"] and j >= c["d_jaccard_min"]:
        return True, f"规则D(事件{'/'.join(sorted(ev))},共同词{inter},J={j:.2f})"
    if inter >= c["base_shared_min"] and j >= c["base_jaccard_min"]:
        return True, f"规则B(共同词{inter},J={j:.2f})"
    return False, f"相似不足(实体{ec},共同词{inter},J={j:.2f})"


def same(title_a, title_b):
    return decide(title_a, title_b)[0]
