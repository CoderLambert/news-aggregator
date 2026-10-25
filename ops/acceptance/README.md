# NewsHub 引导式 UAT（headed Playwright）

面向操作者在本机 **有界面** 走查关键产品能力：登录、深度研究、文章翻译、语音生成、小闻问答、模型配置（含 DeepSeek 文本/工具验证）。

风格对齐 `ops/rss/T27` 的真实 SPA Playwright 用法，但本脚本默认 **headed + 分段暂停**，方便人工观察。

## 一键启动（推荐）

在仓库根目录执行：

```bash
./ops/acceptance/run_guided_uat.sh
```

脚本会自动：定位仓库根 → 选择已装 Playwright 的 Python → 从环境变量或 `ops/acceptance/.env.local`（或 `~/.config/newshub/acceptance.env`）加载凭据 → 探测 `NEWSHUB_BASE_URL`（默认 `http://127.0.0.1:9527`）→ 以 headed + 中文分段暂停启动 `guided_uat.py`。额外 CLI 参数会原样传给 Python 脚本。

本地凭据文件示例（**勿提交**；仓库根 `.gitignore` 已忽略任意路径的 `.env.local`）：

```bash
# ops/acceptance/.env.local
NEWSHUB_ACCEPTANCE_USER=admin
NEWSHUB_ACCEPTANCE_PASSWORD=你的本地密码
# 可选：
# NEWSHUB_ACCEPTANCE_DEEPSEEK_KEY=sk-…
```

也可复制模板：`cp ops/acceptance/.env.local.example ops/acceptance/.env.local`。

若运行时未启动，脚本会打印中文启动提示后退出（不会自动 `down -v` / recreate）。

## 前置

- 本机已启动 `newshub-local-main`（默认 `http://127.0.0.1:9527`）
- Python 3.10+，已安装 Playwright：

```bash
python3 -m pip install 'playwright>=1.40'
python3 -m playwright install chromium
# 或使用系统 Chromium：NEWSHUB_ACCEPTANCE_CHROMIUM=/usr/bin/chromium
```

## 环境变量

| 变量 | 必填 | 说明 |
|------|------|------|
| `NEWSHUB_BASE_URL` | 否 | 默认 `http://127.0.0.1:9527` |
| `NEWSHUB_ACCEPTANCE_USER` | 是* | 登录用户名（本地常见 `admin`） |
| `NEWSHUB_ACCEPTANCE_PASSWORD` | 是* | 登录密码；**勿写入仓库** |
| `NEWSHUB_ACCEPTANCE_DEEPSEEK_KEY` | 否 | 有则在「模型配置」里替换 DeepSeek Key 并跑文本/工具探针；缺失则软跳过付费探针 |
| `NEWSHUB_ACCEPTANCE_CHROMIUM` | 否 | Chromium 可执行文件；默认走 Playwright 自带 |
| `NEWSHUB_ACCEPTANCE_PAUSE` | 否 | `1`（默认）每大段结束等待回车；`0` 自动连跑但仍 headed |
| `NEWSHUB_ACCEPTANCE_SLOW_MO` | 否 | 毫秒级放慢，默认 `400` |
| `NEWSHUB_ACCEPTANCE_ARTICLE_PATH` | 否 | 翻译/语音/小闻用的文章路径，如 `/news/123`；缺省时自动点首页首条 |

\* 仅「登录」及后续登录态步骤需要。未设置时脚本会停在登录段并提示。

## 运行（手动）

优先使用上方一键脚本。若需手动：

```bash
cd /path/to/news-aggregator   # 或本 worktree
export NEWSHUB_ACCEPTANCE_USER=admin
export NEWSHUB_ACCEPTANCE_PASSWORD='…'   # 本地密码，勿提交
# 可选：export NEWSHUB_ACCEPTANCE_DEEPSEEK_KEY='sk-…'
python3 ops/acceptance/guided_uat.py
# 或：./ops/acceptance/run_guided_uat.sh
```

无暂停连跑（仍打开窗口）：

```bash
NEWSHUB_ACCEPTANCE_PAUSE=0 python3 ops/acceptance/guided_uat.py
```

## 段落

1. 登录  
2. 深度研究（打开研究助手面板）  
3. 文章翻译（进入文章，定位「全文翻译」）  
4. 语音生成（「选择语音播报方式」）  
5. 小闻问答（「询问 AI 助手小闻」）  
6. 模型配置（`/settings/ai`，DeepSeek「测试文本能力」「测试工具能力」）

付费/密钥相关步骤在密钥或控件缺失时 **软失败并继续**，不会硬退出整场 UAT（退出码：全绿 `0`，有软失败 `2`，登录等硬失败 `1`）。

## 安全

- **禁止**把 API Key / 密码写进本目录或提交进 git。
- 脚本不会 `print` Key；替换 Key 只走产品已有 UI/表单。
- 验收探针也可用产品 API（`/api/me/ai/.../probe/`）；本引导脚本侧重可视走查。
