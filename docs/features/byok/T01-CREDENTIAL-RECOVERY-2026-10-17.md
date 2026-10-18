# BYOK T01：现有密钥设置安全恢复（2026-10-17）

> **历史记录说明（2026-10-18）**：此文件记录 #97 曾经存在的旧单 Key 页面恢复工作；旧入口及其专属测试已随 [PR #103](https://github.com/CoderLambert/news-aggregator/pull/103) 删除，新连接的回显掩码、响应未知时显式 GET 对账、清空输入、切换账号隔离等行为以 `/settings/ai` 和 `frontend/tests/pages/AIModelSettingsPage.test.tsx` 为准。新架构已合并 `main@13584bc`；下一项原 T01 的真实 worker epoch 接线仍未完成，生产数据迁移/真实模型/人工 UAT 仍 NOT_RUN。下面为先前单独 PR 的历史验收结果，而非当前代码运行说明。

原任务仍为 **PARTIAL**。本文件是原 T01 的局部交付报告，不是新任务/另一套编号；[原 Task](https://github.com/CoderLambert/news-aggregator/blob/ed58afa7a72ae905e2a2ffc315d968ca3634b8f2/docs/features/byok/tasks/T01-credentials.md)、[原 Test](https://github.com/CoderLambert/news-aggregator/blob/ed58afa7a72ae905e2a2ffc315d968ca3634b8f2/docs/features/byok/tests/T01-credentials.md) 和[统一计划](../../plans/FEATURE-DEVELOPMENT-2026-10-17.md)继续有效。

## 差异与本轮代码

开工核对 main `c841b07a410a475855029359370d18abe9a6c79c`。对照旧 [PR #34](https://github.com/CoderLambert/news-aggregator/pull/34) 及其连接页面、原合同和当前 `UserProviderCredential` / `ProviderCredentialView` / `SettingsPage`，确定主线已有单凭据加密读写，但状态读取失败会显示“尚未配置”，错误正文可能直接呈现，保存失败会留存已提交 Key。

本次 [PR #97](https://github.com/CoderLambert/news-aggregator/pull/97)，功能提交 `f2741db9db6458b86dd1969691e925c677a4fb41`：

- 读取失败保持未知状态，禁止误操作；显式 GET 成功后恢复保存/删除。
- 保存/删除响应丢失时不重放写请求，由用户显式 GET 对账。
- Key 在提交时立即从输入框清空，切换提供方和退出账号清除草稿；不写浏览器持久存储。
- 错误仅按状态码映射，忽略可能含 Key 的异常消息、HTML 或上游正文。
- 同步提交门闩拒绝重复表单提交；旧账号晚到响应不更新新账号界面。
- 保存结果明确“尚未验证可用性”，不冒充模型验证。

仅改现有页面及新增组件测试。没有修改后端、公共 API、存储/AAD、模型/数据库迁移、业务 SDK 路由、OAuth 或依赖。旧分支迁移没有直接重放。

## 测试与证据

```bash
cd frontend
npm run typecheck
npm run lint
npm run test:run -- \
  tests/pages/SettingsPage.test.tsx \
  tests/pages/SettingsPage.credentials-recovery.test.tsx \
  tests/pages/ChatGPTSubscriptionSettings.test.tsx \
  tests/context/AuthContext.races.test.tsx \
  tests/App.readOnly.test.tsx
```

新增回归覆盖未知状态、显式读取/重复读取失败、提交立即清空、重复提交拒绝、未知保存/删除结果只读恢复、切换提供方、三种错误泄密反例、取消删除、跨账号晚到读写、退出账号与存储。原测试/断言/skip 未更改。

本地 Node 22.16.0 / TypeScript 5.8.3 transpileModule：源码和新增测试各 0 语法诊断，不等同项目锁文件版本的完整类型检查。当前容器不能联网安装依赖，本地 Vitest/typecheck/lint/后端 pytest **NOT_RUN**。上述用例由仓库现有隔离 CI 的完整前端套件执行，实际结果/受测 head/合并状态记录在 #97；没有完成执行的项目不预写 PASS。

审核为主执行者自检（已检查远端 diff、当前 API 与旧 PR 对应范围），不是独立代理审核。本轮不执行真实用户 Key、真实厂商、生产数据库、真实浏览器或人工验收。

## 不可越过的剩余合同

正式 `/settings/ai` 路由、多连接与别名、掩码/启停、endpoint/AAD 完整身份绑定、credential epoch 及队列/在途 worker 撤销、完整默认关闭开关和原 T01 的全链路契约仍需差量集成。旧 #34 保留；局部 UI 恢复通过不能将这些项目划为完成。

取消旧状态读取与忽略晚到写响应只是 **UI 生命周期隔离**，不声称已经取消服务端提交，也不声称新增服务器级会话或 worker 撤销栅栏。T01 没有网关部署前置；BYOK T02 仍须满足原 T01 与 T00 所需合同，不能因为本 PR 通过就自动放行。

本批另一个独立交付为 RSS T21 [#96](https://github.com/CoderLambert/news-aggregator/pull/96)。后续应优先继续 T01 的明确生命周期差额，再依据依赖选择 T02；不得跳过 T10 研究续问、T11 推荐和 T12 个人用量。
