# BYOK T00 本地协议探针

本目录补上主线缺少的真实官方 SDK → LiteLLM Proxy → 合成 HTTP 上游验证入口。复用 PR #33 的受控上游与协议场景，以及主线 `ops/shared-litellm-proxy/provider_key_guard.py`；不引入业务 provider adapter、业务迁移或 T00-G 运维配置。

任务依据沿用原 [Task T00](https://github.com/CoderLambert/news-aggregator/blob/ed58afa7a72ae905e2a2ffc315d968ca3634b8f2/docs/features/byok/tasks/T00-sdk-protocol.md) 和 [Test T00](https://github.com/CoderLambert/news-aggregator/blob/ed58afa7a72ae905e2a2ffc315d968ca3634b8f2/docs/features/byok/tests/T00-sdk-protocol.md)。实现基线为 `2e3254c890f52af626aa7d2400097301bf550d14`。当前交付为 **T00 PARTIAL**：下列本地进程检查通过，也不代表原合同要求的历史镜像验收完成。

## 安装与执行

使用 Linux、Python 3.12 和可用的 Node.js。客户端与 Proxy 使用两个虚拟环境：客户端锁定 OpenAI 3.28.0 / Anthropic 1.13.0 / httpx2 2.13.1；LiteLLM 1.105.0 自身要求另一范围的 OpenAI 依赖，因此只通过真实 HTTP 连接两端。独立锁文件包含各自完整的依赖版本，不修改业务依赖。

在仓库根目录执行：

```bash
task_env="$(mktemp -d /tmp/byok-t00-env.XXXXXX)"
python3.12 -m venv "$task_env/sdk"
python3.12 -m venv "$task_env/proxy"
"$task_env/sdk/bin/python" -m pip install -r tools/byok_t00_probe/requirements-sdk.lock
"$task_env/proxy/bin/python" -m pip install -r tools/byok_t00_probe/requirements-proxy.lock
"$task_env/proxy/bin/python" tools/byok_t00_probe/prepare_proxy.py
"$task_env/sdk/bin/python" -m unittest discover -s tools/byok_t00_probe -p 'test_*.py'
"$task_env/sdk/bin/python" tools/byok_t00_probe/probe.py \
  --proxy-python "$task_env/proxy/bin/python" \
  --report /tmp/byok-t00-report.json
rm -rf "$task_env"
```

`prepare_proxy.py` 仅下载 Prisma 的官方依赖并生成其客户端，使用无效的本地占位 DSN，不连接数据库。该准备阶段可使用执行环境的网络代理与 CA 配置，不输出它们的值。随后协议运行阶段清空继承环境，不读取现存 provider Key、数据库 URL、HTTP 代理或 dotenv 配置。

只验证 SDK 时可运行 `probe.py --sdk-only --report /tmp/byok-t00-sdk.json`；此时 `PROXY_PROCESS_LOCAL=NOT_RUN`。`--report` 支持自定义路径；不提供外部 Proxy、上游、真实数据库或真实厂商参数。帮助与未知参数检查在启动服务前完成。

## 本地链路与安全边界

每次执行创建三个本地端点：受控 HTTP 上游、固定版本 LiteLLM 进程、全新的 PostgreSQL 临时集群。`pgserver==0.1.4` 提供 PostgreSQL 二进制，`prisma==0.15.0` 仅向该新集群创建 LiteLLM 自己的表。探针生成随机合成 provider Key 和管理 Key，通过真实 `/key/generate` 获取两组项目 virtual key，并配置互不相同的模型权限。

SDK URL 必须是数值 loopback HTTP 地址，SDK `trust_env=False`、`max_retries=0`；Proxy 固定本地模型地址、`num_retries=0`、无 fallback，并复用主线 provider Key guard。Python socket audit 拒绝外部连接与 DNS 查询，Uvicorn 显式使用标准 `asyncio`，避免 `auto` 选择不经过 Python socket audit 的 uvloop。该约束覆盖探针的 Python HTTP 路径；本交付没有运行容器网络命名空间或操作系统级全进程出口防火墙。

PostgreSQL 必须以非 root 运行。root 场景使用系统已有的 `nobody`，将 bundled PG 及相对路径动态库复制到本次独占的临时目录，不修改虚拟环境或用户父目录权限。启动失败、正常退出和 SIGTERM 都进入清理：关闭 SDK/流，终止本次创建的进程组及其后代，再删除本次临时集群和日志。逐项清理失败会使范围检查失败，不以主进程已经退出代替后代退出证据。

## 原合同覆盖范围

| 原 Test | 本次进程验证与明确边界 |
| --- | --- |
| T00-01 | 三协议非流式完整文字和两轮工具终态；SDK 直连三协议流式完整终态；经 Proxy 的 Responses / Messages 流式完整终态。 |
| T00-02 | SDK 三协议及 Proxy Responses / Messages 的 EOF、原生不完整终态；Proxy Chat 流式沿用现有 guard 返回 400，且上游请求为 0（含原始 JSON 字符串/数字 `stream` 标志的 EOF 命名变体；`"t"`/`"y"` 大小写别名亦强制拒绝）。这是失败关闭通过，不是 Chat 流式成功兼容。 |
| T00-03 | HTTP 503、超时、截断 body；可用流式路径的流内 error / `response.failed`；仅记录错误类型、状态码和终态，不输出正文。 |
| T00-04 | 半截参数、非法 JSON、非法参数形状及非白名单工具；以实际 dispatch 计数为 0 证明拒绝，失败发生在已经派发之后不能通过。 |
| T00-05 | 三协议两轮工具往返与完整最终回答；原始 Chat assistant / reasoning、Responses output items、Messages thinking / signature 回送事实；公开输出不包含私有 continuation 或 Key。 |
| T00-06 | 两组真实项目 virtual key、不同合成 provider Key 和模型，在 Chat / Messages 四个并发请求中隔离；检查上游实际模型、协议、凭据归属与时间重叠。Responses 有独立的鉴权和模型权限拒绝用例，未扩大为所有协议的并发矩阵。 |
| T00-07 | 正常、错误、取消后的 SDK / HTTP / 流关闭，上游生产者退出，本次 Proxy / PostgreSQL 进程组清理；含 leader 提前退出但后代存活、清理竞态及流创建/读取阶段中断的负控。 |
| T00-08 | 缺失、空白、非字符串 provider Key，错误项目 Key，项目无权访问的模型均在上游前拒绝；检查部署 sentinel 和项目 Key 未被当成用户 provider Key。 |
| T00-09 | 逐用例 0 / 1 次实际上游请求；所有记录必须属于已声明场景，总数精确闭合；额外未知请求、重复请求、错误模型不能通过。 |
| T00-10 | **NOT_RUN**：原合同固定的 LiteLLM 1.104.2 镜像、digest / 签名和原始 EOF 对照未执行。1.105.0 的 Python 进程检查不能替代该项。 |

`SDK_LOCAL` 与 `PROXY_PROCESS_LOCAL` 分别报告，后者有意区别于原合同的镜像级 `PROXY_LOCAL`。报告中的 `facts.success` 表示 SDK 调用或迭代没有抛出异常；每个检查还单独判断原生终态，不能用该字段证明业务答案完整。空范围、未完成的运行及共享资源关闭失败均不能得到 PASS。

## 本轮证据

2026-10-17 在 Python 3.12.14 上执行，负控单元测试 **24 PASS**，真实 SDK / Proxy / 临时 PostgreSQL 合成矩阵 **207 PASS、0 FAIL**。其中包含 root 用户下 Proxy 虚拟环境为 `0700` 的运行条件。CLI 输出实际 SDK、Proxy、pgserver、Prisma 与 Python 版本；JSON 报告保存脱敏的终态、计数和关闭事实。检查数只记录该次执行结果，不作为可调整旧测试预期计数的理由。

独立负控覆盖不完整最终答案、非法工具已派发、错误模型路由、未登记额外请求、空范围假通过、关闭失败及 SIGTERM 中断资源泄漏。原业务测试、原计数与 skip 范围均未修改。

历史镜像验签 / Docker 对照、真实厂商调用、真实用户 Key、生产数据库、生产部署、T00-G 运维交付与最终人工验收均 **NOT_RUN**。本探针通过不能把 T00 改为 DONE / ACCEPTED，也不替代后续 T13 产品矩阵。
