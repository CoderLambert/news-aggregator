# T03：专项验收

状态：2026-10-16执行。T03-A1–A4工具专项与隔离真实两库恢复通过；最终生产schema/app兼容封存仍由T26承担。

- T03-A1：隔离真实两库备份恢复且实例/映射匹配。预期按对应合同断言成功及失败边界。
- T03-A2：未知 schema/目标及未停 writer 拒绝。预期按对应合同断言成功及失败边界。
- T03-A3：普通 rollback 不恢复库。预期按对应合同断言成功及失败边界。
- T03-A4：新角色不无条件启旧 crawler。预期按对应合同断言成功及失败边界。

## 执行与证据

```bash
RUN_MAIN=true NEWSHUB_RUNTIME_ROLE=rss_sync \
  DJANGO_DB_PATH=/tmp/newshub-rss-t03-tests.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  scripts/deploy/tests/test_rss_backup_restore.py \
  scripts/deploy/tests/test_release_operations.py \
  scripts/deploy/tests/test_full_content_release.py
bash scripts/deploy/tests/test_release_scripts.sh
bash -n scripts/deploy/rollback.sh
python3 ops/rss/T03/verify_isolated.py \
  --python /tmp/newshub-rss-coordinator-venv/bin/python \
  --output /tmp/t03-evidence.json
```

117 passed in8.36s（退出0，Python3.12.14）；release shell回归PASS；真实演练最终退出0。固定Miniflux2.3.3/schema132、PG17.6；完整Django迁移集含0057/0058，未含后来的0059。实际配对覆盖恢复、重复恢复与fresh恢复、活跃writer与错实例/schema/hash/prior拒绝、FK/关系/映射/非admin账号核对及项目清理见[evidence.json](../../../../../ops/rss/T03/evidence.json)。六writer为合成sleep容器；普通app rollback为真实现有脚本的fake-Docker subprocess回归，不是最终app兼容封存。secret副本保护、allowlist异常、PID重用等为独立合成专项。详见[README](../../../../../ops/rss/T03/README.md)。

工具开发不依赖 T11；自身 DONE 需隔离真实恢复。生产兼容基点由 T26 演练后封存

Python/Node 版本沿现有 CI（Python 3.12、Node 22），依赖由所属任务锁定。涉及数据库用临时合成库；live 测试检查明确隔离 allowlist，不连接活动工作区/生产库。前端改动补 typecheck/lint/相关组件测试；数据库改动补迁移/契约测试。实际引擎、浏览器、恢复和运行证据只在本任务承担该风险时要求，见 [验收矩阵](../../ACCEPTANCE-MATRIX.md)。

任务专项证明模块行为，批次验证组合；同版本/配置公共证据可复用。环境缺失写明具体门禁 BLOCKED，不伪造 PASS，也不把无关模块开发冻结。测试失败先修受影响路径，必要时重跑关联集成。

## 完成条件

记录命令/退出码、版本/环境及实际案例结果；通过相关 PR 必需检查和实现评审。可在生产门禁未开始时完成独立模块，但本任务明确承担的真实运行证据缺失则不能 DONE。没有统一的“所有任务必须独立 Agent 审核”要求；关键身份/权限/迁移/恢复变更须独立复核。
