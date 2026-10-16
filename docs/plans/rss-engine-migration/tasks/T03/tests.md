# T03：验收与执行证据要求

状态：NOT_RUN。以下命令是后续任务必须交付的测试入口，当前尚未创建这些测试；不能把测试计划当实现或PASS。当前只校验规划文档。

## 案例与预期

- T03-A1：隔离真实备份/恢复两库、凭据引用和绑定校验，对账后身份一致；生产回滚基点尚不存在。预期：断言满足且保存失败反例及实际结果。
- T03-A2：更新/回滚失败关闭writer，未批准schema拒绝，不做静默reverse migration。预期：断言满足且保存失败反例及实际结果。
- T03-A3：恢复点及之后写入损失被量化，普通回滚不恢复数据库。预期：断言满足且保存失败反例及实际结果。
- T03-A4：旧manifest仍验证；删除阶段不再强制启动crawler。预期：断言满足且保存失败反例及实际结果。

- T03-N1：关闭/重启/权限拒绝/上游错误与重复提交不会产生未声明的写入；预期无错误覆盖、串用户或隐藏旧抓取。
- T03-N2：前置缺失、无运行环境或未获生产授权；预期标BLOCKED并停止依赖动作，不能skip后报告PASS。

## 命令和环境

工作目录为仓库根；Python 3.12、Node 22，以锁定依赖及隔离测试数据库运行。环境配置仅包含合成/隔离资源；测试库不得指向当前工作区或生产库。live测试必须验证目标在隔离allowlist，未显式允许即拒绝运行，不能仅凭环境变量名认为安全。

```bash
# 规划命令：测试文件尚未交付，不能当作已通过证据。
test -f scripts/deploy/tests/test_rss_backup_restore.py
RUN_MAIN=true PYTHONPATH=backend:crawler \
  backend/venv/bin/python -m pytest -q scripts/deploy/tests/test_rss_backup_restore.py
```

预期：测试文件存在；专项进程退出0；断言数与用例逐项记录；要求实际引擎/浏览器/恢复的条目另附运行证据。前端修改执行typecheck/lint；数据变更执行schema/API契约；所有PR满足实际必需CI。批次级全量按ACCEPTANCE-MATRIX，避免无变更重复全量。

## 独立审核与完成门禁

审核Agent必须未参与本任务实现，检查合同、diff、实际测试输出和副作用；留下可追溯结论。P0/P1必须修复，不接受“限制说明”代替实现缺陷修复。report.md覆盖本任务所有A/N条目、API/DB合同、实际运行、SHA/PR/CI、风险和回滚。缺任何必需证据均非DONE。
