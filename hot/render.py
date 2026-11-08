"""渲染：view（run.py 内存生成）+ summaries.json → site/index.html 单文件。无 CDN、CSP、全部转义、不调用 AI。
用法：python -m hot.render view.json out.html [summaries.json]"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CSP = "default-src 'none'; style-src 'unsafe-inline'; script-src 'unsafe-inline'; img-src data:; connect-src 'self'; base-uri 'none'; form-action 'none'"


def load_summaries(path):
    """缺失/损坏 → {}（正常降级）。只保留 id → {title, summary, generated_at} 的字符串字段。"""
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


def render(view, summaries, out_path):
    css = (HERE / "_style.css").read_text(encoding="utf-8")
    js = (HERE / "_app.js").read_text(encoding="utf-8")
    ids = set(view["items"])
    summ = {k: v for k, v in summaries.items() if k in ids}
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
<footer id="foot"><p id="basis">排序依据：名次、互动数、跨源数，不含点击率</p></footer></div>
<dialog id="dlg" aria-labelledby="dt"><div class="dh"><h2 id="dt" style="margin:4px 0;color:var(--fg);font-size:16px"></h2><button class="icon" id="dx" type="button" aria-label="关闭详情">✕</button></div><div class="db" id="db"></div></dialog>
<script type="application/json" id="data">{_blob(view)}</script>
<script type="application/json" id="sum">{_blob(summ)}</script>
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
