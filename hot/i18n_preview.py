"""Build an isolated local preview page. No network, no git push."""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .common import JST, ROOT, UnsafePath, iso, validate_allowed_write_path
from .i18n_apply import apply_all
from .i18n_quality import i18n_cfg
from .i18n_translate import FakeTranslator, TranslationError, make_translator
from .render import render
from .run import build_view
from .snapshot import write_latest


class UnsafePreview(ValueError):
    pass


def validate_preview_out(out, root=None):
    """Preview output must resolve under the project's data/ or selftest/."""
    try:
        return validate_allowed_write_path(out, root=root)
    except UnsafePath as e:
        raise UnsafePreview(str(e)) from e


TABS = ["全部", "AI", "重大新闻", "芯片", "马斯克系"]
NOW = datetime(2026, 11, 11, 12, 0, tzinfo=JST)


class ScriptedTranslator(FakeTranslator):
    """Stub that can force specific source texts to fail."""

    name = "scripted"

    def __init__(self, fail_texts=None, mapping=None):
        super().__init__()
        self.fail_texts = set(fail_texts or [])
        self.mapping = dict(mapping or {})

    def translate(self, text, src="en", tgt="zh"):
        src_text = "" if text is None else str(text)
        self.calls.append(src_text)
        if src_text in self.fail_texts:
            return ""
        if src_text in self.mapping:
            v = self.mapping[src_text]
            if isinstance(v, Exception):
                raise v
            return v
        return "本条已译成中文。"


def cluster(cid, title, family="bbc", tab="全部", heat=50.0, url=None, first_pub=None):
    url = url or ("https://example.com/n/" + cid)
    fp = first_pub or iso(NOW)
    member = dict(source=family, family=family, url=url, title=title, metrics={"score": 1},
                  norm=1.0, weight=1, disc=None)
    cats = ["全部"] if tab == "全部" else ["全部", tab]
    return dict(id=cid, title=title, url=url, source=family, family=family, members=[member],
                families=[family], k=1, E=1.0, D=0.0, decay=1.0, age_h=1.0, first_pub=fp,
                H=float(heat), cats=cats)


def gh_repo(full_name, description="", stars=200, rank=1, board="rising", tags=None, language="Python", topics=None):
    owner, name = full_name.split("/", 1)
    return dict(full_name=full_name, name=name, owner_login=owner,
                url="https://github.com/" + full_name, description=description,
                language=language, topics=list(topics or []), tags=list(tags or ["其他"]),
                stars=stars, stars_delta=2, stars_window="24h_snapshot", stars_7d=5,
                rank=rank, board=board, created_at="2024-01-01T00:00:00Z",
                forks_count=3, license_spdx="MIT")


def news_bundle():
    """Preview + test fixture: Chinese source, English, fail, kana, nhk, teaser, backfill."""
    items = []
    clusters = []
    # High heat English that we force-fail (should be withdrawn; #21 fills).
    fail_title = "This headline is deliberately untranslated"
    clusters.append(cluster("fail01", fail_title, family="bbc", tab="AI", heat=99))
    items.append(dict(id="fail01", title=fail_title, url="https://example.com/n/fail01",
                      family="bbc", source="bbc", _teaser="Long English teaser that must not appear in public pages."))
    # Already Chinese (IT-home style) — must not be sent to the translator.
    zh_title = "长城汽车提醒：警惕假冒召回短信，不点、不信、不转账"
    clusters.append(cluster("zh01", zh_title, family="ithome", tab="芯片", heat=98))
    items.append(dict(id="zh01", title=zh_title, url="https://example.com/n/zh01",
                      family="ithome", source="ithome"))
    # Mixed Chinese with a proper noun, should pass the gate as already Chinese.
    mix = "Nvidia 发布新芯片"
    clusters.append(cluster("mix01", mix, family="ithome", tab="芯片", heat=97))
    items.append(dict(id="mix01", title=mix, url="https://example.com/n/mix01",
                      family="ithome", source="ithome"))
    # English with teaser (translated when the engine succeeds).
    en = "OpenAI announces a new research preview"
    teaser = "The company said the preview would start next week in limited regions."
    clusters.append(cluster("en01", en, family="bbc", tab="AI", heat=96))
    items.append(dict(id="en01", title=en, url="https://example.com/n/en01",
                      family="bbc", source="bbc", _teaser=teaser))
    # Kana — not already Chinese; forced fail so it is withdrawn, never shown as Chinese.
    kana = "東京で新しい発表がありました"
    clusters.append(cluster("kana01", kana, family="nhk", tab="重大新闻", heat=95))
    items.append(dict(id="kana01", title=kana, url="https://example.com/n/kana01",
                      family="nhk", source="nhk"))
    # NHK all-Han title — family blocks the skip; we force-fail to withdraw.
    nhk = "気象庁が注意を呼びかけ"
    # actually has kana が/を. Use a Han-only NHK title:
    nhk = "気象庁注意喚起"
    # still has no Han? 気象庁注意喚起 is Kanji (CJK unified). Good.
    clusters.append(cluster("nhk01", nhk, family="nhk", tab="重大新闻", heat=94))
    items.append(dict(id="nhk01", title=nhk, url="https://example.com/n/nhk01",
                      family="nhk", source="nhk"))
    # Fillers 07..27 so a 21st candidate can backfill after fail01.
    for i in range(7, 28):
        cid = "pad%02d" % i
        title = "Filler story number %d about chips" % i
        heat = 90 - i
        tab = "芯片" if i % 2 == 0 else "AI"
        clusters.append(cluster(cid, title, family="bbc", tab=tab, heat=heat))
        items.append(dict(id=cid, title=title, url="https://example.com/n/" + cid,
                          family="bbc", source="bbc"))
    return clusters, items


