# NewsHub 场景驱动开发与后端 Mock

> 基线 `e74f7b1a4d0964680f90a4b808f59a7b180dce9e`；分支 `feat/scenario-testing-msw-20261025`。
> 状态：集成代码草稿。依赖锁文件、真实应用构建、浏览器验收与指定 Luna xhigh 门禁待完成。
> 这是原 NewsHub 的接入补丁，不是之前独立教学项目的替代仓库，也不是已通过的发布版本。

## 1. 做了什么，没有做什么

本批把**现有资讯列表 → 文章详情 → 私人已读状态**做成可重复的开发/测试路径，覆盖已识别的
身份、能力、栏目、偏好、来源、分类、阅读统计和侧栏启动请求。

页面仍调用原来的 `services/api.ts` / `workspaceApi.ts`；`newsQueries.ts` 与 `types/news.ts`
继续负责查询和响应解析。没有另建 API Client、Domain Store 或教学页面，没有把组件改成依赖假数据。

实现结构：

```text
真实组件 / Hooks / Query / API Client / 现有 parser
                       ↓ 真实 HTTP 请求
             MSW 浏览器拦截 / MSW Node 拦截
                       ↓
         src/mocks/backend.ts（合成状态、响应序列）
                       ↑
         scripts/mock-backend.mjs（可选本机 HTTP 服务）
```

这里的“后端 Mock”是**独立的合成 HTTP API 服务**，不是修改 Django 为假实现。
浏览器模式和独立 HTTP 模式是两种入口；浏览器默认不连接独立 Mock 服务，更不连接真实后端。

未实现 AI 问答/翻译/研究 SSE、RSS 引擎写入、OPML 导入、管理员页面的完整场景。
未知 API 返回 `501 mock_unhandled`，不返回通用成功对象、不透传生产、不调用收费模型。
这些后续业务接入点应逐项扩展，不能把本批称为 NewsHub 全功能覆盖。

Mock 的版本计数仅覆盖 JavaScript 安全整数；Python/数据库 64 位极限、真实认证/CSRF 与细粒度 ACL
仍由后端真实测试负责。Mock 并不完整复刻 Django 中间件或所有 HTTP 解析细节。

## 2. 首次接入与依赖

使用 Node 22.16+（本工程脚本使用 `--experimental-strip-types`），遵循仓库 CI 的 Node 22 路线。
MSW 固定 `3.0.3`，Playwright 固定 `1.64.1`。两者的官方 release 已核查；运行兼容性尚待验收。

本包**没有伪造或重建整个 package-lock.json**。原锁文件必须保留，在实际 checkout 中生成最小增量：

```bash
cd frontend
# 先由指定验收任务检查是否已有兼容环境；不要覆盖其他工作区的 node_modules。
# 在获准创建独立环境时，用仓库声明的 npm 版本生成/安装锁定依赖。
npm install --package-lock-only --ignore-scripts
# 审查 package-lock.json 的新增传递依赖，不接受无关的大面积版本更新。
npm ci
npx playwright install chromium
```

若仍无网络，状态保持 BLOCKED。不能运行 `npm ci` 后忽略 manifest/lock 不一致，也不能手填 integrity。
无需数据库、真实 Session、RSS、短信或模型密钥；不要复制生产 `.env` 或真实数据到该工作区。

## 3. 浏览器开发模式

```bash
npm run dev:mock
npm run mock:catalog
```

打开 `http://127.0.0.1:9530/?scenario=normal`。

仅 `vite.mock.config.js` 在 `serve + mock` 模式替换 HTML 启动入口；先等待 MSW 激活，再加载原 `main.jsx`。
原 `vite.config.js`、`main.jsx`、`App.tsx` 与真实请求重试策略不变。Mock 启动失败或场景名错误时不挂载应用。
底部有 MOCK 标识；修改 URL 的 `scenario` 并整页刷新，即重建状态、缓存和组件。

SPA 跳转不会重新选择场景：列表进入详情，即使链接不带 scenario 参数，当前场景仍有效。
直接刷新一个没有 scenario 参数的地址会恢复 `normal`，这是显式约定，不是持久化场景选择器。

安全边界：仅 `127.0.0.1`；专用端口；不加载 `.env`；移除原 `/api` proxy；逃逸 MSW 的 API 请求由 Vite
返回 503；对外连接由开发 CSP 和 MSW 拦截策略限制。Mock 配置拒绝 build/preview/公开绑定。
不要把这个开发服务部署为线上预览服务或把端口复用于生产应用。

## 4. 独立后端 Mock

```bash
npm run mock:backend -- normal 9531
curl http://127.0.0.1:9531/__mock__/health
curl 'http://127.0.0.1:9531/api/news/?representation=summary'
curl -X PATCH http://127.0.0.1:9531/api/me/news/910001/read-state/ \
  -H 'Content-Type: application/json' \
  -H 'X-Workspace-Viewer: 79001' \
  -d '{"is_read":true,"expected_version":0}'
curl -X POST http://127.0.0.1:9531/__mock__/reset \
  -H 'X-NewsHub-Mock-Control: reset'
```

一个进程/端口只拥有一个场景实例；并行测试各用随机端口（`port: 0`）或独立进程。
绑定地址不可配置为公网。Host/Origin 校验、64 KiB 请求体上限、关闭/中断清理均在适配器中。
只支持同源 HTTP 调试；没有开放跨源 CORS，不能把浏览器普通端口直接连到它冒充真实 API。

