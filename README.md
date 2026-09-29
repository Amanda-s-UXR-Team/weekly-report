# 七国日报核心版 · Seven-Country Daily Core

从 `gbwgc002/Six-Country-Info-Insights` 提取的独立日报代码包，保留：

**资讯源配置 → RSS 采集 → 去重与过滤 → DeepSeek V4.1 Flash 筛选、摘要与翻译 → 日报 PDF → 飞书软件用研群卡片。**

源版本：[`d2a93e140672ddc4f32b20e09adab47529924de7`](https://github.com/gbwgc002/Six-Country-Info-Insights/tree/d2a93e140672ddc4f32b20e09adab47529924de7)，提取日期：2026-09-29。

这是一份整理后的独立副本，不包含 Git 历史、原项目凭据、历史新闻、历史报告或原群 ID。未修改原 GitHub 仓库。

首次接手请先看 [START_HERE.md](START_HERE.md)，按上传、配置、检查、发送的顺序操作。

## 先看这几个文件

| 文件 | 用途 |
|---|---|
| [docs/LOGIC.md](docs/LOGIC.md) | 详细处理流程、函数调用关系、数据字段与异常分支 |
| [docs/daily-flow.mmd](docs/daily-flow.mmd) | 可编辑的 Mermaid 主流程图 |
| [docs/daily-flow.png](docs/daily-flow.png) | 可直接打开的逻辑关系图 |
| [docs/EXTRACTION.md](docs/EXTRACTION.md) | 保留、删除与本地调整清单，以及原有行为说明 |
| [docs/VALIDATION.md](docs/VALIDATION.md) | 本次验证范围和结果 |
| [config/sources.yaml](config/sources.yaml) | 信息源、关键词、权重、分类及数量上限 |
| [.env.example](.env.example) | 新项目环境变量模板 |

## 功能范围

- 覆盖 EE1、印度、印尼、尼日利亚、肯尼亚、巴基斯坦、孟加拉。
- 保留原项目 90 条 RSS 源配置，其中 77 条启用；启用数量不代表当前全部可访问。
- 六类内容：宏观/基建、商业/消费、数字生态、数字生活、手机市场、相关国家要闻。
- 保留来源权重、关键词过滤、时效过滤、国家均衡、AI 语义去重与相关性筛选。
- AI 生成中英文标题和摘要字段；这条日报的默认 PDF 与群卡片主要展示中文。
- 报告含今日要点、分类资讯、原文链接和信息源附录。
- 飞书卡片展示今日要点与完整 PDF 链接；详细正文在 PDF 中。
- 保留 PDF 上传、群访问权限、可选归档/所有权转移和安全发送回执。

不包含：五国单独周报、AI 用研专题周报、设计资讯组合周报、周候选库、完整监控平台、历史归档迁移，以及 SMTP 邮件发送。`email_sender.py` 文件名为兼容原代码保留，交付版只负责 HTML/PDF。

## 1. 本地运行环境（只用 Actions 可跳过）

本仓库已包含核心代码和 `.github/workflows/daily-digest.yml`。使用 GitHub Actions 不需要另建服务器、数据库或定时任务，也无需在本地安装 Python。直接完成第 2、4 节配置即可。

推荐 Python 3.11 或更高版本；PDF 运行环境推荐 Ubuntu/Linux。Windows 可通过 WSL 使用下方 Linux 步骤。

```bash
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
pip install -r requirements.txt
```

Ubuntu/Debian 安装 PDF 所需系统库和中文字体：

```bash
sudo apt-get update
sudo apt-get install -y libcairo2 libpango-1.0-0 libpangocairo-1.0-0 libgdk-pixbuf-2.0-0 libffi-dev shared-mime-info fonts-noto-cjk fonts-wqy-zenhei fonts-noto-color-emoji
```

## 2. 配置 AI 和飞书

```bash
cp .env.example .env
```

| 环境变量 | 必填性 | 内容 |
|---|---|---|
| `DEEPSEEK_API_KEY` | AI 必填 Secret | 在 [DeepSeek 开放平台](https://platform.deepseek.com/) 创建的新 API Key |
| `DEEPSEEK_MODEL` | 可选 Variable | 默认 `deepseek-flash`，对应 DeepSeek V4.1 Flash |
| `DEEPSEEK_BASE_URL` | 可选 Variable | 默认 `https://api.deepseek.com` |
| `ENABLE_DAILY_PUSH` | 可选 Variable | 设置 `true` 后启用每天自动推送；缺省关闭 |
| `FEISHU_APP_ID`、`FEISHU_APP_SECRET` | 推送必填 | 新项目使用的飞书自建应用凭据 |
| `FEISHU_RECEIVE_ID` | 推送必填 Secret | 群聊填 `oc_...`，个人填该应用可见的 `ou_...` |
| `FEISHU_RECEIVE_ID_TYPE` | 推送必填 Variable | 群聊填 `chat_id`，个人填 `open_id`；默认 `chat_id` |
| `FEISHU_BOT_CHAT_ID` | 兼容旧配置 | 仅支持群聊的旧 Secret；未设置 `FEISHU_RECEIVE_ID` 时才读取 |
| `FEISHU_ADMIN_OPEN_ID` | 可选 | 用于赋予文件管理权限；启用所有权转移时需要 |
| `FEISHU_FOLDER_TOKEN` | 可选 | 直接上传 PDF 的目标目录；留空使用应用默认位置 |
| `FEISHU_ARCHIVE_ROOT_FOLDER_TOKEN` | 可选 | 启用归档路由的根目录；留空时不启用该路由 |
| `FEISHU_SIX_COUNTRY_FOLDER_NAME` | 可选 | 根目录下已有的日报子目录名，默认“六国洞察报告”；此旧命名仅用于兼容 |
| `REQUIRE_FEISHU_DELIVERY` | 建议 true | 未取得必需飞书发送确认时，不把任务当作正常完成 |
| `MONITOR_RECEIPT_PATH` | 可选 | 默认 `output/monitor/receipt.json` |

DeepSeek 开放平台账号需有可用 API 额度；本项目不再使用 Google 服务账号或 Vertex AI。飞书应用需要发送群消息、上传文件和设置文件访问权限的能力。使用归档目录时，机器人还需有该目录的访问/写入权限；转移所有权还需要相应能力。本包不包含原项目账号配置。

归档路由留空也能使用主线：直接调用飞书 PDF 上传，不再查找旧项目目录。配置归档根目录时，请事先创建名称匹配的日报子目录；本模块只查找，不负责自动新建。此版本不会再要求同时存在 AI 周报文件夹。

## 3. 先离线检查，再运行真实主线

以下测试不访问 RSS、模型或飞书：

```bash
python -m unittest discover -s tests -v
python tools/preview_offline.py
```

第二条生成 `output/offline-sample.pdf`，里面是明确标注的人工排版样例，不是真实资讯。

配置完成后，从项目根目录运行真实日报：

```bash
python tools/check_config.py
python main.py
```

此命令会实际采集、调用模型、上传 PDF 和发送飞书卡片，不是 dry-run。

主要输出：

| 路径/位置 | 内容 |
|---|---|
| `output/Seven_Country_Insights_YYYY-MM-DD.pdf` | 日报 PDF |
| `output/monitor/receipt.json` | 发送状态、请求/确认时间与安全错误码 |
| 飞书文件目录 | 上传后的 PDF |
| 目标群或个人会话 | 今日要点卡片与 PDF 链接 |
| `data/documents.json` | 本地生成的已上传文档登记，不随本包携带 |

## 4. GitHub Actions：同事仓库的首次配置

代码中的默认值已设置好；凭据必须使用新项目的值。入口：

- [Repository Secrets](https://github.com/Amanda-s-UXR-Team/weekly-report/settings/secrets/actions)
- [Repository Variables](https://github.com/Amanda-s-UXR-Team/weekly-report/settings/variables/actions)
- [Actions](https://github.com/Amanda-s-UXR-Team/weekly-report/actions)

### 第一步：配置四个必填 Secrets

| Secret 名称 | 要填的值 |
|---|---|
| `DEEPSEEK_API_KEY` | DeepSeek 开放平台 → API Keys → 创建 API Key；完整填入 |
| `FEISHU_APP_ID` | 同事的飞书自建应用 App ID |
| `FEISHU_APP_SECRET` | 同一个应用的 App Secret |
| `FEISHU_RECEIVE_ID` | 群聊填 `chat_id`（`oc_...`）；个人填 `open_id`（`ou_...`） |

这些都放 **Secrets**，不要提交到代码，也不要放 Variables。另外在 **Repository Variables** 新增 `FEISHU_RECEIVE_ID_TYPE`：群聊填 `chat_id`，个人填 `open_id`。切换接收对象时只需修改这一个 Secret 和一个 Variable，无需维护两套代码。若你看不到仓库设置入口，让仓库所有者填写。

飞书需创建/使用企业自建应用、开启机器人能力，开通代码需要的消息发送、云空间文件上传和文件权限管理权限，并发布应用版本/完成企业审批。群推送时把机器人加入目标群；个人推送时，接收人必须处于该应用的可用范围内，且 `open_id` 必须属于本次发送所用的同一个应用。这里只支持应用机器人，不是自定义机器人的 webhook key。

切换示例：

| 目标 | Secret `FEISHU_RECEIVE_ID` | Variable `FEISHU_RECEIVE_ID_TYPE` |
|---|---|---|
| 群聊 | `oc_...` | `chat_id` |
| 个人 | `ou_...` | `open_id` |

旧的 `FEISHU_BOT_CHAT_ID` 仍可继续用于群聊；只有在 `FEISHU_RECEIVE_ID` 未设置时才会回退读取，并固定按 `chat_id` 处理。`FEISHU_ADMIN_OPEN_ID` 始终只表示文件管理员/所有权接收人，与日报接收人相互独立，两者可以相同但不会自动绑定。

可选的 `FEISHU_ADMIN_OPEN_ID`、`FEISHU_FOLDER_TOKEN`、`FEISHU_ARCHIVE_ROOT_FOLDER_TOKEN` 也放 Secrets。先只填四项必填值；需要固定目录时再填你们的新目录 ID。所有这些值均没有沿用原项目。

### 第二步：验证并首次发送

1. 每次 push / PR 自动跑离线测试和样例 PDF 渲染，不读取业务凭据、不调用 DeepSeek、不发飞书。
2. 进入 Actions → **Seven-Country Daily Core** → **Run workflow** → `operation=check`。这会检查四个配置是否存在及基本格式；不会验证真实 API 余额和飞书权限。
3. 准备好后手动选 `operation=send`。这会真实采集、调用 DeepSeek（消耗 API 额度）、上传 PDF 并发到所填群聊或个人。日志及 PDF/回执保存在本次运行中。
4. 确认卡片、PDF 链接及接收人打开权限正常后，在 Variables 新增 `ENABLE_DAILY_PUSH=true`。从此每天北京时间 **06:25** 定时执行。GitHub 实际触发时间可能延迟。

包内已提供工作流文件，上传到仓库默认分支后生效，不需要再新建。`ENABLE_DAILY_PUSH` 未设置或不是 `true` 时，定时运行不会执行采集/推送。停止自动推送只需把它改成 `false`。

### DeepSeek 模型配置

已按 [官方 API 文档](https://api-docs.deepseek.com/) 接入：

- 模型 ID：`deepseek-flash`，官方对应 **DeepSeek V4.1 Flash**。不要把展示名 `deepseekV4.1FLASH` 当 API ID。
- API 地址：`https://api.deepseek.com/chat/completions`。
- 鉴权：代码自动使用 `Authorization: Bearer <DEEPSEEK_API_KEY>`。
- 采用非思考模式、5 路并发、JSON 结构化返回（需要结构化的任务），单次最多 4096 输出 tokens；超时/限流/服务端暂时错误有限重试。
- `DEEPSEEK_MODEL` 和 `DEEPSEEK_BASE_URL` 是可选 Variables，留空就使用上面的默认值。后续切换到同接口兼容的 DeepSeek 模型，只改 `DEEPSEEK_MODEL` 即可；换其他服务商时需核对鉴权、参数和结构，不能保证只改名称。
- 不需要 `GOOGLE_SA_JSON`、`GOOGLE_CLOUD_PROJECT` 或 `GEMINI_MODEL`。

模型对应关系核实于 2026-09-29。模型别名未来可能由服务商更新。

## 5. 改资讯源或研究方向

在 `config/sources.yaml` 的 `rss_sources` 中增删条目：

```yaml
rss_sources:
  example_source:
    name: "你的资讯源"
    url: "https://example.com/feed.xml"
    category: "digital_ecosystem"
    country: "kenya"
    priority: 1.5
    freshness_days: 2
    keywords: []
    max_items: 10
    enabled: true
```

上方仅说明配置格式；示例地址不是可用资讯源，正式运行前替换。

| 字段 | 作用 |
|---|---|
| `enabled` | 是否采集 |
| `keywords` | OR 关键词列表；为空则不按此列表过滤 |
| `require_keywords` | 可选第二组 OR 条件，与第一组结果做 AND |
| `country` | 国家元数据；共享源可标 `multi` |
| `priority` | 来源权重，参与排序；不等于强制选中 |
| `freshness_days` | 该源的单独时效窗口 |
| `max_items` | 每次该源最多返回条目数 |
| `category` | 初始分类，AI 可重新判断 |

当前 AI 前每类最多保留 30 条候选，AI 后每类最多 15 条；见 `output.pre_ai_max_per_category` 与 `output.max_per_category`。不是保证每天每类都有 15 条。

**这是七国用研业务的核心版，并未改造成任意主题通用引擎。** 若换研究方向，不仅要换 RSS，也要调整 `processors/summarizer.py` 的 Prompt、`processors/deduper.py` 的国家规则、`reporting.py` 的显示名称与模板默认文案。EE1 替换和来源权重策略仍按原项目保留。

## 6. 运行边界

- 采集的是 RSS 提供的正文/摘要；不保证会打开每篇文章补抓完整网页正文。
- 没有跨日候选数据库，去重主要作用于本次采集；7 天窗口的来源可能在连续几天中重复出现。
- 缺少 DeepSeek Key、鉴权/余额/模型配置报错、或整轮没有成功模型响应时会停止发送。个别条目解析/翻译失败仍保留原有降级策略，不代表每条都完成同等质量的 AI 处理。
- PDF 失败或上传失败时，原流程仍可能发送不带 PDF 链接的卡片。`REQUIRE_FEISHU_DELIVERY` 检查的是消息确认，不是 PDF 完整性。
- 飞书 API 确认不代表每个成员都已收到或阅读。
- 单群是推荐配置。逗号分隔多群保留了原实现，但 PDF 权限准备主要以第一个群为准，回执仍按同一日报目标汇总。
- 原本保留 180 天的清理逻辑依赖本地 `data/documents.json`。工作流没有把它作为持久状态提交/恢复，因此不能将它理解为已验证的跨次运行完整清理系统。

上述边界除 AI 接入与失败检查调整外，沿用提取的主线实现。完整依赖和异常路径见 [LOGIC.md](docs/LOGIC.md)。
