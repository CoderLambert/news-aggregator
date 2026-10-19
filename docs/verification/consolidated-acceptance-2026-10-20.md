# 开发批次集中验收记录

本批基线为 `main@703af0f161119374593b79325165b3f42a69b198`。验收隔离工作树为 `/tmp/newshub-consolidated-acceptance-20261020`，原始日志保存在 `/tmp/newshub-acceptance-703af0f/reports/`。本记录不代表生产发布或六厂商真实验收完成。

## 已确认并修正的问题

- T02 手填模型最多 160 字符，实际探测路由允许 240 字符，但审计模型字段仍为 80。新增回归使用合法的 160 字符模型 ID，经创建、显式探测和完整 alias 校验；修复前确实失败于 Django 字段验证（169 > 80）。`0072` 前向迁移将审计 alias 扩为 240，保留已有模型和回执身份，不改历史迁移或截断 ID。
- AG-01/AG-05 的五项旧回归仍 mock 已移除的个人客户端入口。现复用连接创建与显式探针 API，取得当前 T03 模型快照，在实际 gateway 构造边界替换合成响应。保留目录 GET 无网络/无模型/无写入、推理前标题变化零调用、推理中标题变化不得提交等原断言。
- 公共 capability 固定 schema 补入已合并的 `research_byok_create`，继续检查关闭状态与无秘密数据。研究门禁分别验证 AI 关闭时 403、AI 开启但 hosted 未批准时 503，两种情况均不得创建运行或会话。

## 实际检查

| 检查 | 当前结果 | 范围与限制 |
|---|---|---|
| 第一轮完整后端 | FAIL：串行 85 passed；并行 2576 passed / 9 failed / 16 skipped | 七项旧合同/fixture 失败如上；另两项分别是 root 身份使 user-mismatch 假设失效，以及未挂载 Docker daemon 导致真实 context 测试无法运行。保留首次失败日志 |
| 修复前定向回归 | 47 passed / 1 failed | 长 alias 负例真实失败，其余迁移后的合同及 CI 非 root 身份测试通过。日志 `acceptance-fixes-red.log` |
| 修复后完整后端（SDK 权限未补齐） | FAIL：串行 85 passed；并行 2585 passed / 1 failed / 16 skipped | 只剩非 root 用户无法读取先前 SDK 目录、导致 Anthropic 导入失败；真实 Docker context 与原九项失败均已通过。日志 `backend-fixed-full.log` |
| SDK 权限补齐后的完整后端 | PASS：2671 passed / 16 skipped；2687 个收集/执行身份完全对账 | 原 `ops/ci/benchmark-xdist.sh`：串行 85、并行 2586 passed / 16 skipped，完整轮次 187 秒，退出 0。日志 `backend-fixed-sdk-full.log`；保留原串行清单、两个 worker、断言及 skip 预算 |
| 完整前端 | PASS：105 文件 / 730 用例 | Node 22，typecheck、lint、完整 Vitest 与 build；一条已有 hooks lint warning。源码与本修复的后端差额无前端变更 |
| T00 SDK/Proxy 协议 | PASS：239 / 239 | 原 `probe.py`，官方 SDK→固定 LiteLLM 1.105.0→合成 HTTP 上游；临时 PostgreSQL，零真实 Provider。另有探针 unittest 37 项、Key guard unittest 27 项通过 |
| CI 工具契约 | PASS：50 用例 | 原 `ops/ci/tests` unittest discovery |
| 后端依赖锁 | PASS：160 个安装版本 | 只读既有 Python 3.12 缓存，补齐现成 SDK 包；没有向共享环境安装 |
| 基线生产候选镜像 | PASS | `newshub:accept-703af0f`，release label 为上述基线；修复后最终镜像/G1 另记，不把旧镜像当作最终候选 |
| 标准 G1 probe 镜像构建 | FAIL：Chromium CDN 下载超时 | 原失败日志保留，没有修改仓库 Dockerfile |
| 缓存版 G1 probe 镜像 | PASS（构建） | 仅临时 Dockerfile 将浏览器下载改为复制现有 Chromium 1234，仍安装原 Playwright 1.62.0 及系统依赖；实际 G1 尚未执行 |
| GitHub CI | NOT_RUN | 核对时两个 self-hosted runner 均 offline；沿用用户授权的 `[skip ci]` 集中验证，不伪造 merge-gate 成功 |

后端使用 Python 3.12、UID:GID 1001:121、临时 SQLite 与合成凭据。SDK 权限问题确认后，仅将四个公开 Anthropic/docstring-parser 包目录复制到本次私有目录供该 UID 读取，没有修改原 SDK/共享缓存权限；预检确认 Anthropic 1.13.0、OpenAI 3.31.0。Docker context 用例只创建/删除随机命名的测试镜像和未启动容器；没有真实数据库、生产目标或收费模型调用。后端完整运行通过后须保留动态收集/执行身份对账结果，不能只相加 pytest 的显示计数。

## 后续验收边界

最终镜像、隔离 G1 与新授权的 DeepSeek 有界调用尚待完成。其他厂商真实 Key、来源质量/许可判断、人工产品体验与延期的生产门禁仍须分别列明，不能以此报告替代。生产切换、停止旧角色及依赖该前置的旧栈删除继续延期。

缓存浏览器来源固定为现有 CI 镜像 `sha256:666633c9799531b12f4be1525bf6679040a89b52fe0d1efa3e0e9a33923faae6`；缓存版 probe 镜像 ID 为 `sha256:10be5998a22e7b6ee23692f46f63a8e3be267af67d9f3f887ab17935864ee775`。临时 Dockerfile 和构建日志保留在验收目录，仓库正式构建入口不变。

T00 使用独立新建的 Python 3.12.14 SDK/Proxy 环境，按原两份锁文件安装，未修改共享依赖。依赖准备完成后以 Node 22.23.3 重新生成并确认 Prisma；协议运行清空继承环境，只连接临时本地服务。原始结果为 `/tmp/newshub-t00-acceptance-20261020/report.json`，日志 `t00-full.log`。原报告明确保留历史镜像/验签、真实 Provider 和 UAT 为 NOT_RUN，239 项通过不替代这些门禁。
