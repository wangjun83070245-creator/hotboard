"""一次完整运行：采集 → 打分 → 对比 → 快照 → 渲染。只写 hotboard/ 下的 data/、site/、logs/。
告警只写本地日志 + 页面提示，不对外发送任何消息。不调用 AI。
用法：python -m hot.run [--data DIR] [--site DIR] [--logs DIR] [--now ISO]
      python -m hot.run --dry-run [--fixture F] [--out 隔离目录] [--export-pending [PATH]]（不联网；默认隔离目录为 selftest/dryrun/）
退出码：0 成功；2 dry-run 输出路径不安全或 fixture 不可用；3 全部源失败（不写快照、不覆盖页面）。"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .collect import collect
from .dryrun import UnsafeOutput, no_network
from .common import JST, ROOT, UTC, UnsafePath, iso, load_yaml, parse_iso, validate_allowed_write_path
from .render import load_summaries, render
from .score import score
from .snapshot import compare, load_snapshots, prune, prune_snapshot_cache, write_latest, write_snapshot
from .github_snapshot import run_module as run_github
from .i18n_apply import _now_iso, apply_all, teasers_from_items
from .i18n_pending import write_pending
from .i18n_quality import i18n_cfg
from .i18n_translate import make_translator
from .httputil import redact_text

DEFAULT_DRYRUN_OUT = ROOT / "selftest" / "dryrun"


class Log:
    def __init__(self, logs_dir, now):
        self.path = Path(logs_dir) / f"run-{now.astimezone(JST):%Y%m%d}.log"
        self.path.parent.mkdir(parents=True, exist_ok=True)

    def __call__(self, msg):
        line = f"{datetime.now(JST):%Y-%m-%d %H:%M:%S} JST {msg}"
        print(line)
        with open(self.path, "a", encoding="utf-8") as f:
            f.write(line + "\n")


def health_threshold(n_due, w):
    """源健康阈值：按本轮计划抓取的源数定最少成功数；配置外的源数按约 84% 向上取整。"""
    tbl = {int(k): int(v) for k, v in (w.get("min_ok_by_due") or {}).items()}
    return tbl.get(n_due, -(-n_due * 84 // 100))


def build_view(clusters, cmp, status, now, tabs):
    ids = {r["id"] for rows in cmp["cats"].values() for r in rows}
    items = {}
    for c in clusters:
        if c["id"] in ids:
            items[c["id"]] = {k: c[k] for k in ("id", "title", "url", "source", "family", "members", "families", "k",
                                                "E", "D", "decay", "age_h", "first_pub", "H", "cats")}
    return dict(at=iso(now), prev_at=cmp["prev_at"], gap_h=cmp["gap_h"], snaps=cmp["snaps"], tabs=tabs,
                sources=[dict(name=s["name"], ok=s["ok"], skipped=s.get("skipped", False)) for s in status],
                items=items, cats=cmp["cats"])


def main(argv=None, sources=None, timeout=None):
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default=str(ROOT / "data"))
    ap.add_argument("--site", default=str(ROOT / "site"))
    ap.add_argument("--logs", default=str(ROOT / "logs"))
    ap.add_argument("--now", default=None)
    ap.add_argument("--dry-run", action="store_true", help="不联网：读 --fixture 的本地合成条目；只写隔离目录 --out")
    ap.add_argument("--fixture", default=str(ROOT / "tests" / "fixtures" / "dryrun_items.json"))
    ap.add_argument("--out", default=str(DEFAULT_DRYRUN_OUT),
                    help="dry-run 隔离目录，默认 selftest/dryrun/；只允许项目 data/ 或 selftest/ 下")
    ap.add_argument("--export-pending", nargs="?", const="", default=None,
                    help="写出 i18n_pending.json；不带路径时写到 selftest/dryrun/；带路径则必须在 data/ 或 selftest/ 下")
    a = ap.parse_args(argv)
    if a.dry_run:
        return _dry_run(a)
    return _run(a, sources, timeout)



def _seed_committed_data(dest_data, src_data=None):
    """Copy committed cache/summaries into an isolated data dir if missing."""
    src = Path(src_data or (ROOT / "data"))
    dest = Path(dest_data)
    dest.mkdir(parents=True, exist_ok=True)
    for name in ("i18n_cache.json", "github_summaries.json", "summaries.json"):
        s, d = src / name, dest / name
        if s.is_file() and not d.is_file():
            d.write_bytes(s.read_bytes())


def _write_pending_outputs(a, view, gh_view, clusters, items, gh_summ, now, log, cfg):
    teasers = teasers_from_items(items)
    site_path = Path(a.site) / "i18n_pending.json"
    try:
        dest, _payload, size, dropped = write_pending(
            site_path, view, gh_view, clusters, teasers,
            github_summaries=gh_summ, now_iso=_now_iso(now), cfg=cfg,
        )
        log("i18n pending: " + str(size) + " bytes, truncated " + str(dropped) + ", path " + dest.name)
    except Exception as e:
        log("i18n pending failed: " + type(e).__name__ + ": " + str(e)[:160])
        return
    extra = getattr(a, "export_pending", None)
    if extra is None:
        return
    try:
        if extra == "":
            # no PATH: always selftest/dryrun/i18n_pending.json
            copy_to = validate_allowed_write_path(DEFAULT_DRYRUN_OUT / "i18n_pending.json")
        else:
            copy_to = validate_allowed_write_path(extra)
        copy_to.parent.mkdir(parents=True, exist_ok=True)
        copy_to.write_bytes(Path(site_path).read_bytes())
        log("i18n pending also written to " + str(copy_to.name))
    except (UnsafePath, OSError) as e:
        log("i18n pending copy skipped: " + type(e).__name__)


def _dry_run(a):
    """dry-run：不采集、不联网；只写隔离目录；不读写/裁剪正式快照。"""
    try:
        out = validate_allowed_write_path(a.out or DEFAULT_DRYRUN_OUT)
    except UnsafePath as e:
        print(f"dry-run 拒绝：{e}", file=sys.stderr)
        return 2
    fx_path = Path(a.fixture)
    if not fx_path.is_file():
        print(
            "dry-run 拒绝：夹具文件不存在：" + str(fx_path)
            + "。请用 --fixture 传入本地夹具文件的路径。",
            file=sys.stderr,
        )
        return 2
    try:
        fx = json.loads(fx_path.read_text(encoding="utf-8"))
        items = fx.get("items")
        if not isinstance(items, list):
            raise ValueError("fixture 缺 items 列表")
    except (OSError, ValueError) as e:
        print(f"dry-run fixture 不可用：{type(e).__name__}", file=sys.stderr)
        return 2
    status = fx.get("status") or [dict(name="fixture", family="fixture", ok=True, http=None, err=None, n=len(items), ms=0, skipped=False)]
    a.data, a.site, a.logs = str(out / "data"), str(out / "site"), str(out / "logs")
    _seed_committed_data(a.data)
    recheck = lambda: validate_allowed_write_path(out)  # noqa: E731  写前再校验，缩小竞态窗口
    try:
        with no_network():
            return _run(a, None, None, fixed=(items, status, []), recheck=recheck)
    except (UnsafeOutput, UnsafePath) as e:
        print(f"dry-run 中止（写入前复查不通过）：{e}", file=sys.stderr)
        return 2


def _run(a, sources, timeout, fixed=None, recheck=None):
    now = parse_iso(a.now) if a.now else datetime.now(UTC)
    log = Log(a.logs, now)
    w = load_yaml("weights.yaml")
    tabs = load_yaml("categories.yaml")["tabs"]
    items, status, reqlog = fixed if fixed is not None else collect(now=now, sources=sources, cfg=w, timeout=timeout)
    for s in status:
        if not s["ok"]:
            log(f"source {'skip' if s.get('skipped') else 'FAIL'}: {s['name']} http={s['http']} err={redact_text(s['err'])}")
    fetched = [s for s in status if not s.get("skipped")]
    ok = [s for s in fetched if s["ok"]]
    log(f"collect: {len(ok)}/{len(fetched)} 源成功（{len(status) - len(fetched)} 个本轮不抓），条目 {len(items)}")
    need = health_threshold(len(fetched), w)
    if len(ok) < need:
        log(f"ALERT 源健康不达标：{len(ok)}/{len(fetched)} < {need}（本地告警，不对外发送）")
    else:
        log(f"health: {len(ok)}/{len(fetched)} ≥ {need} 达标")
    if not ok:
        log("ALERT 全部源失败：不写快照、不覆盖页面（本地告警，不对外发送）")
        return 3
    clusters = score(items, now=now)
    snaps = load_snapshots(Path(a.data) / "snapshots")
    ic = i18n_cfg()
    pool = int(ic.get("pool") or 40)
    cmp = compare(clusters, snaps, now, tabs, w, top=pool)
    if cmp["prev_at"] is None and snaps:
        log("ALERT 最近 3 小时内无可用快照（漏跑/损坏），按首次运行处理")
    elif cmp["gap_h"] and cmp["gap_h"] > 1:
        log(f"ALERT 漏跑：与 {cmp['gap_h']} 小时前的快照对比")
    if recheck:
        recheck()
    write_snapshot(clusters, status, now, a.data, tabs, w)
    if recheck:
        recheck()
    prune(Path(a.data) / "snapshots", int(w["keep_snapshots"]), log=log)
    if recheck:
        recheck()
    view = build_view(clusters, cmp, status, now, tabs)
    gh_view = run_github(now, a.data, log=log, skip_network=(fixed is not None))
    prune_snapshot_cache(Path(a.data), now, w=w, log=log)
    news_summ = load_summaries(Path(a.data) / "summaries.json")
    gh_summ = load_summaries(Path(a.data) / "github_summaries.json")
    _write_pending_outputs(a, view, gh_view, clusters, items, gh_summ, now, log, ic)
    try:
        tr = make_translator(cfg=ic)
        applied = apply_all(
            view, gh_view, clusters, news_summ, gh_summ,
            Path(a.data) / "i18n_cache.json",
            translator=tr, cfg=ic, now=now, items=items,
        )
        view, gh_view = applied["view"], applied["github"]
        news_summ, gh_summ = applied["news_summaries"], applied["github_summaries"]
        log("i18n: news dropped " + str(len(applied["news_failed"]))
            + ", github dropped " + str(len(applied["github_failed"])))
    except Exception as e:
        log("i18n module failed: " + type(e).__name__ + ": " + redact_text(str(e))[:160])
        # Do not put untranslated English on the main board.
        banner = (ic.get("banner") or "本轮有 {n} 条未能译成中文，已撤下")
        page_top = int(ic.get("page_top") or 20)
        def _top20(rows, key):
            out=set()
            for r in rows or []:
                try:
                    rank=int(r.get("rank") or 0)
                except (TypeError, ValueError):
                    rank=0
                ident=r.get(key) or ""
                if ident and 1<=rank<=page_top:
                    out.add(ident)
            return out
        n_news = len(set().union(*(_top20(rows, "id") for rows in (view.get("cats") or {}).values())) ) if view.get("cats") else 0
        n_gh = 0
        if isinstance(gh_view, dict):
            n_gh = len(set().union(*(_top20(rows, "full_name") for rows in (gh_view.get("boards") or {}).values())) ) if gh_view.get("boards") else 0
        view = dict(view)
        view["cats"] = {k: [] for k in (view.get("cats") or {})}
        view["items"] = {}
        view["zh_dropped"] = n_news
        view["zh_banner"] = banner.format(n=n_news) if n_news else ""
        if isinstance(gh_view, dict):
            gh_view = dict(gh_view)
            gh_view["boards"] = {k: [] for k in (gh_view.get("boards") or {})}
            gh_view["zh_dropped"] = n_gh
            gh_view["zh_banner"] = banner.format(n=n_gh) if n_gh else ""
    cmp_out = dict(cmp)
    cmp_out["cats"] = view.get("cats") or {}
    write_latest(clusters, status, now, a.data, tabs, w, cmp_out)
    if recheck:
        recheck()
    out = render(view, news_summ, Path(a.site) / "index.html",
                 github=gh_view, github_summaries=gh_summ)
    # 页面断网检查要读同目录 latest.json
    (Path(a.site) / "latest.json").write_text((Path(a.data) / "latest.json").read_text(encoding="utf-8"), encoding="utf-8")
    log(f"done: 簇 {len(clusters)}，页面 {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
