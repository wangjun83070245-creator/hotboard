"""渲染：view（run.py 内存生成）+ summaries.json → site/index.html 单文件。无 CDN、CSP、全部转义、不调用 AI。
用法：python -m hot.render view.json out.html [summaries.json]"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
from .github_rank import FOOTER as GH_FOOTER, block_config_public
CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'"


def load_summaries(path):
    """缺失/损坏 → {}（正常降级）。新闻：id → title/summary；GitHub：full_name → summary。"""
    try:
        d = json.loads(Path(path).read_text(encoding="utf-8"))
    except Exception:
        return {}
    if not isinstance(d, dict):
        return {}
    out = {}
    for k, v in d.items():
        if isinstance(v, dict):
            out[str(k)] = {f: v[f] for f in ("title", "summary", "generated_at") if isinstance(v.get(f), str)}
    return out


def _blob(obj):
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


# 试发布提示：页面顶部静态文字（非弹窗、不可聚焦、不影响键盘操作）
TRIAL_NOTICE = "试发布：新闻合并未完成，可能有重复报道"



def render(view, summaries, out_path, github=None, github_summaries=None):
    css = (HERE / "_style.css").read_text(encoding="utf-8")
    js = (HERE / "_app.js").read_text(encoding="utf-8")
    ids = set(view["items"])
    summ = {k: v for k, v in summaries.items() if k in ids}
    gh = github if isinstance(github, dict) else {}
    ghs = github_summaries if isinstance(github_summaries, dict) else {}
    names = set()
    boards = gh.get("boards") if isinstance(gh.get("boards"), dict) else {}
    for rows in boards.values():
        for r in rows or []:
            if isinstance(r, dict) and r.get("full_name"):
                names.add(r["full_name"])
    if names:
        ghs = {k: v for k, v in ghs.items() if k in names}
    html = f"""<!doctype html><html lang="zh-CN"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<meta name="referrer" content="no-referrer">
<meta http-equiv="Content-Security-Policy" content="{CSP}">
<title>信息雷达 · 实时热榜</title>
<style>{css}</style></head><body><div class="wrap">
<p class="trial" id="trial" role="note">{TRIAL_NOTICE}</p>
<header class="top"><div><h1>信息雷达 · 实时热榜<small>每小时更新</small></h1>
<div class="upd" id="upd"></div></div>
<button class="icon" id="theme" type="button" aria-label="切换深浅色">◐ 主题</button></header>
<div class="bar" role="tablist" aria-label="分类" id="tabs"></div>
<div id="status"></div>
<main id="main"></main>
<section id="gh-mod" aria-labelledby="gh-title">
<h2 id="gh-title">GitHub 项目</h2>
<div class="bar" role="tablist" aria-label="已标记列表" id="gh-lists"></div>
<div id="gh-status"></div>
<div class="bar" role="tablist" aria-label="GitHub 榜" id="gh-boards"></div>
<div class="bar" role="tablist" aria-label="GitHub 类别" id="gh-cats"></div>
<div id="gh-main"></div>
</section>
<footer id="foot"><p id="basis">排序依据：名次、互动数、跨源数，不含点击率</p>
<p id="gh-basis">{GH_FOOTER}</p></footer></div>
<dialog id="dlg" aria-labelledby="dt"><div class="dh"><h2 id="dt" style="margin:4px 0;color:var(--fg);font-size:16px"></h2><button class="icon" id="dx" type="button" aria-label="关闭详情">✕</button></div><div class="db" id="db"></div></dialog>
<script type="application/json" id="data">{_blob(view)}</script>
<script type="application/json" id="sum">{_blob(summ)}</script>
<script type="application/json" id="gh">{_blob(gh)}</script>
<script type="application/json" id="ghsum">{_blob(ghs)}</script>
<script type="application/json" id="gh-block">{_blob(block_config_public())}</script>
<script>{js}</script></body></html>"""
    out_path = Path(out_path)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    tmp = out_path.with_suffix(".html.part")
    tmp.write_text(html, encoding="utf-8")
    tmp.replace(out_path)
    return out_path


if __name__ == "__main__":
    v = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
    s = load_summaries(sys.argv[3]) if len(sys.argv) > 3 else {}
    print(render(v, s, sys.argv[2]))
