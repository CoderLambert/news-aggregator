# 默认 RSS 目录：OPML 导入、栏目发现与回滚

基线：`bfe2a6ad9331af0fbc5c7f7a26411079c8608cc1`。
分支：`feat/opml-default-catalog-20261026`。

## 已实现的边界

- 复用 `FeedDirectorySnapshot` / `FeedDirectoryEntry`，不新增个人分组模型或数据库迁移。
- 导入完整两级 OPML：5 个一级栏目、21 个二级分组，每组至少 20 个唯一 Feed URL。`AI / 大模型`、`DevOps / 云原生` 是完整名称，不按斜杠拆分。
- 将栏目映射为稳定目录标签；已有 Feed 以保守 URL 身份匹配并保留稳定 ID、名称、简介、语言、出处和许可证。只补充分类标签；隐藏条目不重新公开，原有渠道和 RSSHub 模板不删除。
- 全站目录与个人订阅分离。导入不创建用户分组、订阅、Source、FeedBinding 或网络任务；不会把来源分类写入所有文章的 `News.category`。
- 管理命令默认只做 dry-run。正式应用同时锁定输入文件、预览计划、当前快照，短事务原子切换；重复应用不产生重复频道或快照。
- 手工发布/回滚的快照标记为 `activation_policy=manual`，现有启动/每日 `import_pinned_seed()` 不得覆盖。后续种子升级需由管理员另行审阅发布，不自动合并新种子。
- 原 `/api/rss/directory/` 新增 `section/group/language/region` 筛选、5/21 目录计数及 `catalog_paths`；保留旧 9 类 `category` 筛选及旧无新增筛选游标。游标绑定全部筛选参数和快照版本。
- 现有「添加订阅」界面新增一级栏目、二级分组、语言、地区筛选；仍经原确认订阅和 Miniflux 流程接入。切换账号重置本次选择。公共分类不会自动覆盖个人分组。

## 输入

复用用户已有的完整 `NEWSHUB-CURATED-502-ADMIN-CATALOG.opml`，不要把 502 条文件送入个人 OPML 导入器，也不要用其中一个分组文件代替全站目录。

冻结输入 SHA256：

```text
22621f6305edb27f3a34b840b72add5d7a7a2ca536cbbbd68b2a8fa8cdb034aa
```

目录编目输入 502 条：技术 228，商业 71，行业 110，新闻时事 69，人文与阅读 24。与服务器现有目录合并后，**总条数可能大于 502**；报告的 incoming/added/reused/total_entries 不可混用。每组计数按唯一 Feed URL，不代表独立媒体数。

不把外部验活记录写成 NewsHub `verified_at`。本输入源元数据的统一许可证没有在当前材料中确认，默认 `NOASSERTION`；`--acknowledge-provenance` 是操作员审阅声明，不是授权证明。原有集合许可证不改变。输入内容 SHA256 保存在来源 revision 字段，报告明确标注 `source_revision_kind=opml_sha256`，不是伪造的 Git commit。

## 导入（在已配置且获准操作的 NewsHub 环境中）

先确保项目原有迁移已完成；本功能没有新迁移。使用项目兼容 Python 环境，不使用另一个工作区的生产数据库做测试。

在仓库根目录设置实际 OPML 路径，先预览：

```bash
PYTHON=backend/venv/bin/python
OPML="$HOME/Downloads/newshub-rss-main-aligned-20261024/NEWSHUB-CURATED-502-ADMIN-CATALOG.opml"
"$PYTHON" backend/manage.py import_curated_rss_catalog \
  --file "$OPML" --dry-run > /tmp/newshub-catalog-plan.json
cat /tmp/newshub-catalog-plan.json
```

检查 5/21 数量、原目录保留、新增/复用/隐藏条目情况和来源声明后，再应用同一个预览：

