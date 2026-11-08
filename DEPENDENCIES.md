# 依赖清单（2026-11-08 JST 本地核对）
许可证依据：各包安装后的元数据（`importlib.metadata` 的 License / License-Expression / Classifier）和包内 LICENSE 文件；已核对的 Python 包未使用 AGPL/GPL 许可证；此结论不涵盖未逐项核实的 Chromium 第三方组件（见下方“未核实”）。

## 运行依赖（GitHub Actions 与本地运行都装，`requirements.txt` 锁定版本）
| 包 | 声明版本 | 本地实装 | 直接/传递 | 许可证 | 依据 |
|---|---|---|---|---|---|
| feedparser | ==6.0.11 | 6.0.11 | 直接 | BSD-2-Clause | License 字段 + dist-info/LICENSE |
| sgmllib3k | ==1.0.0 | 1.0.0 | 传递（feedparser 需要），已在 requirements 锁定 | BSD | Classifier “OSI Approved :: BSD License”（包内无 LICENSE 文件） |
| PyYAML | ==6.0.2 | 6.0.2 | 直接 | MIT | License 字段 + dist-info/LICENSE |

其余只用 Python 标准库（urllib、json、socket 等）。Actions 上用 `actions/setup-python` 的 Python 3.12；本次本地环境为 Python 3.13.5（PSF-2.0）。

## 测试依赖（只在本地测试用，不进 Actions、不进公开仓库）
| 包 | 本地实装 | 直接/传递 | 许可证 | 依据 |
|---|---|---|---|---|
| playwright | 1.58.0 | 直接（页面自查） | Apache-2.0 | License-Expression + dist-info/licenses/LICENSE |
| greenlet | 3.5.6 | 传递（playwright） | MIT AND PSF-2.0 | License-Expression + LICENSE、LICENSE.PSF |
| pyee | 13.0.1 | 传递（playwright） | MIT | Classifier + LICENSE |
| typing_extensions | 4.16.0 | 传递（pyee） | PSF-2.0 | License-Expression + LICENSE |
| Chromium headless shell（playwright 下载的浏览器） | playwright 1.58 对应版本 | 运行时二进制 | BSD-3-Clause 及第三方组件许可（Chromium 项目） | Playwright 官方说明的浏览器来源；未逐项核对其内附第三方许可 |
| playwright 内置 Node.js 驱动 | 随 playwright 1.58.0 | 运行时二进制 | MIT（Node.js） | 包内 driver/LICENSE |

## 工具（不随代码分发）
| 工具 | 版本 | 许可证 | 依据 |
|---|---|---|---|
| gitleaks | 8.30.1 | MIT | 官方 GitHub release 附带的 LICENSE；下载包 sha256 与官方 checksums 一致 |

## GitHub Actions（workflow 里固定到 commit SHA）
actions/checkout v4.2.2、actions/setup-python v5.6.0、actions/cache v4.2.3、actions/upload-pages-artifact v3.0.1、actions/deploy-pages v4.0.5，均为 GitHub 官方 action，许可证 MIT（依据：GitHub API 各仓库 /license 返回 spdx_id=MIT，2026-11-08 查询）。

## 未核实
- Chromium 内附第三方组件的逐项许可：未核对（只用于本地测试，不分发）。
- greenlet、typing_extensions 等测试依赖未在 requirements 锁定，本地版本为本次安装所得。
