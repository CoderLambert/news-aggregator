# T14：验收与执行证据要求

状态：NOT_RUN。以下命令是后续任务必须交付的测试入口，当前尚未创建这些测试；不能把测试计划当实现或PASS。当前只校验规划文档。

## 案例与预期

- T14-A1：available携带scope/revision/hash/completeness进入模型，摘要不伪称全文。预期：断言满足且保存失败反例及实际结果。
- T14-A2：正文变化时旧异步结果CAS不能发布为当前，历史译文不物理抹除。预期：断言满足且保存失败反例及实际结果。
- T14-A3：TTS/研究/推荐问题/问答全链路无旧Provider或抓取副作用。预期：断言满足且保存失败反例及实际结果。
- T14-A4：现有标题摘要向量索引策略保持，不为换RSS自动触发付费AI。预期：断言满足且保存失败反例及实际结果。

- T14-N1：关闭/重启/权限拒绝/上游错误与重复提交不会产生未声明的写入；预期无错误覆盖、串用户或隐藏旧抓取。
- T14-N2：前置缺失、无运行环境或未获生产授权；预期标BLOCKED并停止依赖动作，不能skip后报告PASS。

## 命令和环境

工作目录为仓库根；Python 3.12、Node 22，以锁定依赖及隔离测试数据库运行。环境配置仅包含合成/隔离资源；测试库不得指向当前工作区或生产库。live测试必须验证目标在隔离allowlist，未显式允许即拒绝运行，不能仅凭环境变量名认为安全。

```bash
# 规划命令：测试文件尚未交付，不能当作已通过证据。
test -f backend/api/tests/rss/test_ai_compatibility.py
RUN_MAIN=true PYTHONPATH=backend:crawler \
  backend/venv/bin/python -m pytest -q backend/api/tests/rss/test_ai_compatibility.py
```

预期：测试文件存在；专项进程退出0；断言数与用例逐项记录；要求实际引擎/浏览器/恢复的条目另附运行证据。前端修改执行typecheck/lint；数据变更执行schema/API契约；所有PR满足实际必需CI。批次级全量按ACCEPTANCE-MATRIX，避免无变更重复全量。

## 独立审核与完成门禁

审核Agent必须未参与本任务实现，检查合同、diff、实际测试输出和副作用；留下可追溯结论。P0/P1必须修复，不接受“限制说明”代替实现缺陷修复。report.md覆盖本任务所有A/N条目、API/DB合同、实际运行、SHA/PR/CI、风险和回滚。缺任何必需证据均非DONE。
