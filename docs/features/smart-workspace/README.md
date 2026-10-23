# NewsHub 阅读工作区与智能频道整理

实现分支：`feat/newshub-smart-workspace`；PR：[#56](https://github.com/CoderLambert/news-aggregator/pull/56)。本轮继承 #53 的前端基线，落实 #55 的智能分组需求。**开发与自动化检查由开发执行；实际产品、真实模型及桌面/移动端验收由用户执行。**

## 功能清单

| ID | 页面/入口 | 已实现的行为 |
| --- | --- | --- |
| W01 | 全站工作区 | 左侧阅读导航、个人快捷分组及实际频道数、移动导航抽屉、浅/深主题；既有账号、搜索、收藏、设置和后台入口保留 |
| W02 | `/` 首页 | 阅读列表布局、真实封面优先、来源/日期与摘要层级；原有搜索、阅读范围、地区、分类/来源、翻页、屏蔽撤销保持原逻辑 |
| W03 | 首页右栏 | 有站内阅读数据时展示近两日独立读者排序；无数据时明确为“最新更新”，不伪造热点 |
| W04 | 阅读统计 | 文章可见并停留三秒后按账号/文章/日期去重；今日、累计独立文章、连续天数、七日图；可清空本人记录 |
| W05 | `/channels` | 实际目录表格/卡片切换、全部/已订阅/未订阅、名称/简介/地区/主题/语言/类型筛选；选中后才出现批量操作 |
| W06 | 订阅管理 | 单条/批量订阅、取消订阅确认、受影响分组提示、停用源不能新订阅；已订阅按钮打开多分组设置 |
| W07 | `/channels/groups` | 两栏根/子树管理：创建/改名/删除空根，创建/改名/改挂/删除子分组；成员和阅读范围只使用子分组，改挂不改变成员 |
| W08 | 添加频道弹窗 | 输入网站或 RSS，匹配已登记来源；多频道时显式选择；未知地址提交待接入申请，不立即开启抓取 |
| W09 | `/channels/:id` | 主题、来源说明、语言/地区、类型、RSS、阅读策略、收录数量与最近文章；个人分组统一显示“根 / 子”路径 |
| W10 | `/channels/smart` | 分为“整理层级”和“整理频道”；前者建议现有子分组改挂，后者批量整理未分组或全部订阅并可建议最多八条新根/子路径 |
| W11 | 整理预览 | 逐项显示当前路径、建议路径和依据；可在确认前选择或调整，一次确认后原子应用，未确认不写层级或成员 |
| W12 | 应用/撤销 | 原子应用、重复提交幂等、结构/订阅/资料变化拒绝旧预览；层级撤销按版本恢复未被人工改动的子组，成员撤销只移除本次新增关系 |
| W13 | 新增订阅整理 | 可靠规则可加入已有子分组；AI 结果和首个根/子路径始终待确认，不代替用户订阅 |
| W14 | AI 任务 | 持久化状态、后台单次非流式结构化调用、最多两次尝试、429 有限退避、取消/刷新恢复、模型凭据或层级变化后拒绝旧任务 |
| W15 | 管理员后台分类 | 默认关闭；管理员显式授权本人模型与每日任务预算后，增量处理信息充足但主题未知的公开来源；不借用其他用户密钥 |
| W16 | 安全及运行 | 账号/根/子分组隔离、CSRF、账号切换请求栅栏、人工移除保护、只读模式、任务 lease/健康检查、独立 worker Compose 覆盖配置 |

## 设计图与实际数据的边界

- 示意图的文章、频道数、热度、阅读量、照片不是种子假数据：页面读取真实数据库，无封面时不生成假图片。
- 来源官网的不同频道可能有不同主题，例如站点里配置的专题频道不是整家媒体。主题推断与抓取/全文权限分开，AI 不能修改来源授权策略。
- 不展示未经校准的“92% 置信度”。界面明确显示目录规则、专题资料、人工确认或 AI 待确认。
- 标准主题是全站元信息；分组名称和归属始终属于个人账号。手动移除的归属不会被 AI 自动加回，需要用户在手动分组界面主动恢复。
- 任意未知 RSS 的自动联网验证、采集策略开通不在本轮：只提交接入申请，由管理员在已有采集体系中审核登记。
- 界面以中文为本轮完整交付语言。原有正文中英/双语显示和搜索模式继续保留；新工作区的完整英文界面不在本轮。

## 启动与回退

当前层级迁移为 `0085_channel_group_hierarchy`：新增 owner-scoped 根分类并把每个 owner 的既有子分组放入一个 `已有分组` 根分类；子分组 ID、成员、偏好、绑定、覆盖和历史记录保持不变。没有既有组的 owner 不创建空根，业务 SQLite 不纳入源码提交。

请先按现有流程备份数据库；不要删除数据库文件或其 WAL/SHM。不要使用 `git reset --hard` 清除本地数据库变更。确认工作树后从远端开发分支建立本地测试分支：

```bash
# 在已有仓库根目录；同名本地分支已存在时用 git switch 切换它。
git fetch origin
git switch -c test/newshub-smart-workspace origin/feat/newshub-smart-workspace
```

### 已有本地 Docker 开发环境

使用原 `.env` 与原数据目录，在完成备份后更新：

```bash
docker compose -f compose.yaml -f compose.workspace.yaml stop app crawler full-content indexer channel-worker
npm --prefix frontend ci
npm --prefix frontend run build
docker compose -f compose.yaml -f compose.workspace.yaml build app
docker compose -f compose.yaml -f compose.workspace.yaml run --rm --no-deps app python /app/backend/manage.py migrate
docker compose -f compose.yaml -f compose.workspace.yaml up -d app crawler full-content indexer channel-worker
docker compose -f compose.yaml -f compose.workspace.yaml logs --tail=80 channel-worker
```

地址仍为 `http://127.0.0.1:9527/`。手动整理要求既有 `PUBLIC_SITE_MODE=full`；AI 另外要求 `PUBLIC_AI_ENABLED=1` 与可用的个人 LiteLLM 连接。不要把 Key 写进仓库。

`channel-worker` 与开发 app 共享网络命名空间，保持原有回环网关信任边界。重建 app 后也应重建该 worker。开启 AI 前先在设置页检查现有模型连接；没有 Key 时使用资料推荐，不影响手动整理。

### 非 Docker 开发

使用该项目已经安装依赖的 Python 环境和原有环境变量：

```bash
python backend/manage.py migrate
RUN_MAIN=true python backend/manage.py channel_worker --once
# 单独终端以前台方式运行后台队列：
RUN_MAIN=true python backend/manage.py channel_worker
```

Web 服务和 Vite 沿用原有启动方式。`--once` 只处理当前一轮；长期处理需常驻 worker，不能把该命令当成自动启用守护进程。

### 生产环境

本轮没有部署生产。新增 `compose.workspace.prod.yaml` 继承生产 app 的不可变镜像、非 root 运行、数据库卷、回环网络和网关 secret；使用相同 Compose 项目名、显式环境文件及镜像版本，与 `compose.prod.yaml` 同时传入。现有发布/停止/回滚动作必须同时包括 `channel-worker`，不得让旧 worker 在应用回退后继续写库。

关闭管理员全站分类开关可立即阻止后续全站推理；停掉 worker 会让排队任务保持持久化。关闭 UI/worker 或回退前端不删除已有个人分组。撤销一次整理仅撤销新增关系，不删除生成的组或订阅。

## 模型与成本语义

个人主动 AI 整理：频道整理每次最多 40 个已订阅频道，可复用已有子分组或建议最多八条完整根/子路径，每个频道最多三个子分组；层级整理最多覆盖 20 个根和 200 个子分组。必须先预览并由用户确认后才创建路径、增加成员或改挂子分组。每任务最多两个模型尝试；上游可能已经收取一次中断请求费用，不能把任务幂等宣称为外部扣费严格恰好一次。

后台站点分类：管理员预算 1–20 个任务/日，按来源证据版本去重；只发送公开元信息和最多 12 个已收录标题。AI 结果必须通过允许主题、来源 ID、JSON 结构等校验。后续新增订阅的个人整理中，可靠规则可复用已有子分组；AI 匹配和新路径保持待确认。

## 自动化与人工验收

- 自动化：Django/pytest 覆盖元数据、预览、幂等、隔离、只读、CSRF、撤销、任务恢复和有限重试；Vitest 覆盖目录操作、预览编辑、请求栅栏和对话框交互。
- 人工：[MANUAL-ACCEPTANCE.md](MANUAL-ACCEPTANCE.md)。每项都保留待验收；CI 通过不等于页面或真实模型通过产品验收。
