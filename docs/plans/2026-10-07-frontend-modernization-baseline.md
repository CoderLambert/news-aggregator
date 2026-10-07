# 前端现代化重构：基线与迁移记录

日期：2026-10-07
用途：主助手审核前的基线记录；此轮未修改应用代码、依赖或接口。

## Git 与执行环境

- 分支 main，HEAD e3af907fb87a51a9f68447519b6f2e401c01d293（origin/main 同步）。
- 盘点前工作树干净；Node v24.21.0、npm 11.19.0、pnpm 10.33.3。
- frontend 同时有 package-lock.json 与 pnpm-lock.yaml，package.json 未指定 packageManager；两锁解析版本不同。当前 npm 安装与 npm 锁一致（React 19.2.6、Router 7.15.1、Vite 8.0.13），pnpm 锁含 React 19.2.7、Router 7.17.0、Vite 8.0.16。加依赖前先根据仓库 CI/开发约定选定规范锁文件，避免锁文件漂移。
- 项目内没有 AGENTS.md 或 .agents/skills 指引。未发现运行中的 Vite/API 进程；frontend/.dev-pids 中的 PID 583/584 已无对应服务，5173 端口不可连接。可用浏览器清单为空，因此此轮不能做浏览器视觉 QA。

## 当前前端与功能

这是 Vite + React 19 + React Router 7 的 SPA。Tailwind CSS 4 已接入，components.json 是 shadcn/ui 配置（tsx=false），src/components/ui 已有 alert、badge、button、card、input、skeleton、toggle-group。vite.config.js 已启用 React Compiler、路径别名、React.lazy 路由分包和构建 chunk 分组；App.jsx 已有 Error Boundary 与 Suspense。不要重复搭这些已有基础。

路由和功能：/ 新闻列表（关键词/语义/混合搜索、分类/来源筛选、分页）；/search 高级本地搜索（URL 查询、排序、全文/时间/来源类型筛选）；/news/:id 新闻详情（抓取全文、SSE 翻译、聊天、文内搜索/目录、朗读、点赞/收藏/屏蔽）；/favorites 收藏与屏蔽管理；/provider-comparisons 抓取 Provider 对比和重测；/__mascot__ 预览页。全局还有账号登录/注册、中文/英文界面与文章显示模式、Research 面板（会话/本地或联网检索/流式追问）和语音播放器。以这些现存行为作为回归范围。

## 数据与状态边界

- 前端 API 集中在 src/services/api.js，路径位于 /api 下：新闻、分类、来源、收藏/点赞、屏蔽、Provider 对比、Research、认证等。Django 后端在 backend/api/urls.py/views.py 实现。
- Axios 请求包含 Django cookie session、CSRF header 和语言参数；文章翻译、聊天、Research 使用已有 SSE 流式工具。保持接口路径、参数、请求字段、cookie/CSRF 与事件语义。api.js 中仅全文抓取方法显式接收 AbortSignal；底层 streamingFetch 可接受 Fetch init.signal，但聊天/翻译/Research service 尚未暴露取消参数；列表、详情等普通请求也未统一传递 signal。
- 当前没有 TanStack Query、Zustand 或 TypeScript 依赖，也没有 TS/TSX 页面；页面和 hooks 用 useState/effect 手动载入远端数据。新闻筛选、详情、收藏、Provider 对比各有独立请求/加载状态。LocalSearch 将 URLSearchParams 与本地 state 镜像；新闻列表筛选保存在 localStorage。
- localStorage 当前保存界面语言、文章显示模式及新闻列表筛选。AuthContext 管理后端 cookie session；不要把鉴权/token 或服务端新闻数据放入 Zustand。
- 建议 Query 管理新闻/分类/来源/详情/收藏/屏蔽/Provider/Research 的服务端数据、错误、缓存、取消及失效；Zustand 仅接管确实跨组件共享的客户端偏好（例如界面语言/文章显示模式）。React Router URL 参数保持为 URL 唯一真源；纯局部开关仍留在组件内。

## 分阶段实施及验收

