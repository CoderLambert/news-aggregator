# Default OPML catalog implementation

Base: `bfe2a6ad9331af0fbc5c7f7a26411079c8608cc1`.
Branch: `feat/opml-default-catalog-20261026`.

Goal: import the reviewed 5-section / 21-group OPML into the existing public directory; do not subscribe users or change private group models.

Approach: use stable taxonomy tags in existing directory entries (no schema migration); parse OPML locally with bounded defusedxml; merge with the active snapshot while preserving origin + key, hidden entries, and route templates. Publish only through the existing atomic snapshot importer with an expected-active checksum. Keep old nine-category filters and cursor behavior when new filters are empty.

- [x] Parser/merge unit regressions: nested labels containing slashes, all 21 groups, duplicate URL union, malformed XML, bounds, no network, preservation and idempotence.
- [x] Administrative dry-run/apply/rollback command, no user/engine writes, explicit content checksum and active-snapshot compare-and-swap.
- [x] Existing directory API section/group filters and counts; pagination binds all filters.
- [x] Existing DiscoverDialog navigation; keep personal subscription confirmation and group selection unchanged.
- [x] Pure-module tests, inline source/diff review, import instructions and evidence.
- [ ] Full-workspace Django/Vitest/typecheck/build and live acceptance (blocked/not run; see README).

Environment: the ChatGPT container cannot resolve github.com and has no Django/Python 3.12 project environment. GitHub connector provides pinned source and isolated branch writes. Pure Python checks are supplemental; do not report unavailable Django/Vitest/production checks as PASS. No subagent execution tool is available; review is inline. No production database access or deployment.

## 执行记录

- 已实现离线 OPML 适配、增量合并、CAS 发布/回滚命令、目录筛选与前端接线。
- Ruling: 使用现有目录 tags 表达公共 5/21 分类，不复用用户私有分组表；没有新 migration。
- Ruling: 输入 digest 属于 OPML 内容版本，许可证未知保留 NOASSERTION。
- Ruling: 发现每日 seed 重激活会覆盖管理员发布，增加 manual activation policy 并在 writer reservation 后复核。
- Ruling: 当前只能运行 Python 纯模块和 TS 语法验证；Django/Vitest/浏览器/Miniflux 未验收，不将其标成 PASS。
- 用户请求新分支实现；仅保存本次隔离分支代码，不开 PR、不合并、不部署、不主动派发 CI。
