# 公开 RSS 来源默认开启正文自动提取

本次按用户后续明确要求，恢复并持久开启全局全文能力。单个受限来源不再导致全局关闭。只更新本地运行环境，未部署生产，未调用模型或额外搜索服务。

## 实现与当前行为

- `backend/newsaggregator/settings.py`：`RSS_FULL_CONTENT_ENABLED` 未设置时默认 `1`。
- `backend/api/rss/engine.py`：环境默认及 `EngineConfig` 默认均开启；显式 `0` 仍能关闭，其他非法值仍拒绝。
- `compose.rss.prod.yaml`：应用与 RSS 同步服务模板统一默认 `1`。修改模板不代表已部署生产。
- `.env.example`：明确默认开启和显式关闭方式。
- 复用现有订阅策略。普通且许可的公开文章默认 full_content；原生全文 Feed 保持直读；受限/非文章来源不扩大权限。已存在的手工直读模式不被全局默认覆盖。
- 提取仍在 Miniflux 正常采集阶段发生，阅读页和聊天不增加抓取；提取成功不自动标记“已确认全文”。

## 本地生效证据

运行项目 `newshub-local-uat`，配置目录 `/home/lambert/.local/share/newshub/uat-20261020`。

- 应用 `settings.RSS_FULL_CONTENT_ENABLED=True`。
- 同步服务 `settings.RSS_FULL_CONTENT_ENABLED=True`，`EngineConfig.from_environment().full_content_enabled=True`。
- `https://v8.dev/blog.atom` → full_content / ordinary_public_article。
- `https://webkit.org/feed/` → feed / observed_native_feed。
- `https://rss.arxiv.org/atom/cs.AI+cs.LG+cs.CL` → feed / non_article。
- 本地已有唯一 Miniflux 订阅 The Verge 保持 feed，策略版本 4/4、ready；其来源限制不会关闭其他来源的全文能力。
- HTTP readiness 200；应用与 RSS 同步服务均 healthy。

本地镜像分别为 `newshub:local-rss-default-on-20261020`、`newshub:rss-default-on-20261020`。基于当前运行镜像只叠加 `settings.py` 和 `engine.py`，保留应用已有未合入的其他代码和界面修复。应用原有 settings 与仓库基线不同，已从运行镜像提取后仅修改目标默认值，未覆盖无关配置。

`app.env`、`translation-redis.app.env` 和 `rss-body-recovery.override.yaml` 均持久写入 `RSS_FULL_CONTENT_ENABLED=1`。没有更改已有订阅、正文或用户关系，没有增添随机测试订阅。

启动仍使用：

```sh
cd /home/lambert/.local/share/newshub/uat-20261020
docker compose -p newshub-local-uat -f compose.yaml -f translation-fix.override.yaml -f rss-body-recovery.override.yaml up -d --no-deps app rss-sync
```

## 验证

独立工作区 `/tmp/newshub-rss-body-recovery-20261020`，HEAD/base `8f7fed66cb66bdccc88bd2dd95f8f96e4a3288c2`，包含上一轮尚未提交的任务改动；原工作区及数据库未动。当前变更未提交或推送；远端 CI 为 NOT_RUN。

在 Python 3.12 的现有镜像中使用 `--network none`、独立源码只读挂载和容器 `/tmp` 合成数据库，不挂载真实配置、凭据和数据。

```sh
python -m pytest -c pytest.ini -p no:cacheprovider -q \
  backend/api/tests/rss/test_engine_adapter.py \
  backend/api/tests/rss/test_feed_policy.py \
  backend/api/tests/rss/test_subscriptions.py \
  backend/api/tests/rss/test_control_worker.py \
  backend/api/tests/rss/test_sync_reconciliation.py \
  backend/api/tests/rss/test_policy_http_errors.py \
  scripts/deploy/tests/test_rss_runtime.py
```

PASS：239 项，32.41 秒。覆盖默认开启、显式关闭、非法值、新订阅与引擎 crawler 策略、原生全文、受限来源、共享模式、控制任务/未知结果、限流、同步回写及部署模板一致性。

新增默认配置回归在修改前 5 项 FAIL，修复后 PASS。原始日志 `/tmp/newshub-rss-default-on-red.log`、`/tmp/newshub-rss-default-on-green.log`，副本在本地备份目录。未新增外部订阅或真实发布者请求，运行时核对为配置/来源策略/健康证据，不冒充新增真实站点采集验收。此次未改 UI，因此未重复上一轮的前端测试和浏览器验收。

## 备份与恢复

修改前配置备份在 `/home/lambert/.local/share/newshub/uat-20261020/rss-default-on-20261020/`，`.before` 文件权限 0600；不提交或打印其内容。该目录还保存局部镜像构建上下文及日志。代码在独立工作区中可单独审查。

如需显式关闭，应用与同步服务均设置 `RSS_FULL_CONTENT_ENABLED=0` 后仅重建这两个本地服务；无须覆盖数据库，也不删除已取得的正文。来源抓取失败继续使用已有内容，不自动触发全局回退。
