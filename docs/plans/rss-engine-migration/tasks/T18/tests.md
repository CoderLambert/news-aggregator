# T18：专项验收

状态：NOT_RUN。以下为待交付测试，文件/命令存在与通过结果均不得预先声明。

- T18-A1：真实 DNS/TLS/公网回流和私网防护。预期按对应合同断言成功及失败边界。
- T18-A2：凭据不跨跳转/不进 DTO/OPML/日志。预期按对应合同断言成功及失败边界。
- T18-A3：锁定路由如 Trending 的 Token/返回对象确认。预期按对应合同断言成功及失败边界。
- T18-A4：无需浏览器/Redis/自定义路由。预期按对应合同断言成功及失败边界。

## 执行与证据

```bash
# PLANNED：测试文件与产品尚未实现。
test -f tests/rss_engine_contract/test_rsshub_gateway.py
RSS_TEST_ALLOW_LIVE=1 RSS_TEST_CONFIG=/absolute/path/to/isolated-test-config.json \
  RUN_MAIN=true PYTHONPATH=backend:crawler \
  backend/venv/bin/python -m pytest -q tests/rss_engine_contract/test_rsshub_gateway.py -m rss_live
```

缺 DNS/Token 只阻塞 RSSHub 运行/上线；参数验证和模板开发可先完成，native 路径不依赖本任务

Python/Node 版本沿现有 CI（Python 3.12、Node 22），依赖由所属任务锁定。涉及数据库用临时合成库；live 测试检查明确隔离 allowlist，不连接活动工作区/生产库。前端改动补 typecheck/lint/相关组件测试；数据库改动补迁移/契约测试。实际引擎、浏览器、恢复和运行证据只在本任务承担该风险时要求，见 [验收矩阵](../../ACCEPTANCE-MATRIX.md)。

任务专项证明模块行为，批次验证组合；同版本/配置公共证据可复用。环境缺失写明具体门禁 BLOCKED，不伪造 PASS，也不把无关模块开发冻结。测试失败先修受影响路径，必要时重跑关联集成。

## 完成条件

记录命令/退出码、版本/环境及实际案例结果；通过相关 PR 必需检查和实现评审。可在生产门禁未开始时完成独立模块，但本任务明确承担的真实运行证据缺失则不能 DONE。没有统一的“所有任务必须独立 Agent 审核”要求；关键身份/权限/迁移/恢复变更须独立复核。
