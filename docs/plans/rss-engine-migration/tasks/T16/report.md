# T16：目录实现与专项证据

实现状态：IMPLEMENTED，待主调度集成/评审。专项结果：19 PASS。生产/真实 Feed 健康验证：NOT_RUN。

## 交付

- DDL 小提交 `81ad293`，已推 `origin/task/rss-T16-directory`；迁移 `0052_feed_directory` 依赖 `0051_seed_domestic_medical_sources`。已释放公共 `models.py` 写入权，T05 从0053继续。
- 独立 `api/rss/directory_models.py` 注册 `FeedDirectorySnapshot/Entry`，唯一 active 快照、snapshot/entry_id 唯一，稳定展示 UUID 与内部行 PK 分离。
- `api/rss/directory.py`：固定 hash/格式验证、有界声明式 JSON 导入、全量校验后原子快照切换、旧快照保留、仅本地确定排序搜索、绑定版本/关键词的签名分页。
- 默认种子 41 项：Plenary 实际 38 个 HTTPS Feed（两份固定 OPML、7个 HTTP 明确排除），2个单独归属的原创建议，RSSHub 实际 GitHub issue 路由1个模板。Coding Horror 保留上游 FeedBurner URL 作为来源 key，目录订阅 URL 改为公网实测两跳后的最终 HTTPS 地址；详见 directory_data/README.md。
- 固定上游提交、输入与投影 SHA256、完整许可文本、格式/覆盖范围/接口说明见 [directory_data/README.md](../../../../../backend/api/rss/directory_data/README.md)。Plenary为CC0-1.0；RSSHub为AGPL-3.0-only。没有把上游描述重新标成CC0。

## 实测

环境：隔离 worktree `/tmp/newshub-rss-T16`，执行器为现有虚拟环境只读 Python 3.14.8 / Django 6.1；CI目标为Python3.12，本机未重建3.12环境。没有安装新依赖，没有触碰用户数据库。

```bash
RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-T16-ddl.sqlite3 PYTHONPATH=backend:crawler \
 /home/lambert/githubRepos/lambert/news-aggregator/backend/venv/bin/python backend/manage.py migrate --noinput
# exit 0，合成空库完整迁移包含0052
RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-T16-ddl.sqlite3 PYTHONPATH=backend:crawler \
 /home/lambert/githubRepos/lambert/news-aggregator/backend/venv/bin/python backend/manage.py makemigrations --check --dry-run
# exit 0，No changes detected
RUN_MAIN=true DJANGO_DB_PATH=/tmp/newshub-rss-T16-tests.sqlite3 PYTHONPATH=backend:crawler \
 /home/lambert/githubRepos/lambert/news-aggregator/backend/venv/bin/python -m pytest -q backend/api/tests/rss/test_directory.py
# exit 0，19 passed in 3.96s
```

- T16-A1 PASS：真实固定种子输入与许可证/投影 hash，格式版本，真实0051→0052迁移、唯一约束和原 Source 主键保持。
- T16-A2 PASS：坏checksum/版本/许可/重复ID/末条错误/个人可见性/伪造验证时间/歧义格式/空集合/私网URL保留旧快照；bulk_create写失败回滚；重复导入复用与新旧版本共存。
- T16-A3 PASS：github、React、健康、中文；大小写；精确/前缀/文本/模板排序和稳定ID收尾；分页、篡改cursor及过期版本拒绝。
- T16-A4 PASS：禁用socket后导入/搜索成功；无订阅/Source写入；无伪造统计/预览；RSSHub能力和必需参数保留，Radar/handler/heat/topFeeds忽略，始终模板。
- Django仅提示隔离worktree无前端dist的现有staticfiles.W004；不影响模型/迁移检查。未进行全仓回归、网络Feed访问、引擎操作或生产操作。

## 接口、后续接线与风险

`import_snapshot(payload, expected_checksum=...)` / `import_pinned_seed()` 返回激活的Snapshot；`search_directory(q='', limit=20, cursor=None)` 返回 `{results,next_cursor,snapshot_version}`。错误为 `DirectoryValidationError` / `DirectoryCursorError`，由API接线映射输入/过期分页错误。`subscribed=null`须由T20按本人关系补齐，预览目前为空；模板 `public_url` 是相对路由路径，不是实例URL。来源验证时间统一null。

T02负责按日调用元数据检查/导入并持久化调度状态；T16不修改公共worker/settings/routes。T20对外接线与授权预览未执行；T18网关/能力批准与真实RSSHub运行未执行。当前只有有界代表性目录子集，新增或更换来源需更新固定来源/许可/hash。完整RSSHub支持中超出当前路径语法的路由会拒绝该次快照，不执行脚本或猜测转换。软件/元数据许可不授予发布者正文展示权。

本任务分支最终功能SHA由交付消息记录，CI/独立评审由主调度记录。恢复可重新激活已保留的原始固定字节版本，无需逆迁移或全库恢复。
