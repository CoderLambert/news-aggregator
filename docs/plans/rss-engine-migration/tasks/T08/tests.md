# T08：专项验收

状态：2026-10-16已执行专项。A1–A4通过；真实轻量容器/引擎最小控制集成通过。故障注入与真实引擎证据分别记录，不代表完整同步/生产放行。

- T08-A1：20 次注册一物理绑定。预期按对应合同断言成功及失败边界。
- T08-A2：响应丢失/取消注册/最后引用收敛。预期按对应合同断言成功及失败边界。
- T08-A3：旧政策修复不执行或发布，配置核对后恢复。预期按对应合同断言成功及失败边界。
- T08-A4：控制不占 SQLite 写事务且短读容量保留。预期按对应合同断言成功及失败边界。

## 执行与证据

```bash
RUN_MAIN=true NEWSHUB_RUNTIME_ROLE=rss_sync \
  DJANGO_DB_PATH=/tmp/newshub-rss-t08-tests.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  backend/api/tests/rss/test_operations.py backend/api/tests/rss/test_control_worker.py \
  scripts/deploy/tests/test_rss_runtime.py
docker build --target rss-sync -t newshub-rss-t08:isolated-check .
python3 ops/rss/T08/verify_live.py --image newshub-rss-t08:isolated-check \
  --output /tmp/rss-t08-evidence.json
```

最终专项及T02直接回归48 passed in12.56s（Python3.12.14，协调venv只读）；真实容器Python3.12.12、Miniflux固定2.3.3，输出见 [evidence.json](../../../../../ops/rss/T08/evidence.json)。20线程注册、丢响应/取消/旧lease/政策与正文token/网络期间DB写/两槽/Retry-After/进程非零退出、六种pin owner/enabled组合、两种unknown配置DTO证据缺口为合成SQLite和fake adapter故障注入；真实引擎另验证20用户操作共享Feed、启停/政策/refresh/refetch/发现0/1/3/真实超时。详细接口和未验证项见 [README](../../../../../ops/rss/T08/README.md)。

实现可先用 fake adapter；DONE 需轻量容器及真实引擎操作集成，生产授权不是开发前置

Python/Node 版本沿现有 CI（Python 3.12、Node 22），依赖由所属任务锁定。涉及数据库用临时合成库；live 测试检查明确隔离 allowlist，不连接活动工作区/生产库。前端改动补 typecheck/lint/相关组件测试；数据库改动补迁移/契约测试。实际引擎、浏览器、恢复和运行证据只在本任务承担该风险时要求，见 [验收矩阵](../../ACCEPTANCE-MATRIX.md)。

任务专项证明模块行为，批次验证组合；同版本/配置公共证据可复用。环境缺失写明具体门禁 BLOCKED，不伪造 PASS，也不把无关模块开发冻结。测试失败先修受影响路径，必要时重跑关联集成。

## 完成条件

记录命令/退出码、版本/环境及实际案例结果；通过相关 PR 必需检查和实现评审。可在生产门禁未开始时完成独立模块，但本任务明确承担的真实运行证据缺失则不能 DONE。没有统一的“所有任务必须独立 Agent 审核”要求；关键身份/权限/迁移/恢复变更须独立复核。
