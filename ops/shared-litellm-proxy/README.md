# 共享 LiteLLM Proxy 独立部署与运维

本目录是独立服务交付，不由 NewsHub Web/Worker Compose 启停。生产配置只有 LiteLLM Proxy 和它自己的 Postgres；合成 upstream、测试配置及恢复用数据库只通过测试 profile 启动。

## 固定镜像与本次验证范围

当前配置固定 `ghcr.io/berriai/litellm:v1.105.0@sha256:60947db020b57e204823d3fbc8bb295c85be890d7c9adcc77fb4f5fc2fe410b2`。版本在 2026-10-12 从 [官方 latest release](https://github.com/BerriAI/litellm/releases/latest) 解析为 v1.105.0；该 [官方 release](https://github.com/BerriAI/litellm/releases/tag/v1.105.0) 说明发行镜像用 Cosign 签名。OCI index 的实际 digest、平台 manifest、固定公钥验证和透明日志结果见 [T00-G 镜像证据](../../docs/features/byok/evidence/T00-gateway-v1.105.0-cosign.json)。同一镜像的 T00 受控 upstream 兼容探针为 `396 PASS / 0 FAIL`；该探针的整体状态仍是 `PARTIAL`，因为它不含旧业务回归和真实 provider 调用。

当前 T00 兼容探针仍复现 Chat streaming 正常 EOF 后缺少协议终态的原始风险。`provider_key_guard.py` 因此在到达 upstream 前拒绝 Chat streaming；其他请求路径不会因这个限制被暗中切到其他模型。响应、Messages 和非流 Chat 的 T00 证据也不代表任何真实 provider 兼容。

## 部署边界

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
  "models": ["news.deepseek-flash"],
  "key_alias": "newshub-prod",
  "max_budget": 5.0,
  "budget_duration": "1d",
  "rpm_limit": 60,
  "tpm_limit": 120000,
  "max_parallel_requests": 4,
  "duration": "90d"
}
```

Generic CLI 消费者要使用另一把 key，并将 `models` 限定为 `generic-cli.deepseek-flash`。轮换时先生成新 key，将其写入对应项目的 secret manager，部署并验证新 key，再撤销旧 key。轮换不改变用户 provider key；用户 provider key 由拥有该用户连接的业务后端加密并逐请求传递。

master key 仅用于 Proxy 管理 API，轮换它不会替换项目 virtual key。更换 Postgres 密码须先在 Postgres 内更新 role 密码，再原子替换 secret 文件并重启 Proxy。`LITELLM_SALT_KEY` 用于 LiteLLM 数据库加密材料；变更前须按版本兼容说明验证迁移和备份恢复，不能直接替换后碰运气。

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

脚本使用临时随机 master/project/provider key，provider egress 网络设为 internal，并只连接测试 upstream；它不读取用户密钥、不访问真实 provider。脚本会实际校验配置、Postgres 启动/恢复、两个受限 project key、独立 `curl` CLI、额度字段、错误 project key、未授权模型、缺 provider key、Chat stream 拒绝、usage 脱敏、Proxy 停止/重启和容器清理。测试密钥只存在于临时目录和内存，不打印到终端。

该脚本不替代真实 NewsHub Web/Worker 停止/重启验收、生产备份恢复、生产升级回退或 T13 provider 矩阵；这些结果必须按 T00-G 测试契约分开记录。真实 provider 请求保持 `NOT_RUN`。

2026-10-12 的本地验收结果为 **26 PASS / 0 FAIL**，涵盖两个隔离项目 key、合成上游 provider-key 路由、拒绝路径、usage 脱敏、Proxy 重启和 Postgres 隔离备份恢复。精确基线、实现 SHA、Docker/Compose 版本和每项未验证边界记录在 [T00-G 测试证据](../../docs/features/byok/tests/T00-gateway-service.md)；整卡状态仍为 **PARTIAL**，不代表生产 go-live 或 provider 兼容。
