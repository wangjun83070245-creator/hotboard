"""一次完整运行：采集 → 打分 → 对比 → 快照 → 渲染。只写 hotboard/ 下的 data/、site/、logs/。
告警只写本地日志 + 页面提示，不对外发送任何消息。不调用 AI。
用法：python -m hot.run [--data DIR] [--site DIR] [--logs DIR] [--now ISO]
      python -m hot.run --dry-run [--fixture F] [--out 隔离目录]（不联网，只写隔离目录）
退出码：0 成功；2 dry-run 输出路径不安全或 fixture 不可用；3 全部源失败（不写快照、不覆盖页面）。"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .collect import collect
from .dryrun import UnsafeOutput, no_network, validate_out
from .common import JST, ROOT, UTC, iso, load_yaml, parse_iso
from .render import load_summaries, render
from .score import score
from .snapshot import compare, load_snapshots, prune, write_latest, write_snapshot


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
    ap.add_argument("--out", default=str(ROOT.parent / (ROOT.name + "-ceshi")))
    a = ap.parse_args(argv)
    if a.dry_run:
        return _dry_run(a)
    return _run(a, sources, timeout)


def _dry_run(a):
    """dry-run：不采集、不联网；只写隔离目录；不读写/裁剪正式快照。"""
    protected = [ROOT, ROOT / "data", ROOT / "site", ROOT / "logs", ROOT / "data" / "snapshots",
                 a.data, a.site, a.logs, Path(a.data) / "snapshots"]
    try:
        out = validate_out(a.out, protected)
    except UnsafeOutput as e:
        print(f"dry-run 拒绝：{e}", file=sys.stderr)
        return 2
    try:
        fx = json.loads(Path(a.fixture).read_text(encoding="utf-8"))
        items = fx.get("items")
        if not isinstance(items, list):
            raise ValueError("fixture 缺 items 列表")
    except (OSError, ValueError) as e:
        print(f"dry-run fixture 不可用：{type(e).__name__}", file=sys.stderr)
        return 2
    status = fx.get("status") or [dict(name="fixture", family="fixture", ok=True, http=None, err=None, n=len(items), ms=0, skipped=False)]
    a.data, a.site, a.logs = str(out / "data"), str(out / "site"), str(out / "logs")
    recheck = lambda: validate_out(out, protected)  # noqa: E731  写前再校验，缩小竞态窗口
    try:
        with no_network():
            return _run(a, None, None, fixed=(items, status, []), recheck=recheck)
    except UnsafeOutput as e:
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
            log(f"source {'skip' if s.get('skipped') else 'FAIL'}: {s['name']} http={s['http']} err={s['err']}")
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
    cmp = compare(clusters, snaps, now, tabs, w)
    if cmp["prev_at"] is None and snaps:
        log("ALERT 最近 3 小时内无可用快照（漏跑/损坏），按首次运行处理")
    elif cmp["gap_h"] and cmp["gap_h"] > 1:
        log(f"ALERT 漏跑：与 {cmp['gap_h']} 小时前的快照对比")
    if recheck:
        recheck()
    write_snapshot(clusters, status, now, a.data, tabs, w)
    write_latest(clusters, status, now, a.data, tabs, w, cmp)
    if recheck:
        recheck()
    prune(Path(a.data) / "snapshots", int(w["keep_snapshots"]), log=log)
    if recheck:
        recheck()
    view = build_view(clusters, cmp, status, now, tabs)
    out = render(view, load_summaries(Path(a.data) / "summaries.json"), Path(a.site) / "index.html")
    # 页面断网检查要读同目录 latest.json
    (Path(a.site) / "latest.json").write_text((Path(a.data) / "latest.json").read_text(encoding="utf-8"), encoding="utf-8")
    log(f"done: 簇 {len(clusters)}，页面 {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
