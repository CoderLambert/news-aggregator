# T35：专项与运行验收

当前NOT_RUN。下列测试文件尚未实现，命令为规划要求。必须在隔离allowlist运行，不能连接活动业务库或生产。

- T35-A1：实际构建镜像且包清单无Torch/embedding/Scrapy/feedparser/browser。预期逐项断言通过且附真实工件。
- T35-A2：隔离启动Django ORM及EngineAdapter，sys.modules/运行日志证明未加载模型。预期逐项断言通过且附真实工件。
- T35-A3：角色不继承BYOK或无关卷/凭据，数据库路径与lease实例配置正确。预期逐项断言通过且附真实工件。
- T35-A4：现有app/indexer/channel-worker照常加载其所需功能；T08可直接复用此镜像。预期逐项断言通过且附真实工件。
- T35-N1：未知schema/实例/角色必须失败关闭，拒绝冒用真实生产配置。
- T35-N2：环境或证据不足标BLOCKED，不能skip后PASS。

```bash
test -f scripts/deploy/tests/test_rss_sync_runtime.py
RUN_MAIN=true PYTHONPATH=backend:crawler backend/venv/bin/python -m pytest -q scripts/deploy/tests/test_rss_sync_runtime.py
```

预期：测试存在、退出0且全部用例通过；实际镜像/进程/故障恢复工件与SHA/digest/schema对应。独立审核Agent校验diff、输出及无额外依赖，修P0/P1；API/DB契约、必要运行、必需CI全部通过才可验收。
