# T02：专项验收

状态：2026-10-16 已实现并运行隔离专项。A1/A2/A4 PASS；A3 配置与直接部署兼容回归 PASS，完整 app/indexer/channel-worker 本轮 live 启动 NOT_RUN。同步 worker 尚未接线，运行壳 sync_ready=false。

- T02-A1：PG 无宿主公开端口且引擎 API 受限。预期按对应合同断言成功及失败边界。
- T02-A2：真实镜像无 Torch/Scrapy/feedparser/browser 且不预加载 embedding。预期按对应合同断言成功及失败边界。
- T02-A3：app/indexer/channel-worker 正常。预期按对应合同断言成功及失败边界。
- T02-A4：隔离卷/secret 与健康检查正确。预期按对应合同断言成功及失败边界。

## 执行与证据

```bash
python3 -m venv /tmp/newshub-rss-t02-venv
/tmp/newshub-rss-t02-venv/bin/python -m pip install \
  -r backend/requirements-rss.lock pytest==8.4.2 PyYAML==6.0.3
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend:. \
  /tmp/newshub-rss-t02-venv/bin/python -m pytest -c /dev/null -p no:cacheprovider \
  scripts/deploy/tests/test_rss_runtime.py -q
docker build --target rss-sync -t newshub-rss-t02:isolated-check .
/tmp/newshub-rss-t02-venv/bin/python ops/rss/T02/verify_isolated.py \
  --image newshub-rss-t02:isolated-check --output /tmp/rss-t02-evidence.json
```

隔离验证器拒绝远端 Docker daemon/已有同名资源，生成新项目、合成 secrets、独立 named volumes 和随机环回 API 端口；只启动自己的 migration/rss-sync/miniflux/rss-db，finally 删除该项目容器/网络/卷。真实镜像证据见 [evidence.json](../../../../../ops/rss/T02/evidence.json)，运行接口和未验证项见 [README](../../../../../ops/rss/T02/README.md)。

最终 T02 专项5 passed in5.72s；此前与直接部署兼容回归组合65 passed in14.22s，最终只增强 T02 测试后复验5项。独立轻量镜像实际 Python3.12.12，证据中的 schema leaf为api0054；这是该基线的实验，不宣称覆盖后续集成schema/最终发布镜像。

构建文件可先按候选版本开发；T00 后锁 digest 并真实构建/启动，轻量镜像是 T08 容器验收前置

Python/Node 版本沿现有 CI（Python 3.12、Node 22），依赖由所属任务锁定。涉及数据库用临时合成库；live 测试检查明确隔离 allowlist，不连接活动工作区/生产库。前端改动补 typecheck/lint/相关组件测试；数据库改动补迁移/契约测试。实际引擎、浏览器、恢复和运行证据只在本任务承担该风险时要求，见 [验收矩阵](../../ACCEPTANCE-MATRIX.md)。

任务专项证明模块行为，批次验证组合；同版本/配置公共证据可复用。环境缺失写明具体门禁 BLOCKED，不伪造 PASS，也不把无关模块开发冻结。测试失败先修受影响路径，必要时重跑关联集成。

## 完成条件

记录命令/退出码、版本/环境及实际案例结果；通过相关 PR 必需检查和实现评审。可在生产门禁未开始时完成独立模块，但本任务明确承担的真实运行证据缺失则不能 DONE。没有统一的“所有任务必须独立 Agent 审核”要求；关键身份/权限/迁移/恢复变更须独立复核。