def github_bundle():
    rows = [
        gh_repo("kept/chinese", "unused english", stars=900, rank=1, tags=["开发工具"]),
        gh_repo("fresh/english", "An experimental toolkit for local builds", stars=800, rank=2, tags=["开发工具"]),
        gh_repo("already/zhdesc", "这是仓库自带的中文说明", stars=700, rank=3, tags=["文档"]),
        gh_repo("empty/nodesc", "", stars=600, rank=4, tags=["其他"]),
        gh_repo("fail/intro", "This description will be forced to fail", stars=500, rank=5, tags=["其他"]),
    ]
    # pads so the failed intro can be backfilled from later rows
    for i in range(6, 25):
        rows.append(gh_repo("pad/repo%02d" % i, "English description for repo %d" % i,
                            stars=400 - i, rank=i, tags=["其他"]))
    boards = {"rising": [dict(r, board="rising") for r in rows],
              "hot": [dict(r, board="hot") for r in rows],
              "all": [dict(r, board="all", stars_delta=None) for r in rows]}
    summaries = {
        "kept/chinese": {"summary": "已有维护者写的中文简介", "generated_at": iso(NOW)},
    }
    return dict(at=iso(NOW), prev_at=None, gap_h=None, failed=[], window_note="", boards=boards), summaries


def cmp_from_clusters(clusters, tabs=None, now=NOW):
    tabs = tabs or TABS
    by_tab = {t: [] for t in tabs}
    ordered = sorted(clusters, key=lambda c: -c["H"])
    for tab in tabs:
        rank = 0
        for c in ordered:
            if tab not in c["cats"] and tab != "全部":
                continue
            if tab == "全部" and "全部" not in c["cats"]:
                continue
            rank += 1
            by_tab[tab].append(dict(id=c["id"], rank=rank, delta="new", trend=None,
                                    hist=[dict(at=iso(now), rank=rank, heat=c["H"])]))
    return dict(cats=by_tab, prev_at=None, gap_h=None, snaps=[iso(now)])


def preview_translator():
    fail = {
        "This headline is deliberately untranslated",
        "Long English teaser that must not appear in public pages.",
        "東京で新しい発表がありました",
        "気象庁注意喚起",
        "This description will be forced to fail",
    }
    return ScriptedTranslator(fail_texts=fail)


def build_preview(out_dir, translator=None, cfg=None, now=None):
    now = now or NOW
    cfg = i18n_cfg(cfg)
    out = validate_preview_out(out_dir)
    data = out / "data"
    site = out / "site"
    data.mkdir(parents=True, exist_ok=True)
    site.mkdir(parents=True, exist_ok=True)
    clusters, items = news_bundle()
    gh_view, gh_summ = github_bundle()
    cmp = cmp_from_clusters(clusters, now=now)
    status = [dict(name="fixture", ok=True, skipped=False)]
    view = build_view(clusters, cmp, status, now, TABS)
    tr = translator or preview_translator()
    applied = apply_all(view, gh_view, clusters, {}, gh_summ,
                        data / "i18n_cache.json", translator=tr, cfg=cfg, now=now, items=items)
    view, gh_out = applied["view"], applied["github"]
    cmp_out = dict(cmp)
    cmp_out["cats"] = view.get("cats") or {}
    write_latest(clusters, status, now, data, TABS, {"page_top": 20}, cmp_out)
    html = render(view, applied["news_summaries"], site / "index.html",
                  github=gh_out, github_summaries=applied["github_summaries"])
    (site / "latest.json").write_text((data / "latest.json").read_text(encoding="utf-8"), encoding="utf-8")
    meta = {
        "news_failed": sorted(applied["news_failed"]),
        "github_failed": sorted(applied["github_failed"]),
        "news_banner": view.get("zh_banner") or "",
        "github_banner": (gh_out or {}).get("zh_banner") or "",
        "html": str(html),
    }
    (out / "preview_meta.json").write_text(json.dumps(meta, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return meta


def main(argv=None):
    ap = argparse.ArgumentParser(description="Write an isolated all-Chinese preview page")
    ap.add_argument("--out", default=str(ROOT / "selftest" / "preview"))
    a = ap.parse_args(argv)
    try:
        meta = build_preview(a.out)
    except UnsafePreview as e:
        print("preview refused: " + str(e), file=sys.stderr)
        return 2
    print("preview:", meta["html"])
    print("news_banner:", meta["news_banner"] or "(none)")
    print("github_banner:", meta["github_banner"] or "(none)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
