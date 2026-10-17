# T21：专项验收

2026-10-17：原 OPML 合同保持有效。本轮恢复差额 [PR #96](https://github.com/CoderLambert/news-aggregator/pull/96) 已编写 15 个组件用例；本地只执行语法检查，行为测试/类型/lint 结果以该 PR 的实际 CI 为准，未运行不算通过。

- T21-A1：恶意 XML/深度/大小和凭据拒绝且预览零网络。
- T21-A2：确认后幂等、不同选择重放 409。
- T21-A3：部分失败只重试失败项。
- T21-A4：本人多组导出/再导入幂等，无账号全量/secret。

## 执行命令

```bash
# 已存在的后端合同文件，不是旧规划中的 test_opml.py。
RUN_MAIN=true PYTHONPATH=backend:crawler \
  backend/venv/bin/python -m pytest -q \
  backend/api/tests/rss/test_opml_import.py \
  backend/api/tests/rss/test_subscriptions.py \
  backend/api/tests/rss/test_access_contract.py

cd frontend
npm run typecheck
npm run lint
npm run test:run -- \
  tests/features/rss/OpmlDialog.test.tsx \
  tests/features/rss/OpmlDialog.recovery.test.tsx \
  tests/features/rss/DiscoverDialog.test.tsx \
  tests/features/rss/ConnectionStatus.test.tsx \
  tests/pages/Channels.integration.test.jsx \
  tests/services/workspaceApi.test.ts
```

仓库现有 PR CI 运行完整前端套件，因此包含上述组件和关联测试；后端三根完整回归包含原权限/OPML 用例。上述专项命令不能仅凭写在文档中就标为已运行，执行位置和实际数量必须注明。

## 本轮反例

更换或清空文件后旧预览不可确认；预览失败不隐式重试；确认结果未知时冻结 token/项目/分组并原样重放；改变选择先新建预览。第一条进度读取失败仍保留记录编号，恢复同编号与恢复按钮只发送 GET。

部分成功仅重试所选失败项；重试 POST 结果未知时先 GET 对账，未读取成功前禁用再次提交。进度失败或终态停止轮询。旧用户预览/确认晚到不回填新会话或旧用户缓存；更换记录时旧进度不能覆盖新记录。非法 UUID 无请求。

## 本轮证据边界

- 基线 `c841b07a410a475855029359370d18abe9a6c79c`；功能提交 `95479b7c286fa8dca675f73c0849e14d904c4b3c`。
- 本地 Node 22.16.0、TypeScript 5.8.3 的 transpileModule：源码/新增测试各 0 语法诊断。这不是项目锁定 TypeScript 的完整类型检查。
- 执行容器无法解析外部依赖地址，本地项目 Vitest/typecheck/lint、后端 pytest：NOT_RUN；由 PR 隔离 CI 产生实际运行证据后在 PR 中记录，不用历史通过数代替。
- 原测试、预期计数和 skip 未更改；新增测试独立成文件。
- 真实浏览器、移动端、实际来源和生产验收：本轮 NOT_RUN；历史 T27 证据不自动升级为本 SHA 的验收。
- 审核为主执行者自检，不是独立代理审查。

## 完成条件

记录命令/退出码、版本/环境及实际案例结果；通过相关 PR 必需检查和实现评审。可在生产门禁未开始时完成独立模块，但本任务明确承担的真实运行证据缺失则不能 DONE。没有统一的“所有任务必须独立 Agent 审核”要求；关键身份/权限/迁移/恢复变更须独立复核。生产恢复与完整产品验收保留原门禁。