## 5. 场景目录

| ID | 验证重点 |
|---|---|
| normal | 真实页面读取文章，已读保存成功 |
| news-empty | 200 空列表与订阅引导 |
| news-error | 持续 503，错误状态不显示旧数据 |
| news-retry | 前两次 503，耗尽现有自动重试后手动恢复 |
| news-slow | 延迟 1500ms，等待期间不显示假数据 |
| news-network-error | 连接错误，不伪装为 HTTP 500 |
| news-malformed | 必需 title 缺失，真实 parser 拒绝 |
| news-rate-limited | 429 + Retry-After，页面仍按当前统一错误 UI 验证 |
| search-race | 旧请求慢、新请求快；旧结果不能覆盖新意图 |
| detail-not-found | 文章 404，真实页面错误与重试入口 |
| summary-only | 正文无授权，不返回或显示受限正文 |
| read-save-error | 保存失败不显示已读成功 |
| read-conflict | 409 → 重读版本 → 用户再操作成功 |
| read-load-retry | 读取状态失败后恢复 |
| auth-expired | 匿名阅读、私人接口拒绝、个人按钮不出现 |
| read-only | 公共模式能力和写操作关闭 |
| capabilities-unavailable | 能力请求失败仍 fail-closed |

不要为让场景“看起来正确”而修改生产规则：当前 ReadStateButton 不是乐观更新；查询默认自动重试一次；
429 页面目前并未实现倒计时。矩阵分别验证这些真实行为，不虚构产品已经拥有更丰富的交互。

## 6. 四层测试与验收

| 层 | 文件/命令 | 能证明什么 |
|---|---|---|
| 纯 Mock 核心、HTTP 与隔离 | `npm run test:scenarios:core` | 响应序列、CAS、边界、实例/资源隔离、HTTP 适配 |
| 真实 parser / API / 组件 | `npm run test:scenarios:integration` | 原解析器、Axios/CSRF/viewer header、ReadStateButton 集成 |
| 真实浏览器场景矩阵 | `npm run test:scenarios:e2e` | 原应用路由与用户操作；响应来自 Service Worker；无漏 Mock API |
| 真实后端契约/安全 | 保留已有 Django tests 和受控真实集成 | Session、真实 CSRF、权限、DB/引擎授权，不由 Mock 替代 |

`e2e/scenarios/matrix.mjs` 是独立的需求预期；不得从 mock handler 的返回值自动计算验收答案。
目录和矩阵有一一覆盖检查，但“有同名用例”本身不证明断言质量。
Node `setupServer` 复用 MSW handlers；组件集成测试不 `vi.mock(services/api)`。
浏览器开启 Service Worker，不混用 `page.route()` 模拟相同接口。

建议的本地验收顺序（由仓库指定的 `newshub-test-acceptance-luna` 单一任务执行）：

```bash
npm run mock:drift
npm run typecheck
npm run typecheck:scenarios
npm run lint
npm run test:scenarios:core
npm run test:scenarios:integration
npm run build:checked
npm run test:scenarios:e2e
```

另选择已有 ReadStateButton / news parser / query / 权限相关回归；不要未经授权跑完整套件、CI、生产或 provider。
Playwright `retries: 0`，每用例独立 context，失败保留 trace/screenshot 和脱敏网络摘要。
窄屏测试是 Chromium viewport 验收，不等于 Android/iOS 人工 UAT。

## 7. 契约变化应该改哪里

网络响应仍在 `types/news.ts` 等现有边界解析，再进入 Query/组件。
本批演示真实已有的 `content → summary` 兼容，以及额外字段不影响稳定输出、必需字段缺失必须报错。
没有把教学包虚构的 `lab-v2` 接口加入生产兼容层。

后端只改字段/包裹结构：先增加独立 wire fixture 和契约用例，再在现有 parser/adapter 改映射。
后端改变字段语义/权限/业务流程：不能只做重命名，应同时审查业务规则和对应矩阵。
`mock:drift` 比较关键真实文件的 Git blob，只是变动告警，不是后端契约已通过。

## 8. 添加下一项业务

复制 `scenario-template.md`，先写用户经历、输入、步骤、预期、错误恢复、身份/版本/取消边界。
随后依次增加：catalog 配置 → fixture → 后端 handler 状态逻辑 → 独立 Matrix → 原 API/parser 测试 → UI 验收。
扩展 AI 流式功能时必须沿用真实 SSE 事件和 terminal/cancel 回执，不把 EOF 当成功，不调用真实 provider。
扩展 RSS 订阅时先核查当前 API/operation 状态与权限，再增加成功、重复、限流、同步失败等经历。

## 9. 生产与 CI

`npm run build` 保持原行为；新增 `build:checked` 在真实 build 后扫描保留 Mock 标记和 Worker 资产。
Mock Worker 不复制到 public。静态扫描器通过不代表所有生产安全风险都消失。
本批未修改 `.github/workflows`；通过本地验收后再按现有变更路由接入专用场景任务。
不要用 Mock 通过替代后端真实契约门禁，也不要触发每次前端提交都跑全后端的配置退化。

## 10. 当前未完成项

当前执行环境不能解析 npm，无法建立完整依赖环境；指定 Luna xhigh 代理不可调用。
因此仅做了源码语法与补丁完整性检查，没有运行本批功能测试、构建或浏览器验收。
必须生成/审查 lockfile、完成上述验收和指定提交门禁，才能推送实现并开启 PR。
