# 信息雷达 · 实时热榜（hot-v1）
每小时（GitHub Actions，UTC 第 5 分）抓取公开 API/RSS → 聚类打分 → 快照对比 → 生成单文件静态页并发布到 GitHub Pages。
- 不调用 AI，不需要任何密钥；中文标题/摘要由维护者手动提交 `data/summaries.json`（可缺失，缺失时显示原标题）。
- 本地运行：`pip install -r requirements.txt && python -m hot.run`
- 干跑：`python -m hot.run --dry-run --out <隔离目录>`（不联网；输出目录不能与工程目录及正式 data/site/logs 重叠，不能含符号链接）
- 同事件合并（`hot/match.py` + `config/merge.yaml`）：只看标题、用词表近似，不理解语义。先查冲突（具名主体不同或一边缺失、地点不同、年份不同、事件类型不同、涨跌立场相反）就不合并，再看共同实体/共同词/Jaccard 门槛；聚类和簇内每个成员逐一比较，不拿全簇词集合做并集比较，结果与输入顺序无关。
- 排序依据：名次、互动数、跨源数，不含点击率。
- 依赖：feedparser（BSD-2-Clause）、sgmllib3k（BSD）、PyYAML（MIT）；测试另用 playwright（Apache-2.0）。
