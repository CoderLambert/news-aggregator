# Test T00-G · 共享 LiteLLM Proxy 运维交付契约

> **PARTIAL**：独立服务配置与本地合成运维闭环已实现并通过；生产部署、真实 NewsHub Web/Worker 生命周期、升级回滚和真实 provider 仍未执行。

对应：[T00-G Task](../tasks/T00-gateway-service.md)。

| 用例 | 场景 / 故障注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T00G-01 | 校验官方镜像发布、签名/证明、版本和 OCI digest | 固定官方 release tag+digest；Cosign claims、签名及透明日志验证通过 | PASS |
| T00G-02 | Proxy / Postgres 单机启动和错误配置 | Compose 配置检查、Proxy/Postgres 启动及 readiness 检查通过 | PASS（本地合成环境） |
| T00G-03 | 每项目独立受限 virtual key | NewsHub/CLI 使用不同 key 和模型 allowlist；额度字段已配置，额度阈值和并发压测未执行 | PARTIAL |
| T00G-04 | Proxy master key 与业务运行环境检查 | master key 仅挂载到 Proxy；合成消费者容器未获得 secret/env | PASS（本地合成环境） |
| T00G-05 | 请求无 provider Key、无效 Key 或 Proxy 不可达 | 缺 provider key、错误项目 key、未授权模型及 Proxy 停机均 fail closed；无 fallback | PASS（本地合成环境） |
| T00G-06 | 日志、回调、异常和指标脱敏 | 合成日志、usage 日志及备份不含测试 key 或提示词 | PASS（本地合成环境） |
| T00G-07 | 重启、Postgres 备份与隔离恢复演练 | 合成数据库备份及隔离恢复通过；结果不代表生产 RPO/RTO | PARTIAL |
| T00G-08 | 固定版本升级失败与回滚 | 生产数据库兼容性、升级失败注入和版本回退未执行 | NOT_RUN |
| T00G-09 | 网关停机期间 NewsHub 运行 | 未启动真实 NewsHub Web/Worker；产品阅读与已存历史回归未执行 | NOT_RUN |
| T00G-10 | 真实厂商请求门禁 | 本卡未调用任何真实 provider；T13 兼容矩阵仍未验证 | NOT_RUN |
| T00G-11 | 第二个独立通用 CLI 消费者与 NewsHub 启停隔离 | CLI 独立 key、allowlist、usage 区分和 Proxy 重启恢复通过；真实 NewsHub 生命周期未执行 | PARTIAL |

## 执行证据