1. **边界与基础**：选定包管理器/规范锁；建立 strict TypeScript 逐步迁移配置（先允许存量 JS）；为 API 响应、请求参数、新闻/用户/分页定义类型；创建 QueryClient 与稳定 query-key 约定。验收：TS 检查可运行，不改变 API/鉴权/存储语义，现有测试通过。
2. **列表和搜索纵切**：迁移新闻、分类、来源查询；让 Query 缓存作为远端数据唯一来源，保留现有筛选/分页/排序/搜索结果；URL 查询状态不复制进 Zustand；传递 AbortSignal。验收：列表、筛选、模式切换、分页、URL 分享/返回正常；加载/错误/空态和重复请求覆盖测试。
3. **详情与用户数据纵切**：迁移详情、收藏/屏蔽状态及 Provider 页面；用 mutation 失效相关 query。保留全文抓取、翻译、聊天、Research 的 SSE reader 与数据契约，流完成时定向更新/失效 Query 缓存。验收：详情/收藏/屏蔽/重测与流式功能回归通过，切页取消请求，缓存失效测试覆盖。
4. **UI 状态与逐步类型化**：用 Zustand 托管跨组件共享 UI 偏好；保留 AuthContext 和页面局部状态。沿用 shadcn/ui 与 Tailwind 主题/响应式规则，增量迁移业务模块到 TSX，不引入 any 扩散。验收：键盘可达、图标按钮可读、移动端布局通过；最终 TypeScript、lint、前端测试、production build 通过。

完成每个纵切后记录实际验收命令和结果；端到端浏览器验收须在本地测试服务/安全测试数据可用后进行，不接触生产数据。

## 当前检查结果与审计注意

- npm run test:run -- --configLoader native：28 个测试文件、159 个测试通过。
- npm run build -- --outDir /tmp/news-aggregator-baseline-dist --emptyOutDir --configLoader native：通过；构建只输出到 /tmp。图表/代码高亮 chunk 中存在 Mermaid 与 Shiki 动态语言模块，继续保留功能并按实际加载图谱衡量体积，不能照旧审计建议直接卸载。
- npm run lint：失败，10 errors、3 warnings，主要涉及未使用符号、Research/LocalSearch/Provider 页面同步状态的 effects 及依赖项。分阶段记录原有问题，不将它们误判为重构引入。
- frontend/docs/audit-*.md 日期为 2026-05-31，部分判断已过时：当前已有 28 个测试文件、React Compiler、懒加载路由、Error Boundary；Shiki/Mermaid 和 react-markdown 均仍被实际内容功能使用。以当前代码和命令结果为准，不照搬旧审计中的卸包或路由建议。

## 2026-10-07 实施检查点：新闻列表纵切 1

分支：`codex/frontend-list-query-slice`，起点为 `e3af907fb87a51a9f68447519b6f2e401c01d293`；实现已在本地提交，未推送。初始盘点后确认仓库 README、测试说明和脚本均以 npm 为唯一入口，因此将 `frontend/packageManager` 固定为当前环境的 `npm@11.19.0`，保留 `package-lock.json` 并删除未被仓库入口引用的 `pnpm-lock.yaml`。如果贡献者此前依赖 pnpm，需要改用 npm。

已完成首个首页列表切片：

- 引入 TanStack Query v5 和 Zustand v5；添加 `QueryClientProvider`、共享 QueryClient、失败重试规则和 TS strict 检查入口。
- 首页从 `NewsList.jsx` 迁为 TSX。搜索词/模式、分类、来源和页码现在以 URL 查询参数为唯一真源；分类、来源请求并行；新闻响应在 unknown 边界做运行时解析。
- 新闻列表 query key 覆盖分页/筛选、界面语言和后端用户 ID；首页请求、分类和来源请求均将 TanStack 的 `AbortSignal` 传给 Axios。筛选与翻页会更新 URL，翻页可通过后退/分享恢复；旧 localStorage 筛选只在没有 URL 筛选时导入一次到 URL，然后移除旧副本。
- 共享界面语言、文章显示偏好迁入 Zustand，继续读写原有 `newshub_lang` 和 `newshub_display_mode` 两个 localStorage key。AuthContext 迁为 TSX，校验后端用户响应，并在用户身份变化/登出时清理个性化列表缓存。
- 首页卡片的现有屏蔽按钮使用 mutation，成功后失效列表缓存；详情页点赞/收藏按钮及 `/search` 高级搜索仍待后续切片迁移。
- 添加首页 URL/query、query key / signal、屏蔽 mutation 成功失效与失败不失效测试；更新 SearchBar 测试以通过 Zustand store 设置偏好。

