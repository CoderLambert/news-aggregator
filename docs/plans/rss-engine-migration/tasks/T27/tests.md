# T27 专项验收

2026-10-16：合成真实浏览器全链 PASS；公开来源有限取样已运行，部分来源/完整性仍未封存。具体范围见 [report.md](report.md)。

- A1：实际 Chromium 首访、GET、hover、搜索全部 GET，无隐式采集；publisher audit 无被动原文请求。
- A2：A/B/匿名与切换账号、已读/收藏、退订重载通过；越权详情/AI/TTS 404；真实付费 provider 未使用。
- A3：真实 Miniflux→worker→SQLite→SPA，代码 DOM/clipboard 精确相同；表格、合成图片、移动端键盘与显式修复通过。
- A4：6 个公开 feed 尝试，5 sampled、Uber failed；11 篇结构取样，逐 URL 与延迟已保存；人工完整性、第二摘要博客成功、HN self_post、RSSHub 和旧 DEV 8555 仍有限制。

```bash
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T27/run_browser.py \
  --output /tmp/rss-t27-browser-final2
# exit 0，真实引擎/浏览器，资源已清理
/tmp/newshub-rss-coordinator-venv/bin/python ops/rss/T27/sample_public.py \
  --output /tmp/rss-t27-public-evidence.json
# exit 0；业务失败保留于输出，不代表所有来源通过
/tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q \
  tests/rss_engine_contract/test_product_acceptance.py
# 3 passed, 1 skipped：已保存证据一致性；fresh live 包装器默认跳过。
```

显式重新运行 fresh live 包装器时，先准备隔离 allowlist JSON：

```json
{"allow_project_prefix":"newshub-rss-t27-","allow_loopback_app":true,"allow_synthetic_publisher":true,"allow_public_sampling":false}
```

然后 `RSS_TEST_ALLOW_LIVE=1 RSS_TEST_CONFIG=/absolute/path/to/config.json` 运行上述 pytest 的 `-m rss_live`。该包装器没有在第一条命令已成功后重复执行；真实浏览器证据来自第一条命令。脚本每次创建唯一项目与临时 DB，不复用生产资源。公共来源另行显式运行 sample_public.py，固定允许 feed 清单与每类最多 5 篇。

可复用 T00/T03/T08/T09 已有故障证据，但各自 SHA/配置范围不变。T26 和最终 CI 由协调者独立完成。本任务不运行全仓测试，也不把真实用户副本缺失写成通过。
