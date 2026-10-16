# T18：专项验收

状态2026-10-16：离线85项及真实固定RSSHub健康/合成Nginx隔离专项PASS；A1/A3真实公网与Token仍BLOCKED，A2部分验证，整体不能DONE。

- T18-A1：真实 DNS/TLS/公网回流和私网防护。预期按对应合同断言成功及失败边界。
- T18-A2：凭据不跨跳转/不进 DTO/OPML/日志。预期按对应合同断言成功及失败边界。
- T18-A3：锁定路由如 Trending 的 Token/返回对象确认。预期按对应合同断言成功及失败边界。
- T18-A4：无需浏览器/Redis/自定义路由。预期按对应合同断言成功及失败边界。

## 执行与证据

```bash
RUN_MAIN=true NEWSHUB_RUNTIME_ROLE=rss_sync \
  DJANGO_DB_PATH=/tmp/newshub-rss-t18-tests.sqlite3 PYTHONPATH=backend:crawler \
  /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q backend/api/tests/rss/test_routes.py
sh -n ops/rss/T18/rsshub-entrypoint.sh
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T18/verify_isolated.py \
  --output /tmp/t18-evidence.json
```

85 passed in0.12s（Python3.12.14、退出0）；隔离脚本退出0。实际Nginx与临时测试CA/合成上游验证默认503、认证401、批准请求200、只读405/错Host421、编码/query/路径/未批准repo拒绝、三种认证头不透传、302→502无Location/不访问目标、500合成secret不回显、选定logs无合成secret。实际RSSHub固定镜像仅健康调用，以UID1000/只读根/memory cache启动，无Redis/浏览器cache；source revision与审查commit一致。输出见[evidence.json](../../../../../ops/rss/T18/evidence.json)。这些不是实际公网DNS/TLS/回流/Miniflux私网与认证跳转/真实GitHubToken对象或DTO/OPML端到端证明；默认template execution/网关profile依然关闭，真实门禁缺失详见[README](../../../../../ops/rss/T18/README.md)。

缺 DNS/Token 只阻塞 RSSHub 运行/上线；参数验证和模板开发可先完成，native 路径不依赖本任务

Python/Node 版本沿现有 CI（Python 3.12、Node 22），依赖由所属任务锁定。涉及数据库用临时合成库；live 测试检查明确隔离 allowlist，不连接活动工作区/生产库。前端改动补 typecheck/lint/相关组件测试；数据库改动补迁移/契约测试。实际引擎、浏览器、恢复和运行证据只在本任务承担该风险时要求，见 [验收矩阵](../../ACCEPTANCE-MATRIX.md)。

任务专项证明模块行为，批次验证组合；同版本/配置公共证据可复用。环境缺失写明具体门禁 BLOCKED，不伪造 PASS，也不把无关模块开发冻结。测试失败先修受影响路径，必要时重跑关联集成。

## 完成条件

记录命令/退出码、版本/环境及实际案例结果；通过相关 PR 必需检查和实现评审。可在生产门禁未开始时完成独立模块，但本任务明确承担的真实运行证据缺失则不能 DONE。没有统一的“所有任务必须独立 Agent 审核”要求；关键身份/权限/迁移/恢复变更须独立复核。