## 首个切片验收

- `npm run test:run -- --configLoader native`：31 个测试文件、166 个测试通过。
- `npm run typecheck`：通过。
- 新迁移文件的 ESLint 定向检查：通过。
- `npm run lint`：仍失败；10 个 errors 和 3 个 warnings 均在未迁移的 Markdown、Research、LocalSearch、ProviderComparisons 文件，与首轮记录的基线一致；本切片无新增 lint error。
- `npm run build -- --outDir /tmp/news-aggregator-list-slice-dist --emptyOutDir --configLoader native`：通过。
- 浏览器端到端验收：NOT_RUN。隔离 Vite 服务可启动，但本机 Chromium 以代码 133 退出并报告 Crashpad `setsockopt: Operation not permitted`；未更改 flags、未禁用 sandbox、未继续绕过此策略。后端 API 此环境未运行，因此列表 API 浏览器端到端和真实数据行为仍未验收。
- 安装依赖时 npm 提示依赖树有 19 项审计告警；未运行 `npm audit fix`，也未升级无关依赖。

## 待续范围

下一切片应延续该分支和本记录，迁移详情用户数据/Provider 或高级搜索中的一条纵向路径；覆盖 mutation 成功/失败与 Query 缓存失效，再逐模块迁移剩余页面和 SSE 取消/缓存语义。高级搜索路由当前仍保留既有 URL/local state 镜像，不能声称全前端迁移完成。真实 API 浏览器验收需等可用的非生产 API 环境及不冲突端口。

## 2026-10-07 最终审查修补：列表接口回归

分支：`codex/frontend-list-query-slice`。本轮仅补齐首个列表切片在鉴权、URL 导航和现有屏蔽操作之间的接口行为：

- TanStack Query 列表占位数据只在上一查询与当前查询的 `viewerId` 和语言相同时复用；实际 `AuthProvider` 登出及切换账号测试证明新响应到达前不会显示上一身份的列表。
- SearchBar 的防抖提交读取最新 URL 回调；筛选/搜索模式变化会合并到最近 URL，浏览器前进/后退替换搜索值时会取消未提交草稿。
- NewsCard 将当前路径与查询串保存在路由 state；详情返回恢复来源 URL，直接打开详情仍回退首页。
- 列表/详情屏蔽和详情/收藏页取消屏蔽成功后统一定向失效 `newsKeys.lists()`；失败不失效。列表→详情屏蔽→返回以及取消屏蔽→返回测试均确认恢复原筛选 URL 并重新请求列表。

验收：定向回归 7 个文件、30 项测试通过；完整套件 34 个文件、178 项测试通过；`npm run typecheck`、变更文件 ESLint、production build 均通过。完整 `npm run lint` 仍为原基线的 10 errors、3 warnings，均在未修改的 Markdown、Research、LocalSearch、ProviderComparisons 文件。浏览器端到端仍 `NOT_RUN`：Chromium Crashpad sandbox 限制未绕过；未启动后端或触碰生产数据。

## 2026-10-07 小修：相同搜索词的历史 POP

SearchBar 现在按 React Router 的 POP 导航 key 重置当前草稿并清除防抖定时器。列表分类/来源等 PUSH 导航不会清除输入，所以输入后切换筛选仍会合并到最新 URL。新增相同 `search`、不同 `category`/`page` 的后退与前进回归。定向验证：NewsList/SearchBar 2 个测试文件、13 项通过；TypeScript 检查和变更文件 ESLint 通过。
