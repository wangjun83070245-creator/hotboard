# 信息雷达 · 实时热榜（hot-v1）
每小时（GitHub Actions，UTC 第 5 分）抓取公开 API/RSS → 聚类打分 → 快照对比 → 生成单文件静态页并发布到 GitHub Pages。
- 不调用 AI，不需要任何密钥；中文标题/摘要由维护者手动提交 `data/summaries.json`（可缺失，缺失时显示原标题）。
- 本地运行：`pip install -r requirements.txt && python -m hot.run`
- 排序依据：名次、互动数、跨源数，不含点击率。
- 依赖：feedparser（BSD-2-Clause）、sgmllib3k（BSD）、PyYAML（MIT）；测试另用 playwright（Apache-2.0）。
