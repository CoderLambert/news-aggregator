# 共享 LiteLLM Proxy 独立部署与运维

本目录是独立服务交付，不由 NewsHub Web/Worker Compose 启停。生产配置只有 LiteLLM Proxy 和它自己的 Postgres；合成 upstream、测试配置及恢复用数据库只通过测试 profile 启动。

## 固定镜像与本次验证范围

当前配置固定 `ghcr.io/berriai/litellm:v1.105.0@sha256:60947db020b57e204823d3fbc8bb295c85be890d7c9adcc77fb4f5fc2fe410b2`。版本在 2026-10-12 从 [官方 latest release](https://github.com/BerriAI/litellm/releases/latest) 解析为 v1.105.0；该 [官方 release](https://github.com/BerriAI/litellm/releases/tag/v1.105.0) 说明发行镜像用 Cosign 签名。OCI index 的实际 digest、平台 manifest、固定公钥验证和透明日志结果见 [T00-G 镜像证据](../../docs/features/byok/evidence/T00-gateway-v1.105.0-cosign.json)。同一镜像的 T00 受控 upstream 兼容探针为 `396 PASS / 0 FAIL`；该探针的整体状态仍是 `PARTIAL`，因为它不含旧业务回归和真实 provider 调用。

当前 T00 兼容探针仍复现 Chat streaming 正常 EOF 后缺少协议终态的原始风险（报告 §12：LiteLLM v1.104.2 与 v1.105.0 镜像均在 upstream 无终态 EOF 时合成 `finish_reason=stop` + `[DONE]`，与完整流不可区分）。本分支将拒绝策略收窄为一个有上游原始终态证据的例外：精确 alias `deepseek/deepseek-flash` 使用可信静态 `api_base: https://api.deepseek.com`，T04 明确传 `reasoning_effort=none`；它只在 LiteLLM `1.105.0`、原生 DeepSeek Chat parser、精确 Proxy `_UpstreamStreamBoundary` 与 pinned Router `FallbackStreamWrapper` 全部匹配时允许流式。`provider_key_guard.py` 在该 exact route 的 pre-call 准入处验证 Router 方法版本/签名并一次幂等安装窄包装，原样调用 LiteLLM 方法，只把原始 provider `CustomStreamWrapper` 作为私有 provenance 引用附到 Router 返回对象；whole-iterator hook 再严格验证该引用的类型/provider；同时，原生 DeepSeek parser 的实例级观察器在 LiteLLM 规范化前记录上游 JSON `choices[0].finish_reason == "stop"`，并只认精确 SSE `[DONE]` 传输标记。Router fallback 标记必须始终为 false，caller 请求级重试/备用模型被拒绝，静态 Proxy retries 为 0、fallbacks 为空；任何方法漂移、重复/外部替换、未知 wrapper 或 provenance 缺失都 fail-closed。终态仅在观察到上游 JSON `finish_reason=stop` 且 iterator 干净结束后释放；缺少上游 finish reason 时，EOF 或仅精确 `[DONE]` 均拒绝。有效终态之后仍校验允许的 usage-only chunk、解析错误和后续帧；遇到精确协议 `[DONE]` 时关闭持有的上游 response，不等待 TCP EOF。干净 EOF 在已验证 stop 后也可接受。异常和取消不会保存为完成。旧 `deepseek/deepseek-chat` 预设仅为存量 T02 配置保留，永不作为 T04 流式路由；其他 Chat alias、URL覆盖、多候选和工具调用仍 fail-closed；原生 Responses/Messages 流式协议保持 T00 既有行为，除非部署者通过显式 deny list 禁用。精确 alias 的端到端 SDK→Proxy→合成 upstream 与 Django T04 证明已加入完整 CI 候选，但**在这些测试和独立审查通过前不得将兼容性标作已验证**；旧 T00 结果仍为 `PARTIAL`，也不代表任何真实 provider 兼容。


非流式 Chat 也不能把归一化后的默认 `stop` 当作原始终态。`async_post_call_success_hook` 复用固定版本 LiteLLM 的请求私有 `Logging.model_call_details["original_response"]` 记录，拒绝缺失/空终态、重复 JSON 字段、错误响应、多个候选、归一化终态不一致，以及版本或记录来源不明的响应；错误只返回静态代码 `BYOK_COMPLETION_TERMINAL_UNVERIFIED`。明确的 `length` / `content_filter` 等非成功终态原样保留，由既有业务校验拒绝完成。原生 Responses/Messages 与 Flash 流式 guard 保留各自合同。不要关闭该回调或取消消息脱敏来绕过故障；代码/本地合成证据见[集中验收记录](../../docs/verification/consolidated-acceptance-2026-10-20.md)，生产与真实 Provider 另行验收。

## 部署边界

新增管理员 manifest 路由使用下面的独立严格合同；上面的 DeepSeek parser 合同仍只用于旧静态 alias。默认 `trusted-endpoints/manifest.json` 为 `[]`，不会发布无 Key 或内网服务。当前交付是代码与本地合成验证，尚未部署。

- Postgres 只在 Compose 的内部 `gateway` 网络内可达，没有宿主机端口映射。调用方容器只能加入 `byok-gateway-backend`，不加入 Proxy 的 `provider_egress` 网络。
- Proxy 的主机端口默认绑定 `127.0.0.1:4000`。同机反向代理可在本机终止 TLS；跨主机访问必须使用 TLS、上游鉴权和网络访问控制，不能把明文 Proxy 端口公开到公网。
- NewsHub、知序、TranslateFlow 等消费者分别持有不同 virtual key，并只允许对应项目的模型 alias。`LITELLM_MASTER_KEY` 只挂载给 Proxy 运维容器，不传给业务容器。
- `proxy.yaml` 不含任何 provider key。用户后端要在每个获准请求中显式传入当前用户的 provider key；缺失时准入回调返回静态错误码，且不访问 upstream。不得设置 provider 环境默认值或 fallback。
- 默认 key 额度为每日 `$5`、60 RPM、120000 TPM、最多 4 并发、最长 90 天。配置的预算和请求限制是应用层执行限制，不是 provider 账单绝对硬上限。
- `turn_off_message_logging`、异常消息脱敏、`store_prompts_in_spend_logs: false` 与 30 天 spend-log 保留一起启用。不要在 Admin UI 重新打开提示词存储。Docker JSON 日志按单文件 10 MB、每容器 5 个轮转。
- LiteLLM 默认重试为 0，无 fallback，无共享 cache。业务端 SDK 同样必须显式设为不自动重试；结果未知时由业务任务机制决定是否可重试。

## 安装秘密并启动

把秘密放到仓库外、受系统账户保护的位置；不要写入 `.env` 或提交到 Git。以下示例只把随机值写入文件，不回显：

```sh
sudo install -d -o root -g 1000 -m 0750 /etc/byok-gateway/secrets
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/byok-gateway/secrets/postgres_password'
sudo sh -c 'umask 077; printf sk- > /etc/byok-gateway/secrets/litellm_master_key; openssl rand -hex 32 >> /etc/byok-gateway/secrets/litellm_master_key'
sudo sh -c 'umask 077; openssl rand -hex 32 > /etc/byok-gateway/secrets/litellm_salt_key'
sudo chown root:1000 /etc/byok-gateway/secrets/*
sudo chmod 0440 /etc/byok-gateway/secrets/*
```

在受保护的运行目录创建只包含这些路径的 `.env`：

```dotenv
POSTGRES_DB=litellm
POSTGRES_USER=litellm
POSTGRES_PASSWORD_FILE=/etc/byok-gateway/secrets/postgres_password
LITELLM_MASTER_KEY_FILE=/etc/byok-gateway/secrets/litellm_master_key
LITELLM_SALT_KEY_FILE=/etc/byok-gateway/secrets/litellm_salt_key
PROXY_HOST_PORT=4000
GATEWAY_BACKEND_NETWORK=byok-gateway-backend
GATEWAY_EGRESS_NETWORK=byok-gateway-egress
PROVIDER_EGRESS_INTERNAL=false
```

在本目录执行：

```sh
docker compose --env-file /etc/byok-gateway/runtime.env config --quiet
docker compose --project-name byok-gateway --env-file /etc/byok-gateway/runtime.env up -d --wait
curl --fail --silent http://127.0.0.1:4000/health/readiness
```

生产运行不要启用 `test` 或 `restore` profile。启动输出、反向代理日志和监控告警不得采集 HTTP 请求正文、授权 header、容器 secret 文件内容或 shell tracing。

## 创建、轮换和撤销项目 virtual key

每个项目各自创建 key，显式设置 alias、model allowlist、预算和限流；创建返回的 key 只在获准的运维终端交给对应项目 secret manager。不要在终端历史、Issue、日志或仓库保存完整返回值。NewsHub key 的示例请求：

```json
{
  "models": [
    "openai/*", "anthropic/*", "deepseek/*", "gemini/*", "dashscope/*",
    "zai/*", "moonshot/*", "mistral/*", "groq/*", "xai/*", "openrouter/*"
  ],
  "key_alias": "newshub-prod",
  "max_budget": 5.0,
  "budget_duration": "1d",
  "rpm_limit": 60,
  "tpm_limit": 120000,
  "max_parallel_requests": 4,
  "duration": "90d"
}
```

NewsHub 的项目 key 只允许上述白名单路由；其中 Qwen 在 LiteLLM 内部使用 `dashscope/*`，但业务层不暴露 DashScope 直连选项。其他项目必须使用另一把 key 和自己的最小 model allowlist。轮换时先生成新 key，将其写入对应项目的 secret manager，部署并验证新 key，再撤销旧 key。轮换不改变用户 provider key；用户 provider key 由拥有该用户连接的业务后端加密并逐请求传递。

master key 仅用于 Proxy 管理 API，轮换它不会替换项目 virtual key。更换 Postgres 密码须先在 Postgres 内更新 role 密码，再原子替换 secret 文件并重启 Proxy。`LITELLM_SALT_KEY` 用于 LiteLLM 数据库加密材料；变更前须按版本兼容说明验证迁移和备份恢复，不能直接替换后碰运气。

## 可信地域连接

按 BYOK 原方案第 3 节，新增连接可明确选择 `glm_cn`、`glm_zai`、`qwen_beijing`、`qwen_singapore`、`kimi_international`。它们分别绑定 `zai/cn/*`、`zai/international/*`、`dashscope/beijing/*`、`dashscope/singapore/*`、`moonshot/international/*`。`proxy.yaml` 将这些别名交给 LiteLLM 既有 provider，并固定原方案的通用 API 端点；没有新增协议适配器、Coding/Token Plan 或任意 URL。

旧 `*_default` 身份/版本与原路由保留，不将已有 Key 静默切到新端点。变更地域须新建连接并重新提交 Key；应用层仍要求原模型白名单和本人/版本绑定的能力证明。该配置交付不代表模型能力或真实地域兼容已验收。部署时应核对 Proxy 配置与业务版本一致，并单独验证项目 key 的地域 alias 准入；本批未部署或修改任何真实 key。

## 管理员发布兼容端点

Web/Worker 的 `AI_BYOK_ENDPOINT_MANIFEST` 和 Proxy 必须读取同一份已验证内容。每条 profile 固定 `/v1` 目的地、协议 `chat_completions_v1`、精确允许 IP、认证模式和用户范围；普通用户不提供地址或 headers。私网、回环或 `none` 认证必须指定用户。容器中的 `same_host` 指 Proxy 自己所在的网络命名空间，不是用户浏览器所在机器。

受控发布前可离线生成配置（以下不启动服务，也不调用供应商）：

```sh
PYTHONPATH=../../backend/api/services python configure_trusted_endpoints.py \
  --manifest trusted-endpoints/manifest.json --base proxy.yaml --output /tmp/newshub-proxy-review.yaml
```

生成器验证整个 manifest，并以 0600 权限原子写出。入口脚本执行同一生成器；新路由形如 `newshub/<profile>-v<version>-<policy_digest>/*`，项目 virtual key 必须明确授权这些 alias。只有可信业务后端可持有项目 key，并写入 `metadata.newshub_owner_id/newshub_auth_mode`；它们不是面向浏览器的身份输入。带 Key 的请求仍显式携带本人 Key，`none` 必须显式传 null；不会继承环境 Key 或使用占位 Key。

新增或更改端点需提升 profile version、同步两端配置、受控重建 Proxy 并重新验证连接/模型；保存连接不触发注册。已有 alias 每次 admission、实际连接前和完成前重新读取当前 manifest。紧急撤销可原子替换目录内 manifest，将 profile 设为 disabled：Compose 挂载整个专用目录，避免单文件 bind mount 固定旧 inode。撤销阻止后续 dispatch/完成，不承诺收回已经发出的 token 或账单；重新启用必须发布更高 version，不能恢复旧身份。目录、文件和所有历史版本由管理员保护，不得混放 secrets。

新路由通过 LiteLLM 原生 CustomLLM 扩展复用其成熟 raw Chat adapter，不改变旧 provider parser 或全局实验开关。实际传输关闭环境代理、重定向、重试和 fallback；DNS 全部答案必须属于允许 IP，且只拨号第一个批准的字面 IP，保留原 Host、SNI 和 TLS 校验。请求只接受文本和 function tool 数据；媒体下载和内置联网工具在预处理前拒绝。响应不协商压缩，并拒绝非 identity Content-Encoding；正文/帧/整流分别有界。非流式校验原始 JSON，文本流要求原始 stop、精确 `[DONE]` 与干净 HTTP 正文结束才释放终态。工具仅允许非流式独立证明，不能将 tool_calls 当作最终文本完成。

连接层依赖精确版本 `httpx 0.28.1/httpcore 1.0.9`，漂移时关闭该路由。合成 TLS、取消和进程探针见[统一接入报告](../../docs/superpowers/reports/2026-10-21-newshub-unified-ai-access-v1.md)；本地 Python 进程证据不等于生产镜像、真实供应商或部署验收。

## 健康检查、备份、恢复和升级

- 运行健康检查：`GET /health/readiness`，该 endpoint 检查 Proxy 的 readiness；Postgres 是否可连接也以启动检查和运行日志确认。业务 SDK 遇到 Proxy 不可达时应清晰失败，不能直连 provider 或回退到平台 key。
- 维护 Postgres 加密磁盘与访问限制。备份命令通过 `docker compose exec -T db pg_dump -Fc ...` 将归档流写到受保护的备份位置；不要把 dump 上传到公开日志。异地副本须加密并使用独立凭据。
- 恢复必须落到隔离的新数据库/主机，先验证表结构、virtual key 的有效状态、配置版本和健康，再切换流量。记录实际 RPO/RTO。不要把新 schema 数据文件直接挂到旧版 Postgres image，也不要在原库上做未经验证的 schema 降级。
- 升级前保存 Postgres 备份、secret 版本、Compose/YAML、当前 image tag+digest 和验证结果；新版本先在隔离副本启动并跑配置验证、合成请求和恢复演练。只有经单独审核的 release tag+digest 才能修改镜像行。
- 升级失败时先停止流量，恢复升级前数据库备份到隔离数据目录，再启动原 image tag+digest；禁止仅把 Compose image 换回旧 tag 后直接复用可能已迁移的数据库。
- 本地 Docker JSON 日志最多保留 5 个 10 MB 文件；数据库 spend logs 配置为 30 天清理。备份保留期、加密密钥保留期及删除证明由运维保管制度单独设定。

## 本地合成验收

执行：

```sh
python3 tests/run_local.py
```

查看命令帮助不会启动容器；其他未知参数会在运行前报错：

```sh
python3 tests/run_local.py --help
```

脚本使用临时随机 master/project/provider key，provider egress 网络设为 internal，并只连接测试 upstream；它不读取用户密钥、不访问真实 provider。脚本会实际校验配置、Postgres 启动/恢复、两个受限 project key、独立 `curl` CLI、额度字段、错误 project key、未授权模型、缺 provider key、Chat stream 拒绝、usage 脱敏、Proxy 停止/重启和容器清理。测试密钥只存在于临时目录和内存，不打印到终端。

该脚本不替代真实 NewsHub Web/Worker 停止/重启验收、生产备份恢复、生产升级回退或 T13 provider 矩阵；这些结果必须按 T00-G 测试契约分开记录。真实 provider 请求保持 `NOT_RUN`。
