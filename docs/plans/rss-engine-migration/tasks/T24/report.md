# T24 静态盘点工具与副本门禁

状态：实现与合成专项已完成；真实副本、逐源替代决定及生产范围仍 BLOCKED。没有访问活动工作区或生产数据库。

`api.rss.migration_inventory` 直接读取代码政策，不初始化 Django、不导入 Spider、不请求来源。`scripts/rss-inventory.py --output PATH` 生成只读盘点产物；可提供 `--snapshot` 脱敏一致性副本证据 JSON 与 `--targets` 显式目标映射。产物始终 `production_ready=false`，不是 T25 可执行授权清单。输出使用独占创建，避免覆盖已审 manifest。

本次基线 `d0472c1`，静态政策并集 57 项。DEV.to 标签/热度、HN 前80与混合对象、GitHub daily/weekly 仓库、arXiv 摘要分别记录差异。其余保留政策、源码路径/hash、Feed候选。候选未进行网络验证，不自动批准或将不支持来源改成公开。

快照格式：`{id, sources:[{source_id, source_keys, display_name, publication, reading_policy, owner, epoch, preservation}]}`。`preservation` 应提供一致性副本的 PK/FK、用户关系、正文及译文聚合hash；本工具不编造该证据。数据库ID只接受显式证据，不按名称猜测。多旧key归于同source时保留全部合同；无代码政策的动态来源仍保留。目标映射按 `inventory_key` 指定公开 HTTPS Feed，规范scheme/host/default port/fragment，保留路径/query；同Feed形成最小候选组，完整性仍需真实副本和运行引用核实。

验证环境：Python 3.12.14，独立 `/tmp/newshub-rss-coordinator-venv`。命令：

```sh
RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-coordinator-unused.sqlite3 PYTHONPATH=backend:crawler \
 /tmp/newshub-rss-coordinator-venv/bin/python -m pytest -q backend/api/tests/rss/test_migration_inventory.py
# 5 passed，退出0；不访问数据库。
/tmp/newshub-rss-coordinator-venv/bin/python scripts/rss-inventory.py --output /tmp/newshub-rss-static-inventory-20261016.json
# 57 sources; snapshot=BLOCKED; production_ready=false，退出0。
```

未完成：从授权一致性副本导出真实source/endpoint/关系/hash；逐源确认目标Feed、覆盖差异和停更决定；核对完整共享采集引用。以上阻塞 T24 实际盘点完成和生产范围，不能阻塞 T25 合成工具或无关开发。现已补充只读副本导出器；真实副本运行仍未执行。

副本模式：`scripts/rss-inventory.py --snapshot-db /explicit/standalone-copy.sqlite3 --snapshot-sha256 EXPECTED --output NEW_PATH`。只接受显式路径与预期SHA，拒绝有非空WAL的活动主文件；SQLite mode=ro/query_only及读事务，前后hash核对。输出全表行数/确定顺序hash（不输出正文/译文/凭据），SourceConfig FK与既有频道精确政策名关联，未绑定动态配置单列不丢失；公共旧来源的public/legacy初始化与当前迁移合同一致。只有合成文件运行，未读取用户库。扩展后6专项通过。
