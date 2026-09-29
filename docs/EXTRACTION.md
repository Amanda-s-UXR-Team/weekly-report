# 提取记录

来源：`https://github.com/gbwgc002/Six-Country-Info-Insights`

固定提交：`d2a93e140672ddc4f32b20e09adab47529924de7`

日期：2026-09-29。GitHub 只读；所有调整均发生在交付副本。

## 保留原则

保留七国日报实际执行的采集、预处理、语义去重、AI 筛选/翻译/摘要、国家均衡、每日亮点、HTML/PDF、飞书上传/权限/卡片、轻量回执。国家、分类、关键词、启用状态、来源权重、AI Prompt、模型配置和日报视觉模板沿用源版本。

## 本地调整

| 文件 | 调整 |
|---|---|
| `main.py` | 去除 SMTP 发送分支；保留 HTML/PDF。AI 初始化改用新项目的 `DEEPSEEK_API_KEY`。未配置归档根目录时直接上传 PDF |
| `collectors/__init__.py` | 只导出 RSS 采集能力，不再尝试导入未打包的其他采集器 |
| `config/sources.yaml` | 原 90 项 RSS 配置完整保留；去掉关闭的其他采集器配置和国家周报专属数量参数 |
| `processors/summarizer.py` | 去掉单国周报亮点方法；日报业务方法与 Prompt 保留；底层从 Vertex AI 改为 DeepSeek Chat Completions |
| `email_sender.py` | 保留类名、HTML/PDF 方法和模板接口；移除 SMTP 发送函数、初始化和邮件依赖 |
| `publishers/feishu_publisher.py` | 保留日报上传、权限、卡片、确认回执、登记/清理依赖；移除无关文档创建/读写与 AI 专题卡片方法 |
| `publishers/feishu_archive.py` | 原固定目录值清空；仅解析日报子目录；移除 AI 周报目录及迁移工具逻辑 |
| `monitoring.py` | 保留回执与确认校验；目标/管线名单收缩为七国日报 |
| `requirements.txt` | 去掉无关抓取库 BeautifulSoup；增加跨平台时区数据 `tzdata` |
| `.env.example` | 全部凭据和目标目录留空；模型名称与源代码保持一致，去除旧模板中不一致的说明 |
| 工作流 | 只保留日报；统一新项目 Secret 名；自动计划默认注释，手动运行可用；保留 PDF/回执 artifact |
| 测试与文档 | 保留适用的国家策略测试和发送回执测试，新增提取后编排/单目录归档测试、离线 PDF 样例脚本和详细说明 |

保留了共享数据对象里的英文标题/摘要和部分显示元数据；保留模板内的可选双语字段。这些小型兼容结构不会运行其他业务管线，避免为压缩少量字段改变日报处理接口。源模板中的原仓库链接作为来源保留，新项目可按需修改。

## 没有打包

- `ai_insights.py`、AI 专题配置与 summarizer。
- `country_report.py`、`country_candidate_store.py`、五国归档器和历史候选 JSON。
- `design_ai_weekly_push.py`、外部设计源状态。
- arXiv、Twitter、Hacker News、WayToAGI 采集器。
- 监控汇总脚本、`monitor-data` 数据及监控网页。
- 历史归档迁移、旧预览脚本、旧报告样例和无关测试。
- 原 `.git`、环境、服务账号文件、飞书凭据、真实群 ID 和原固定归档根目录值。

## 版本可追溯性

`SOURCE_MANIFEST.json` 记录固定源提交与交付文件的 SHA-256；对源仓库存在的同名文件，同时记录原文件哈希及是否调整。该清单不包含自己，避免循环校验。原 GitHub 仓库没有提交、推送、分支创建或工作流变更。

## 新仓库部署调整（2026-09-29）

目标为 `Amanda-s-UXR-Team/weekly-report`，原仓库保持只读。新增 DeepSeek V4.1 Flash 接入、模型适配器测试、配置预检查；移除 Google SDK 依赖。工作流新增 push/PR 离线检查、手动 check/send 及 Variables 控制的每日定时推送。所有真实凭据和目标 ID 仍为空。
