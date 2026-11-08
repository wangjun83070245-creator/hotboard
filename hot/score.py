"""打分：Items → Clusters；D 按源家族去重；股价类硬排除出 AI/芯片榜。"""
import hashlib
import math
import re
from datetime import datetime

from .common import UTC, JST, canon_url, load_yaml, parse_iso
from .match import conflict, features, same


def cluster_items(items, jmin=None, shared_min=None):
    """聚类：
    1) 规范化 URL 相同必合并（并查集，与输入顺序无关）；
    2) 各 URL 组按确定键（规范 URL、标题）排序后依次归簇——输入顺序打乱结果不变；
    3) 成员一致性：只和簇里每个成员的标题逐一比较（不用簇内词/实体并集），
       与任一成员冲突（主体/地点/时间/事件类型/立场）即不能入簇，且须与过半成员判为同事件。
    jmin/shared_min 保留参数位兼容旧调用，实际门槛见 config/merge.yaml。"""
    groups = {}
    for idx, it in enumerate(items):
        cu = canon_url(it["url"]) or f"__nourl__{it.get('title','')}__{it.get('source','')}__{idx}"
        groups.setdefault(cu, []).append(it)
    def gkey(kv):
        cu, mem = kv
        return (cu.startswith("__nourl__"), cu, min(m.get("title", "") for m in mem))
    cl = []
    for cu, mem in sorted(groups.items(), key=gkey):
        titles = sorted({m.get("title", "") for m in mem})
        best, best_score = None, 0.0
        for c in cl:
            ok_conflict = True
            hits = 0
            for ct in c["titles"]:
                hit = False
                for t in titles:
                    if conflict(features(t), features(ct)):
                        ok_conflict = False
                        break
                    hit = hit or same(t, ct)
                if not ok_conflict:
                    break
                hits += hit
            if not ok_conflict:
                continue
            need = (len(c["titles"]) + 1) // 2
            frac = hits / len(c["titles"])
            if hits >= max(1, need) and frac > best_score:
                best, best_score = c, frac
        if best is None:
            best = dict(members=[], urls=set(), titles=[], tk=set(), ent=set())
            cl.append(best)
        best["members"].extend(sorted(mem, key=lambda m: (m.get("source", ""), m.get("title", ""))))
        if not cu.startswith("__nourl__"):
            best["urls"].add(cu)
        for t in titles:
            if t not in best["titles"]:
                best["titles"].append(t)
            best["tk"] |= set(features(t)["tok"])
            best["ent"] |= set(features(t)["ent"])
    for c in cl:
        c["members"].sort(key=lambda m: (m.get("source", ""), canon_url(m.get("url", "")), m.get("title", "")))
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
        # 发布词按词首匹配（launch/launches/launched…）
        self.launch = re.compile("|".join((r"(?<![A-Za-z])" + re.escape(w) + r"[a-z]*") if re.match(r"[A-Za-z]", w)
                                          else re.escape(w) for w in f["exception_launch"]), re.I)
        self.tabs = set(f["from_tabs"])
        self.strong_x = [re.compile(r, re.I) for r in f.get("strong_regex", [])] + [re.compile(r) for r in f.get("strong_regex_cs", [])]
        self.action_x = [re.compile(r, re.I) for r in f.get("action_regex", [])]

    def explain(self, title):
        t = title or ""
        return dict(strong=[m.group(0) for m in self.strong.finditer(t)] + [m.group(0) for r in self.strong_x for m in r.finditer(t)],
                    market=[m.group(0) for m in self.market.finditer(t)],
                    action=[m.group(0) for m in self.action.finditer(t)] + [m.group(0) for r in self.action_x for m in r.finditer(t)],
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
        if s not in by or (it["norm"], it.get("url", "")) > (by[s]["norm"], by[s].get("url", "")):
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
