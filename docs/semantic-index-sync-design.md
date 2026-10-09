# 语义索引同步与恢复设计

## 目标

SQLite 中的 `News` 是唯一事实来源，ChromaDB 是可重建的派生索引。系统需要自动同步新增、修改和删除，支持模型版本升级、无停机重建、超级管理员控制和搜索降级。

## 索引契约

- 文本：规范化后的 `title + "\n" + content[:500]`
- 模型：`sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2`
- 空间：余弦距离
- Chroma ID：字符串形式的 `News.id`
- metadata：`news_id`、`source_hash`、`schema_version`、`model_name`、`indexed_at`
- `source_hash` 覆盖索引版本、模型名称和规范化文本，任一变化都会触发 upsert。
- 代码中的模型或 schema 版本高于活动索引时，普通同步会自动提升为版本化重建；完成前语义请求使用关键词降级，避免混用不同 embedding 空间。

全文和用户私有翻译暂不进入本索引。全文语义检索应另行采用分块索引，避免长正文覆盖标题相关性。

## 运行架构

独立 `indexer` 容器运行持久化 `embedding_worker`：

1. 爬虫批次进入最终状态后只在数据库中排队一次增量同步。
2. Worker 周期性执行完整一致性扫描，修复遗漏的事件。
3. Worker 流式读取新闻，比较 Chroma metadata 中的内容哈希。
4. 只编码缺失或变化的记录，并删除数据库中已不存在的孤立向量。
5. Chroma 读写通过跨进程文件锁协调；生成 embedding 时不持锁。

Worker 与 `sync_embeddings --wait` 还共享 `logs/embedding-worker.lock` 执行锁。同一时刻只有一个任务执行者。新进程拿到锁即证明前任已经退出，会立即回收前任的 `running` / `cancel_requested` 任务、改写 owner token 并创建恢复任务，不依赖五分钟心跳超时。迟到的旧 owner 不能提交终态。

Crawler 继续使用 `NEWS_CRAWL_ONLY=1`，不自动翻译、生成摘要或调用外部 AI。索引维护使用本地 embedding 模型。

## 任务与状态

`SearchIndexSettings` 保存自动同步开关、间隔、批大小、活动 collection、索引版本和 Worker 心跳。

`SearchIndexRun` 保存触发来源、同步模式、生命周期、数据量、缺失/变化/孤立计数、写入/删除计数和脱敏错误。数据库约束确保同一时间只有一个活动任务，同一爬虫批次最多产生一个索引任务。

关闭自动同步后，周期任务、Worker 启动任务和爬虫批次任务都不会新建；已经运行的任务继续安全完成。手动同步和重建仍可使用，便于管理员维护与恢复。

同步任务使用开始时的最大新闻 ID 作为水位，避免长事务阻塞爬虫。同步期间进入的新记录由下一轮处理。每轮结束重新核对数据库 ID 与向量 ID。

## 增量同步

- 缺失：数据库有新闻、Chroma 无 ID。
- 变化：ID 存在，但 `source_hash` 不同或旧索引没有 hash。
- 孤立：Chroma 有 ID、数据库无新闻。
- 批量 upsert 和 delete 均为幂等操作；失败后下一轮可以继续。
- 任务取消在批次边界生效，不留下半写入事务。

## 全量重建

重建写入新的版本化 collection，校验成功后在同一数据库事务中更新 `active_collection`、模型/schema 版本和最终任务计数。旧 collection 在当前版本保留作为回滚，不在重建开始时清空。Web 进程按活动 collection 读取，切换期间继续使用旧索引。异常清理会重新读取活动指针，只删除未启用的候选 collection。

## 搜索降级

语义索引为空、损坏、被锁或模型加载失败时：

- semantic 自动执行关键词检索；
- hybrid 自动退化为关键词检索；
- API 返回 `search_mode_requested`、`search_mode_applied` 和白名单 `search_warning`；
- 前端明确显示“语义索引正在恢复，当前显示关键词结果”；
- 不向用户暴露异常正文、本地路径或凭据。

## 管理接口

超级管理员可查看 Worker、模型、索引版本、新闻/向量数量、缺失/变化/孤立计数、当前任务和历史任务，并可：

- 暂停或恢复自动同步；
- 调整同步间隔和批大小；
- 立即增量同步；
- 创建全量重建；
- 请求取消活动任务。

所有写操作使用 Session、CSRF 和超级管理员权限。
设置接口只更新 `enabled`、`interval_seconds`、`batch_size` 和审计字段，并在行锁内重新读取当前设置；不会用页面读取到的旧实例覆盖活动 collection、版本或 Worker 心跳。

## Docker 与持久化

`indexer` 共享：

- `./backend:/app/backend`
- `./chroma_data:/app/chroma_data`
- `./logs:/app/logs`
- `huggingface-cache:/root/.cache/huggingface`

`chroma_data/` 不进入 Git。容器删除或重启不影响数据库、向量或模型缓存。索引损坏时可以从 `News` 完整重建。

## 验收

- 新增新闻在一次同步周期内可被语义检索。
- 修改标题或摘要后 metadata 哈希更新。
- 删除新闻后对应向量消失。
- 重复同步不重复写入。
- Worker 中断、容器重启和 Chroma 损坏后可恢复。
- 索引不可用期间搜索返回降级结果而不是 500。
- 普通用户无法访问索引控制接口。
- Docker 重启后 app、crawler、indexer 均健康且数据持久化。
