"""M2 打分：Items → Clusters。公式见 design.md §1；D 按源家族去重；股价类硬排除出 AI/芯片榜。"""
import hashlib
import math
import re
from datetime import datetime

from .common import UTC, JST, canon_url, entities, load_yaml, parse_iso, same_event, similar, tokens


def cluster_items(items, jmin=0.34, shared_min=3):
    """同 URL（规范化后）必合并；否则标题词集 Jaccard ≥ jmin 且共有 ≥ shared_min 词。"""
    cl = []
    url_index = {}
    for it in items:
        cu = canon_url(it["url"])
        tk = tokens(it["title"])
        ent = entities(it["title"])
        best = url_index.get(cu) if cu else None
        if best is None:
            for c in cl:
                if same_event(tk, c["tk"], ent, c["ent"], jmin, shared_min):
                    best = c
                    break
        if best is None:
            best = dict(members=[], urls=set(), tk=set(), ent=set())
            cl.append(best)
        best["members"].append(it)
        best["urls"].add(cu)
        best["tk"] |= tk
        best["ent"] |= ent
        if cu:
            url_index[cu] = best
    return cl


def _rx(words):
    parts = []
    for w in words:
        e = re.escape(w).replace(r"\ ", r"\s+")
        parts.append((r"(?<![A-Za-z0-9])" + e + r"(?![A-Za-z0-9])") if re.match(r"[A-Za-z0-9$]", w) else e)
    return re.compile("|".join(parts), re.I)


class FinanceRule:
    """强词 1 个，或 市场词+动作词；含发布词且无强词 → 例外。"""
    def __init__(self, cfg):
        f = cfg["finance_exclude"]
        self.strong, self.market, self.action = _rx(f["strong"]), _rx(f["market"]), _rx(f["action"])
        # 发布词按词首匹配（launch/launches/launched…）——待设计确认（问题 Q6）
        self.launch = re.compile("|".join((r"(?<![A-Za-z])" + re.escape(w) + r"[a-z]*") if re.match(r"[A-Za-z]", w)
                                          else re.escape(w) for w in f["exception_launch"]), re.I)
        self.tabs = set(f["from_tabs"])

    def explain(self, title):
        t = title or ""
        return dict(strong=[m.group(0) for m in self.strong.finditer(t)],
                    market=[m.group(0) for m in self.market.finditer(t)],
                    action=[m.group(0) for m in self.action.finditer(t)],
                    launch=[m.group(0) for m in self.launch.finditer(t)])

    def is_finance(self, title):
        x = self.explain(title)
        if x["strong"]:
            return True
        if x["launch"]:
            return False
        return bool(x["market"] and x["action"])


def categorize(main_title, all_titles, src_cats, k, cat_cfg, fin):
    cats = set(src_cats)
    text = " ".join(all_titles)
    for c, rx in cat_cfg["keywords"].items():
        if re.search(rx, text, re.I):
            cats.add(c)
    if k >= int(cat_cfg.get("major_news_min_families", 4)):
        cats.add("重大新闻")
    finance = fin.is_finance(main_title)
    if finance:
        cats -= fin.tabs
        cats.add("finance")
    return sorted(cats), finance


def score_cluster(c, now, w, cat_cfg, fin):
    by = {}
    for it in c["members"]:  # 同源只取最高
        s = it["source"]
        if s not in by or it["norm"] > by[s]["norm"]:
            by[s] = it
    contrib = sorted((it["weight"] * it["norm"] for it in by.values()), reverse=True)[: int(w["top_sources"])]
    E = contrib[0] + w["secondary_factor"] * sum(contrib[1:])
    E = min(E / w["e_norm"], 1.0)
    fams = sorted({it["family"] for it in by.values()})
    k = min(len(fams), int(w["k_cap"]))
    D = min(math.log2(1 + k) / math.log2(1 + w["k_cap"]), 1.0)
    pubs = [parse_iso(it["published"]) for it in by.values()]
    first = min(pubs)
    age = max(0.0, (now - first).total_seconds() / 3600)
    decay = 0.5 ** (age / w["half_life_h"])
    H = 100 * (w["a_eng"] * E + w["a_dup"] * D) * decay
    H = round(min(100.0, max(0.0, H)), 2)
    rep = max(by.values(), key=lambda it: (it["weight"] * it["norm"], it["source"]))
    cats, finance = categorize(rep["title"], [it["title"] for it in c["members"]],
                               {x for it in by.values() for x in it["cats"]}, len(fams), cat_cfg, fin)
    cid = hashlib.sha1(canon_url(rep["url"]).encode()).hexdigest()[:10]
    return dict(id=cid, title=rep["title"], url=rep["url"], source=rep["source"], family=rep["family"],
                members=[dict(source=it["source"], family=it["family"], title=it["title"], url=it["url"],
                              weight=it["weight"], norm=it["norm"], metrics=it["metrics"], disc=it.get("disc"))
                         for it in sorted(by.values(), key=lambda x: -x["weight"] * x["norm"])],
                families=fams, k=len(fams), E=round(E, 4), D=round(D, 4), decay=round(decay, 4),
                age_h=round(age, 2), first_pub=first.astimezone(UTC).isoformat(timespec="seconds").replace("+00:00", "Z"),
                H=H, cats=cats, finance=finance, urls=sorted(c["urls"]), tk=sorted(c["tk"]), ent=sorted(c["ent"]))


def sort_key(x):
    # H 降序 → 源家族数降序 → 最早发布更晚者优先 → id
    return (-x["H"], -x["k"], -parse_iso(x["first_pub"]).timestamp(), x["id"])


def score(items, now=None, weights=None, cat_cfg=None):
    now = now or datetime.now(UTC)
    w = weights or load_yaml("weights.yaml")
    cat_cfg = cat_cfg or load_yaml("categories.yaml")
    fin = FinanceRule(cat_cfg)
    cls = [score_cluster(c, now, w, cat_cfg, fin) for c in cluster_items(items, w["jaccard_min"], w["shared_tokens_min"])]
    # id 冲突（不同簇同主链接）时保留高分者
    cls.sort(key=sort_key)
    seen, out = set(), []
    for c in cls:
        if c["id"] in seen:
            continue
        seen.add(c["id"])
        out.append(c)
    return out


def in_tab(c, tab):
    return tab == "全部" or tab in c["cats"]