| 项目 | 结果 |
| --- | --- |
| 本卡状态 | **PARTIAL**；本地合成服务/运维链路通过，尚不具备生产 go-live 或 provider 兼容结论 |
| 基线 HEAD | `origin/feat/byok-user-api-keys`：`3cd584c95acd52bc533bba0b55eab75b35c41ad5` |
| 实现 SHA（最新复测代码） | `6140489c3a3eabf1b259d7d51c3734fcc1d71776`；包含测试入口参数校验与无副作用 `--help` |
| PR #35 | open / Draft；base `feat/byok-user-api-keys`，实现 head `6140489c3a3eabf1b259d7d51c3734fcc1d71776` 的两组 frontend/backend-and-release-gates 均通过；runs [38174227321](https://github.com/CoderLambert/news-aggregator/actions/runs/38174227321)、[38174232182](https://github.com/CoderLambert/news-aggregator/actions/runs/38174232182)，backend 各 `838 passed / 2 warnings` |
| 执行命令 | `python3 ops/shared-litellm-proxy/tests/run_local.py`；另执行 `python3 ops/shared-litellm-proxy/tests/run_local.py --help` 和 `cd ops/shared-litellm-proxy/tests && /tmp/byok-t00-smoke-20261012/bin/python -m unittest -v test_runner_cli` |
| 执行环境 | Python 3.14.8、Docker 29.7.2、Docker Compose 5.5.1、Postgres 16 Alpine；OS 发行版未采集 |
| Proxy 镜像 | `ghcr.io/berriai/litellm:v1.105.0@sha256:60947db020b57e204823d3fbc8bb295c85be890d7c9adcc77fb4f5fc2fe410b2` |
| 镜像签名/摘要 | **PASS**；Cosign v3.0.2 验证 1 个签名，claims 有效，签名匹配固定公钥，claim digest 与 OCI index 一致；[完整机器可读证据](../evidence/T00-gateway-v1.105.0-cosign.json) |
| 本地测试结果 | **26 PASS / 0 FAIL**；最新启动 22.0 秒；Compose profiles 清理成功。CLI safety 单测另为 `2 passed`，`--help` 输出 usage 且不调用 Docker |
| 配置与健康检查 | `docker compose config --quiet` 通过；Proxy 与 Postgres 启动成功；`/health/readiness` 返回 200 |
| 项目 key / allowlist | `newshub-test` 和 `generic-cli-test` 使用不同虚拟 key；各自显式 provider key 请求均返回 200；跨项目模型请求在上游前返回 403 |
| fail-closed | 缺 provider key 返回静态 400；错误项目 key 返回 401；Chat streaming 返回静态 400；以上请求未触达合成上游 |
| provider key 隔离 | 合成上游收到各自匹配的 provider key；未收到项目 key、master key、其简单 SHA-256 或请求体 provider key |
| usage / 脱敏 | 6 条 usage 行可区分 `newshub-test` 与 `generic-cli-test`，合计观察到 20 tokens；容器日志和 usage 数据无测试 key 或提示词 |
| Proxy 生命周期 | 停止 Proxy 后新请求连接失败；Proxy 重启后通用 CLI 请求恢复为 200；未启动 NewsHub Web/Worker 容器 |
| 本地备份恢复 | 最新备份 257,067 bytes，SHA-256 `7c439f2bf10ac920d830bca619a898efa82733453f4a2edc39136a5acc0baaaf`；隔离恢复 1,732.79 ms；恢复 `LiteLLM_SpendLogs` 和 `LiteLLM_VerificationToken` 两表，共 6 条 spend rows |
| PROVIDER_REAL | **NOT_RUN**；没有真实 DeepSeek 或其他供应商请求 |
| 业务回归 / 用户 UAT | **NOT_RUN**；真实 NewsHub Web/Worker 阅读、历史和断网行为未覆盖 |
| 未验证项 | 生产部署与访问控制、生产密钥轮换、生产 RPO/RTO、升级/回滚、阈值/并发压测、NewsHub 生命周期、T13 provider 矩阵及 T14 发布验收 |

### 当前工作区复测（2026-10-12）

从仓库根目录运行 `python3 ops/shared-litellm-proxy/tests/run_local.py`；结果 **26 PASS / 0 FAIL**，status `PASS`，upstream 合成请求 2 次，`provider_real=NOT_RUN`。固定 LiteLLM v1.105.0 与 Postgres 16 镜像均按 digest 启动；两个项目 alias、两条显式 provider key 路由、未授权模型/缺 key/错误项目 key/Chat streaming 拒绝、usage 脱敏、Proxy 停止/恢复及隔离数据库备份恢复均通过。最终只清理随机项目 `byok-t00g-*`；清理后未发现该项目前缀的容器，既有 NewsHub 和其他项目容器仍保持运行。

补充执行 `python3 ops/shared-litellm-proxy/tests/run_local.py --help`，确认只输出参数帮助，不启动容器；`test_runner_cli` 的 2 项单测验证 `--help` 与未知参数都在调用 Docker/创建测试状态前退出。此修复避免把查询帮助误当作执行入口，实际无参数路径的完整合成验收已在同一代码版本复跑。

前一 PR #35 head `d10ba1c14e41e1fcdb5bc1eff1747a06ef2aa279` 的一份 run 出现既有 `test_sse_disconnect_does_not_cancel_background_worker` SQLite `OperationalError`（837 passed / 1 failed），同一 SHA 的另一完整 CI run 为 838 passed / 2 warnings。当前 CLI guard SHA `6140489c3a3eabf1b259d7d51c3734fcc1d71776` 的两组完整 CI 均已通过；该代码只影响本地测试脚本参数解析。

### 断言修正记录

首轮有效合成请求失败源自测试上游的 fingerprint 查找逻辑：runner 只提交 provider key 的 SHA-256，upstream 却把该 fingerprint 再哈希后用于原始 key 匹配。当前夹具直接用收到的 fingerprint 建立查找表，并单独保留二次哈希用于检测误传 fingerprint。修正后 HTTPX 出站请求和合成 upstream 均确认使用匹配的 request-scoped provider key；生产配置没有 provider 默认 key。

不得把本地合成验收、T00 风险复现夹具或镜像签名验证视为真实 provider 兼容、NewsHub 产品验收或生产 go-live。
