"""一次完整运行：采集 → 打分 → 对比 → 快照 → 渲染。只写 hotboard/ 下的 data/、site/、logs/。
告警只写本地日志 + 页面提示，不对外发送任何消息。不调用 AI。
用法：python -m hot.run [--data DIR] [--site DIR] [--logs DIR] [--now ISO]
退出码：0 成功；3 全部源失败（不写快照、不覆盖页面）。"""
import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from .collect import collect
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
    """Q4：按本轮计划抓取的源数定最少成功数；配置外的源数按约 84% 向上取整。"""
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
    a = ap.parse_args(argv)
    now = parse_iso(a.now) if a.now else datetime.now(UTC)
    log = Log(a.logs, now)
    w = load_yaml("weights.yaml")
    tabs = load_yaml("categories.yaml")["tabs"]
    items, status, reqlog = collect(now=now, sources=sources, cfg=w, timeout=timeout)
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
    write_snapshot(clusters, status, now, a.data, tabs, w)
    write_latest(clusters, status, now, a.data, tabs, w, cmp)
    prune(Path(a.data) / "snapshots", int(w["keep_snapshots"]), log=log)
    view = build_view(clusters, cmp, status, now, tabs)
    out = render(view, load_summaries(Path(a.data) / "summaries.json"), Path(a.site) / "index.html")
    # 页面断网检查要读同目录 latest.json
    (Path(a.site) / "latest.json").write_text((Path(a.data) / "latest.json").read_text(encoding="utf-8"), encoding="utf-8")
    log(f"done: 簇 {len(clusters)}，页面 {out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
