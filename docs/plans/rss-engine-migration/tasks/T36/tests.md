# T36：专项与运行验收

当前NOT_RUN。下列测试文件尚未实现，命令为规划要求。必须在隔离allowlist运行，不能连接活动业务库或生产。

- T36-A1：兼容镜像读取legacy/complete/available和个人源授权正确。预期逐项断言通过且附真实工件。
- T36-A2：真实旧任务开始于切换前、完成于回滚后时仍被fence拒绝。预期逐项断言通过且附真实工件。
- T36-A3：manifest schema精确匹配、服务角色符合暂停owner，不能无条件启旧crawler。预期逐项断言通过且附真实工件。
- T36-A4：隔离应用回滚保留新News/译文历史/用户关系；记录SHA/digest/CI与恢复证据。预期逐项断言通过且附真实工件。
- T36-N1：未知schema/实例/角色必须失败关闭，拒绝冒用真实生产配置。
- T36-N2：环境或证据不足标BLOCKED，不能skip后PASS。

```bash
test -f tests/rss_engine_contract/test_compatibility_seal.py
RSS_TEST_ALLOW_LIVE=1 RSS_TEST_CONFIG=/absolute/path/to/isolated-test-config.json RUN_MAIN=true PYTHONPATH=backend:crawler backend/venv/bin/python -m pytest -q tests/rss_engine_contract/test_compatibility_seal.py -m rss_live
```

预期：测试存在、退出0且全部用例通过；实际镜像/进程/故障恢复工件与SHA/digest/schema对应。独立审核Agent校验diff、输出及无额外依赖，修P0/P1；API/DB契约、必要运行、必需CI全部通过才可验收。