```bash
INPUT_HASH=$("$PYTHON" -c 'import json; print(json.load(open("/tmp/newshub-catalog-plan.json"))["input_checksum"])')
PLAN_HASH=$("$PYTHON" -c 'import json; print(json.load(open("/tmp/newshub-catalog-plan.json"))["proposed_checksum"])')
PREVIOUS=$("$PYTHON" -c 'import json; print(json.load(open("/tmp/newshub-catalog-plan.json"))["previous_checksum"] or "none")')
"$PYTHON" backend/manage.py import_curated_rss_catalog \
  --file "$OPML" --apply --input-sha256 "$INPUT_HASH" \
  --plan-sha256 "$PLAN_HASH" --expected-active "$PREVIOUS" \
  --acknowledge-provenance > /tmp/newshub-catalog-applied.json
```

正式写入前任一哈希或当前版本改变都会拒绝，需重新 dry-run；不要盲重试。只有指定 `--apply` 才写目录。没有 `--skip-dns-check`：编目是离线操作，真实接入仍保留服务器的 DNS/URL/重定向安全策略。

导入成功后重新打开「频道管理 → 添加频道」，在默认 RSS 栏目中选择栏目/分组，结合关键词搜索，再选择个人分组并确认订阅。目录浏览不会自动订阅。

示例只读接口：

```text
GET /api/rss/directory/?section=tech&group=frontend&language=en&q=React
```

文件未提供地区的来源不会被猜测为国内/国际；地区筛选只匹配有明确元数据的条目。

## 回滚

仅当导入前存在目录快照时，`previous_checksum` 才是可回滚目标。保留上面的预览/应用报告；第一次在空数据库导入不承诺存在旧快照。

```bash
CURRENT=$("$PYTHON" -c 'import json; print(json.load(open("/tmp/newshub-catalog-applied.json"))["active_checksum"])')
"$PYTHON" backend/manage.py import_curated_rss_catalog \
  --rollback "$PREVIOUS" --expected-active "$CURRENT" --apply
```

只切换保留的快照，不删除目录历史、用户订阅、个人分组或文章。目标不存在或当前版本已变化则拒绝。回滚后继续手工发布保护，不会被运行时每日种子刷新覆盖。不要把旧代码回退当成此快照回滚命令的替代。

## 验证状态（本次环境）

| 检查 | 状态 |
|---|---|
| Python 纯解析/合并/分类单元测试 | PASS：20 项 |
| 用户原始 502 条 OPML + 上游原 URL 语法校验函数 | PASS：5/21/502、每组至少 20，离线检查 |
| Python compileall | PASS |
| TypeScript/TSX 转译语法检查 | PASS：4 个文件；不是语义类型检查或构建 |
| Django/DRF/事务/命令/种子保护集成测试 | BLOCKED：当前容器缺少 Django，依赖下载失败；测试已编写 |
| Vitest / 项目 typecheck / lint / build | NOT_RUN：没有完整依赖工作区 |
| 真实浏览器、Miniflux、线上 Feed、生产导入 | NOT_RUN |
| 独立代码审查/指定模型委派 | NOT_RUN：当前工具没有子代理执行器 |

没有声称已达到合并或生产验收门槛。代码留在独立开发分支，不合并、不部署、不运行生产导入。

在无真实凭据、独立数据库的完整工作区运行定向验证：

```bash
PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest -q \
  tests/rss_catalog/test_catalog_opml.py \
  backend/api/tests/rss/test_curated_catalog.py \
  backend/api/tests/rss/test_directory.py \
  backend/api/tests/rss/test_directory_http.py \
  backend/api/tests/rss/test_opml_import.py
cd frontend
npm run typecheck
npm run lint
npm run test:run -- tests/features/rss/CatalogTaxonomyFilter.test.tsx \
  tests/features/rss/DiscoverDialog.catalog.test.tsx tests/features/rss/DiscoverDialog.test.tsx
npm run build
```

若实例已有 `verified_at` 运行时数据，本导入器拒绝而不是抹掉证据；需要独立迁移方案。现有不同 URL 的重定向别名也不会凭猜测合并。
