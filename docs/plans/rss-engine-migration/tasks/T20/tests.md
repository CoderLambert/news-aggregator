# T20：专项验收

状态：2026-10-17 错误恢复专项自动化 TESTED；本轮真实浏览器、移动端、实际来源与生产验收 NOT_RUN。以下原合同继续有效，局部自动化通过不等于全部场景已验收。

- T20-A1：关键词/URL 0/1/多候选接线。预期按对应合同断言成功及失败边界。
- T20-A2：目录/token/直接 URL 都调用普通订阅校验。预期按对应合同断言成功及失败边界。
- T20-A3：键盘/移动端/焦点和错误恢复。预期按对应合同断言成功及失败边界。
- T20-A4：连接/initial_sync/ready 不虚构，私有操作不串用户。预期按对应合同断言成功及失败边界。

## 执行与证据

```bash
# 2026-10-17：当前实现的专项命令
cd frontend
npm run typecheck
npx eslint src/features/rss/DiscoverDialog.tsx tests/features/rss/DiscoverDialog.test.tsx
npm run test:run -- tests/features/rss/DiscoverDialog.test.tsx tests/features/rss/ConnectionStatus.test.tsx tests/features/rss/OpmlDialog.test.tsx
```

UI 可先依据 fixture 开发；T09 真实健康和 RSSHub 条件分支在 T27 联合验收，RSSHub 未就绪隐藏可执行入口

Python/Node 版本沿现有 CI（Python 3.12、Node 22），依赖由所属任务锁定。涉及数据库用临时合成库；live 测试检查明确隔离 allowlist，不连接活动工作区/生产库。前端改动补 typecheck/lint/相关组件测试；数据库改动补迁移/契约测试。实际引擎、浏览器、恢复和运行证据只在本任务承担该风险时要求，见 [验收矩阵](../../ACCEPTANCE-MATRIX.md)。

任务专项证明模块行为，批次验证组合；同版本/配置公共证据可复用。环境缺失写明具体门禁 BLOCKED，不伪造 PASS，也不把无关模块开发冻结。测试失败先修受影响路径，必要时重跑关联集成。

## 完成条件

记录命令/退出码、版本/环境及实际案例结果；通过相关 PR 必需检查和实现评审。可在生产门禁未开始时完成独立模块，但本任务明确承担的真实运行证据缺失则不能 DONE。没有统一的“所有任务必须独立 Agent 审核”要求；关键身份/权限/迁移/恢复变更须独立复核。

## 2026-10-17 本轮自动化证据

- 基线：`2e3254c890f52af626aa7d2400097301bf550d14`；功能提交：[`add9d64e695d74c3edc4841b6dd54a943efbaa1f`](https://github.com/CoderLambert/news-aggregator/commit/add9d64e695d74c3edc4841b6dd54a943efbaa1f)；[PR #94](https://github.com/CoderLambert/news-aggregator/pull/94)。
- Node `v24.19.0`，使用该基线的原 `package-lock.json`；仓库 Node 22 和全量检查由同一 PR CI 验证。
- 上述 RSS 专项：**26 passed / 3 files，exit 0**；发现弹窗由原 8 项增加至 22 项，连接和 OPML 4 项。
- `npm run test:run -- tests/features/rss/ConnectionStatus.test.tsx tests/features/rss/OpmlDialog.test.tsx tests/pages/Channels.integration.test.jsx tests/services/workspaceApi.test.ts`：**32 passed / 4 files，exit 0**。连接/OPML 与前组重叠，不相加宣称总数。
- 完整前端源码 `typecheck`、两改动文件 ESLint、`git diff --check`：**exit 0**。
- 新增反例验证每阶段恢复对应的 API、写请求无隐式重试、同意图复用完整请求和幂等键、改变分组产生新意图、GET 出错/终态停止轮询、键盘 Enter、关闭重开、跨 viewer 及晚到响应隔离。
- 未删除旧测试、改变旧断言或新增 skip。真实浏览器/移动端、真实来源健康联动与生产环境：**NOT_RUN**。
