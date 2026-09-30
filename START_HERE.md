# 同事接手说明 · 2026-09-29 16:46（北京时间）

目标仓库：https://github.com/Amanda-s-UXR-Team/weekly-report

这是最新交付版：七国资讯源 → RSS 采集 → DeepSeek 整理、翻译 → PDF → 飞书推送。每份 PDF 上传后都会把所有者移交给 `FEISHU_ADMIN_OPEN_ID`，同时保留机器人管理权限。

## 1. 上传代码

先解压，把 `weekly-report` 文件夹**里面的所有内容**上传到仓库根目录。上传后根目录应直接看到 `main.py`、`README.md`、`requirements.txt` 和 `config/`。

一定保留 `.github/workflows/daily-digest.yml`、`.env.example` 和 `.gitignore`。不要只上传 ZIP，也不要让整个项目多套一层 `weekly-report/`。可以使用 GitHub Desktop/Git 上传，以确保点号开头的文件也被包含。提交到默认分支 `main`。

Actions 工作流文件已包含，不需要另建。推送代码会触发离线检查和样例 PDF 渲染；不会自动调用真实模型或发送飞书。

## 2. 四个必填配置

在仓库 Settings → Secrets and variables → Actions → Secrets 添加：

| 名称 | 内容 |
|---|---|
| DEEPSEEK_API_KEY | 新项目的 DeepSeek API Key，账号需有可用额度 |
| FEISHU_APP_ID | 新飞书企业自建应用的 App ID |
| FEISHU_APP_SECRET | 同一应用的 App Secret |
| FEISHU_BOT_CHAT_ID | 新接收群 chat_id，以 oc_ 开头 |

不需要改代码。不使用原项目的任何真实密钥或群 ID。飞书应用需要开启机器人、消息发送、云空间上传及文件权限管理能力，并发布应用版本/完成企业审批，把机器人加进接收群。这里不是 webhook 自定义机器人。

DeepSeek API Key 入口：https://platform.deepseek.com/
模型默认 `deepseek-flash`（核实于 2026-09-29，对应 V4.1 Flash），API 基地址默认 `https://api.deepseek.com`。如需更换同接口兼容模型，在 Variables 设置 `DEEPSEEK_MODEL`；不用 Google 服务账号。

## 3. PDF 所有权（必需）

额外添加 Secrets：

- `FEISHU_ADMIN_OPEN_ID`：接收所有权人员在新应用下的 open_id。
- `FEISHU_ARCHIVE_ROOT_FOLDER_TOKEN`：新的归档根文件夹 ID，机器人需有访问和写入权限。

在根文件夹下预先创建“六国洞察报告”子文件夹；名称可用 Variable `FEISHU_SIX_COUNTRY_FOLDER_NAME` 修改。代码只查找该子目录，不自动创建。

直接上传和归档上传都会移交所有权，并在重新读取元数据确认成功后才继续推送。文件保留在原位置，机器人保留完整管理权限；移交失败会终止当次推送。

## 4. 首次运行与定时推送

1. Actions → Seven-Country Daily Core → Run workflow → `operation=check`。只检查配置存在和基本格式，不验证真实 API 权限/余额。
2. 配置就绪后选 `operation=send`，会真实调用模型、上传 PDF 和推送飞书群。
3. 确认卡片、PDF 打开权限以及需要的所有权转移正常后，在 Variables 设置 `ENABLE_DAILY_PUSH=true`。
4. 后续每周五北京时间 08:30 执行（GitHub 可能延迟）；设为 `false` 即停止定时推送。

仅使用 Actions 不需要另建服务器或数据库。如果组织禁用了 Actions 或所用的 actions/checkout、setup-python、upload-artifact，需要组织管理员允许这些工作流使用的 Actions。

## 已完成的验证

56 项离线测试通过；GitHub Actions 会继续生成 WeasyPrint 样例 PDF 进行排版验证。更多运行边界见 README.md 和 docs/VALIDATION.md。

详细逻辑：docs/LOGIC.md；图：docs/daily-flow.png；可编辑图源：docs/daily-flow.mmd。
