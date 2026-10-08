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

## 2026-10-07 实施检查点：高级搜索、详情与用户新闻数据纵切

分支：`codex/frontend-list-query-slice`，本切片起点 `db3585357fab4573bceb40655b85aa1bad5da50e`。没有改 API 路径、请求字段、Django cookie/CSRF 或业务响应含义，也没有加依赖。

- `/search`、`/news/:id`、`/favorites` 和详情互动按钮已迁至 TSX。高级搜索的已提交词、模式、页码、排序、全文、时间和来源类型仅由 URL 管理；未提交的输入草稿仍是输入组件局部状态。TanStack Query 使用现有搜索参数、语言和 viewer ID 建缓存键，读取传递 `AbortSignal`，同一 viewer/语言切换筛选时可复用占位结果。保留后端既有参数映射：时间范围转为 `publish_time_after`，多选来源类型仍只提交第一项。
- 详情由 Query 按新闻 ID、语言和 viewer 查询。全文抓取及翻译 SSE 仍通过现有 hook 使用 `setNews`，该 setter 现在写入当前详情 query cache；聊天 SSE 没有迁移。
- 收藏/点赞状态、屏蔽状态、收藏列表和屏蔽列表使用 viewer 专属 query keys。Query 查询函数均传 `AbortSignal`。Mutation 先校验 API 响应，成功后按目标 viewer 更新已缓存的状态/列表并失效关联列表；拒绝或无效响应保持原状态并显示错误。详情按钮在状态未知或请求进行中时禁用，避免未知状态下重复切换。退出或切换账号仍清除个性化 Query 缓存。
- 新增 URL 驱动高级搜索测试、Query detail/取消请求/身份隔离测试、收藏/屏蔽成功和失败缓存测试，以及使用 mock API 的搜索→详情→收藏/取消→列表→屏蔽/恢复跨页回归。测试不连接 Django、写入数据库或调用 AI。

验收：`npm run test:run -- --configLoader native`：36 个测试文件、189 项通过；`npm run typecheck`：通过；所有变更源文件和相关回归测试 ESLint 定向检查：通过；production build 输出至 `/tmp/news-aggregator-user-data-slice-dist`：通过。完整 `npm run lint` 仍失败，9 个 errors/2 个 warnings 都在未修改的 MarkdownContent、ProcessTimeline、ResearchHeader、useResearch、ProviderComparisons 文件；首轮记录的 LocalSearch lint 问题已随本次 TSX/Query 迁移消除。本切片未运行真实 API 浏览器 E2E：沿用已记录的 Chromium Crashpad `setsockopt: Operation not permitted` 限制，没有尝试绕过 sandbox。

本切片代码已本地提交：`35d28ab`（`refactor frontend search and user news flows`）；未推送。审阅材料延续同一 Library 文件，准备更新到版本 4。后续审查范围仍包括 Provider Comparisons、Research/其他服务端状态及全局剩余 JS 类型边界；本记录不代表全部前端迁移完成。

## 2026-10-07 P2 收口：搜索草稿与用户状态竞态

起点：`b244fd1593536fdeaadcebed3d240554a8291e4f`。本轮仅修复上轮独审确认的搜索/屏蔽/收藏响应边界；没有更改 Django API 语义、鉴权或业务数据。

- `/search` 去掉 `SearchControls key={location.key}` 全导航重挂。URL query 实际改变时同步输入；仅在新的 POP 导航信号到达时回填 URL query，即使 q 相同、其他筛选不同也会同步。其他 mode、sort、全文、时间和来源类型 PUSH 都保留未提交草稿，并且 POP 后的首个 PUSH 不会再次清空草稿。
- block/unblock 在 mutation 开始时取消精确 viewer/news block-status query；响应成功后再次取消期间重启的同 key 读取，写入服务端确认状态并使该 status key 与列表 key 失效。deferred GET 回归覆盖 mutation 前和 pending 期间启动、在成功后才返回的旧响应。
- 收藏 toggle parser 接受真实并发边界 `{created:false}`（以及归一化为双 false 的 no-op）；该响应不改变状态计数或列表项，只失效状态/列表查询以重读，不触发重复 POST。双 true、错误类型或缺少 flags 仍视为畸形响应并不改缓存。
- Favorites 页面用一个共享 unblock mutation observer，因此 pending 期间全体“恢复”按钮串行禁用，避免 observer 的 `variables` 更新后旧行提前重新可点。

验收：完整 `npm run test:run -- --configLoader native`：36 个测试文件、199 项通过；`npm run typecheck`：通过；变更源文件及回归测试 ESLint 定向检查：通过；production build 输出至 `/tmp/news-aggregator-p2-slice-dist`：通过。完整 `npm run lint` 有 9 个 errors、2 个 warnings，均在未修改的 `MarkdownContent.jsx`、`ProcessTimeline.jsx`、`ResearchHeader.jsx`、`useResearch.js`、`ProviderComparisons.jsx`，与上一轮记录的全仓基线一致；本轮变更文件 lint 通过。没有运行浏览器 E2E，也没有启动 API、访问数据库或调用 AI。工作仍未代表 Provider Comparisons、Research 等剩余模块全部迁移完成。

本轮实现已本地提交：`3cbb9aca148c8ff6aef6e10c0032cb5a769826c2`（`fix frontend search and user state races`）；未推送。审阅补充延续同一 Library 文件，准备更新到版本 6。

## 2026-10-07 实施检查点：Provider 对比与 Research/SSE 纵切

本切片起点为 `9b8329c73b6f86985b79176ec53f103108f9bc5e`。Provider 对比和 Research 面板及依赖组件迁为 TSX，Research SSE 增加运行时事件解析、任务 reducer 与断线重连回放；没有改 API 路径、请求字段、Django session/CSRF 或后端行为，也没有增加依赖。

- TanStack Query 负责 Provider 对比列表、创建/重测后失效，以及 Research 会话、会话详情和持久化结果；viewer/语言参与个性化缓存键，查询传播 AbortSignal。流式增量消息保存在当前 Research 任务本地状态，不复制进 Query 或 Zustand。Zustand 仍只持有全局客户端偏好。
- Research stream 事件按会话和任务连接归属应用；tool call/result 按 call ID 去重，允许 result 先于对应 call 到达；complete/error 是终态，忽略之后到达的迟到事件。完成后重取持久化会话快照；手动停止仅中止当前浏览器读取，页面明确说明后端 worker 继续运行。刷新/重访可通过已有 GET stream 端点订阅仍活动的任务并接收 replay；已完成结果由会话 Query 恢复。
- Research 不因挂载、重渲染或重试自动重复创建昂贵任务；创建请求有同步锁，失败/断线用现有任务 ID 恢复。Provider create 仍是现有同步单 POST，不增加自动重试。每个 provider retest 独立发请求、维护 AbortController 和“停止等待”状态；停止仅结束浏览器侧等待，既有 API 没有取消后端 provider 任务的语义。
- Provider/Research API 和 UI props 增加 TS 类型与 unknown 响应边界检查；Button/Input 共享控件迁为 TSX 修复原有 JS 推断问题。`MarkdownContent.jsx` 移除两处现有未使用符号，使完整 ESLint 可以通过。未改无关业务数据或凭据。
- 新增 reducer、Research hook/面板、SSE API、Provider API/UI 回归：去重、乱序、complete 后迟到事件、断线恢复、显式取消、失败重试、切换会话/用户、Provider 防重复创建及逐行独立停止等。

验收：`npm run test:run -- --configLoader native`：40 个测试文件、215 项通过；`npm run typecheck`：通过；`npm run lint`：通过。production build 用 `npm run build -- --configLoader native --outDir /tmp/news-aggregator-provider-research-slice-dist --emptyOutDir` 输出至 `/tmp` 并通过。未在浏览器启动真实 API 测试：此前本机 Chromium 因 Crashpad `setsockopt: Operation not permitted` 退出；本切片没有绕过 sandbox，也没有连接 Django、生产/开发数据库或外部 AI。服务端 retest/Research worker 的实际中止仍需后端 API 支持，本前端不会声称停止了服务端执行。

本切片按本地提交保留，未推送，供主助手审查；此前已提交的高级搜索/详情/用户数据切片仍保存在本分支历史中。

## 2026-10-07 审查检查点：Provider 身份隔离与 Research 恢复

本轮起点为 `8bcc4215e0a03242cf2ae11ccbeb0914a98f9f4a`，分支 `codex/frontend-list-query-slice`。保留既有 API、cookie/CSRF、持久化结果和服务端 worker 语义；没有修改后端或增加依赖。

- Provider 对比查询等待鉴权完成后才执行，并按 viewer ID 隔离；登录身份切换会重挂页面。创建与逐行重测各自持有 AbortController，卸载或切换 viewer 时中止浏览器请求，迟到响应不写入新身份状态；成功后仅失效当前 viewer 的查询。
- Research 在收到流式响应头中的 session ID 时立即保存仅含恢复所需字段的、viewer/session 隔离的 sessionStorage 记录。重新挂载或切回历史会话时仅调用现有 GET stream/session 接口以恢复活动流或加载已保存结果，不会自动重发昂贵 POST。新会话尚未收到 ID 时的恢复由用户显式点击重试；界面说明原请求可能已被服务器接受，重新研究可能重复计算或收费。
- 停止只取消浏览器侧接收；已有 API 不支持取消服务端 worker，界面继续明确告知这一边界。测试覆盖身份切换/登出、迟到创建与重测响应、卸载取消、历史恢复 GET、停止后显式重试和连接所有权。

验收：`npm run test:run -- --configLoader runner`：40 个文件、226 项通过；`npm run lint`、`npm run typecheck` 均通过；`npm run build -- --configLoader runner --outDir /tmp/newsagg-p2-build --emptyOutDir` 通过。`git diff --check` 通过。

本地浏览器在隔离 Vite + 临时 Django 环境中验证了 Provider 创建、JINA 行重测，以及 Research 创建后停止接收、再继续接收并显示“本地确定性研究”结果。该环境只使用 `/tmp` 临时 SQLite 与确定性本地 mock；没有打开项目数据库、调用外部模型或 Provider API。临时服务已停止。浏览器验收截图随本轮审查结果提供。

本检查点只完成 Provider/Research 的身份与恢复边界，尚不表示整个前端重构完成。代码和本记录保留在本地分支，等待主助手审查；未推送。下一步先根据审查意见再继续。

## 2026-10-07 复审修补：Research 历史探测期间的发送边界

复审发现无恢复 checkpoint 的历史会话 GET 探测期间，hook 已持有连接锁但面板仍显示空闲；按 Enter 会清空输入，而 hook 静默拒绝发送。本轮只修复该边界并补直接回归：

- Research hook 将流式连接与历史恢复探测公开为 `isBusy`；探测中输入区显示停止接收状态、发送路径和建议问题均不可触发请求。输入草稿仍可保留供用户在探测完成后发送。
- `handleSend` 现在返回明确的 accepted 布尔值；面板只在同一份草稿确实取得发送锁时清空输入。连接忙时返回 false，不能清空或重复 POST。
- 延迟 GET 测试覆盖探测期间键盘发送被阻止、草稿原样保留、没有 create/chat POST，GET 完成后可发送且只清空已接受草稿。附加测试直接覆盖 viewer 间 sessionStorage 隔离，以及成功保存结果和删除会话后的恢复记录清理。

验收：定向 Research hook/面板测试 2 个文件、16 项通过；完整 `npm run test:run -- --configLoader runner`：40 个文件、231 项通过；`npm run lint`、`npm run typecheck`、`npm run build -- --configLoader runner --outDir /tmp/newsagg-p2-final-build --emptyOutDir`、`git diff --check` 均通过。没有修改后端/API，也没有改变“停止只取消浏览器接收”的既有语义。

## 2026-10-08 实施检查点：全文、翻译与聊天工作流

起点：分支 `codex/frontend-list-query-slice`，HEAD `bc9578b0238b3e180c509e54fcf76f18e1d32239`。本轮延续详情页 Query 与现有 API 契约；没有增加依赖，也没有修改后端。

- 全文抓取、翻译、聊天历史和推荐问题的 hooks/依赖组件迁为 TypeScript。新增 `newsWorkflowApi.ts` 的 `unknown` 响应解析边界；TanStack Query 管理聊天历史和推荐问题缓存，key 区分文章/语言及适用的 viewer，GET/POST/DELETE/流请求传播 `AbortSignal`。推荐问题仅在打开助手后加载，缓存失败不会自动重打昂贵 POST；用户点“换一批”才强制请求。
- 翻译 SSE 进度及聊天草稿/增量响应仍是按文章、viewer、语言隔离的本地 UI 状态。切换文章、账号或卸载会取消本页读取并阻止迟到结果写入新上下文。停止翻译/聊天只结束浏览器接收；UI 提示服务端任务可能继续，停止后不会自动重复提交。显式翻译重试保留已保存译文；聊天失败可显式重试并复用当前页面的临时对话行。
- 拆出对既有 chat SSE `__META__` 标记跨 chunk 的安全拼接，保留搜索来源、Markdown 与 Shiki 代码块/复制体验。后端聊天历史仍按文章保存，接口没有幂等键，因此服务器收到问题但浏览器断线后的再次发送仍可能使后端保存重复请求；前端能避免同一会话界面重复追加临时行，不能承诺服务器端幂等。
- 变更范围：`useFullArticle`、`useTranslation`、`useChat`、`useSuggestedQuestions`、聊天与全文展示组件；API 适配层只增加取消信号参数，URL、请求体、cookie/CSRF 和响应语义保持不变。AuthContext 账号切换时取消/清除文章聊天历史的私有 Query；公开推荐问题缓存保留。

验收：扩展定向回归 8 个文件、61 项通过；完整 `npm run test:run -- --configLoader native`：41 个文件、246 项通过；`npm run lint`、`npm run typecheck`、`npm run build -- --configLoader native --outDir /tmp/newsagg-p4-build --emptyOutDir` 和 `git diff --check` 均通过。无依赖变更。

本地浏览器用 `/tmp/newsagg-p4-evidence/isolated-browser-verified.sqlite3` 中的单条虚构新闻验收：全文由本地 fetch mock 返回，翻译 worker 与聊天流均为确定性本地 mock；推荐问题直接使用 fixture 缓存。浏览器确认全文获取、翻译渲染、发送聊天、刷新后译文和聊天历史恢复。项目 `backend/db.sqlite3` 未被打开/修改；没有真实模型推理、登录凭据或 API key。登录态未建立，现有 `/api/auth/me/` 在该环境返回 403；新闻详情及公开工作流端点仍完成验收。

验收图由 CUA 浏览器捕获并在审查会话中显示，演示标签为 `http://127.0.0.1:5180/news/1` 且已标记为 deliverable；此 CUA 会话没有提供将截图写入本地路径的接口。两个临时服务已停止。

验收环境注意：首次 Django 启动调用了既有 `ApiConfig.ready()` embedding 预加载钩子，观察到无凭据的 Hugging Face 模型元数据请求后立即中止；之后仅在临时进程设置 `RUN_MAIN=true` 禁用该启动预加载再运行确定性 fixture，无进一步外连。首次请求写入本轮专用 `/tmp/newsagg-p4-home/.cache` 的少量元数据，已删除；后续临时 SQLite 和构建目录仅位于 `/tmp`。

## 2026-10-08 P2 修补：聊天清空互斥与中断请求核对

起点：`767f2d8c86c6cacef2bf143e2f1eb8848341cce5`，分支 `codex/frontend-list-query-slice`。本次仅修补聊天交互竞态，不改 API 路径/请求/响应语义、后端、数据库或依赖。

- 确认清空时立即安装互斥锁、取消本页流并禁用重复清空与发送；DELETE 失败时保留历史和未决行，清空弹窗保持打开并显示可恢复错误，待请求归属仍是当前文章/账号/语言时才允许回写。切换身份会中止 DELETE，迟到响应不会覆盖新身份历史。
- 聊天流中止或网络失败后只执行一次只读历史 GET，不自动 POST。仅当获取到的历史在请求前快照边界完全按序匹配，且紧随边界出现本次用户问题及其助手记录时，才将该回合视为已保存；仅确认用户问题时隐藏本地重复问题并阻止重发。其余情况保留输入草稿和未决回合，提供显式重查与带重复/费用风险提示的重发按钮。
- 清空请求失败时已中止的流也会进入同一只读核对流程。测试覆盖流式/空闲清空失败、延迟 DELETE 时发送与重复清空互斥、身份切换后的迟到 DELETE、成功/未成功保存、GET 失败、已有相同问题、单独保存用户问题和明确重发行为。

验收：聊天定向回归 3 个文件、28 项通过；完整 `npm run test:run -- --configLoader native` 为 41 个文件、255 项通过；`npm run lint`、`npm run typecheck`、`git diff --check` 均通过；`npm run build -- --configLoader native --outDir /tmp/newsagg-p2-chat-build-verified --emptyOutDir` 通过。验证只使用 mock API；本轮未运行连接 API 的浏览器 E2E，也未连接 Django、触碰项目数据库或调用 AI。此修补不声称服务端请求具备幂等能力；未决时自动重发仍被禁止。

## 2026-10-08 复审补充：普通聊天历史更新协调

起点：`262cce6214db56a9cfecbba9cab870aa7470d7df`。将中断回合的按序历史边界判定抽为同一协调函数，既处理中断后的只读 GET，也处理后续 TanStack Query 历史数据变化；只协调当前 `ownerKey` 的同一个未决回合。后续响应确认完整问答时移除临时 overlay；只有用户问题时维持原来的防重发状态，草稿被改写成另一条时予以保留。

验收：定向 `useChat` / phase 测试 2 个文件、22 项通过；完整套件 41 个文件、257 项通过；`npm run lint`、`npm run typecheck`、`git diff --check` 通过；`npm run build -- --configLoader native --outDir /tmp/newsagg-history-refetch-verified --emptyOutDir` 通过。新增两项回归覆盖首次核对未发现记录、首次仅发现用户问题后由普通历史 refetch 读到完整问答；两者均只调用一次聊天 POST、去除重复 overlay 并保留新的输入草稿。使用 mock API；未触碰后端、数据库或 AI 服务。

## 2026-10-08 复审补充：重复历史快照的显式重查

起点：`80e69a088c561b08120b11d47e8005d9c7aabea6`。历史对象相同只在当前未决回合已经结算为 `unconfirmed` 或 `partial` 时去重；显式重查处于 `checking` 时，即便 Query 结构共享返回同一对象，也重新结算。viewer 切换取消正在进行的核对后，将旧 viewer 的未决回合恢复为可重查状态；旧响应仍不能影响新 viewer。

验收：定向聊天测试 2 个文件、25 项通过；完整套件 41 个文件、260 项通过；lint、typecheck、diff check 和 production build 均通过。覆盖连续两次相同空历史、连续两次相同仅问题历史、历史 GET 失败、viewer 切换取消，以及此前普通 history refetch 两条回归。构建输出位于 `/tmp/newsagg-refcheck-final`；测试只使用 mock API。

## 2026-10-08 最终切片：API/SSE、应用壳、共享内容与语音播放器

起点：`3d677bd8f6cfd786b87f075757bf3a32dd23c67b`，分支 `codex/frontend-list-query-slice`。本切片只梳理前端现存基础层；未改 Django、数据库、业务数据或鉴权语义，也没有新增/升级依赖。

- `api.js`、`sse.js`、`tts.js` 与应用壳/共享内容组件迁为 TypeScript。API 适配器以 `unknown` 表示未经验证的 JSON 边界，保留既有 endpoint、参数、请求体、session cookie、CSRF、语言参数和长请求 timeout；Provider/Research 继续用 TanStack Query 的 `AbortSignal`。SSE 保留两种现存流格式；消费者提前结束时取消 reader，并增加取消回归。
- 将语音播放器控件从 App 壳提为 `GlobalSpeechPlayer.tsx`，拆分 state/actions/capabilities context；播放进度不再迫使详情页订阅者在每次 timeupdate 时重渲染。单个全局 Audio 实例支持切换文章、暂停/续播、键盘/触屏可操作的原生 range、倍速/音色/全文摘要选择；请求代次和当前 Audio 身份阻止旧事件覆盖新文章。位置及偏好仍使用原本的本地存储键。
- Header、登录弹窗、Error Boundary、Markdown 和 Mermaid 迁为 TSX，并继续沿用现有 shadcn/ui、Tailwind 主题与 lazy routes。增加 skip-to-main、导航菜单 Escape 与焦点返还，以及登录弹窗焦点循环、Escape 关闭与焦点返还。GSAP targets 改为引用真实节点。
- 删除没有生产调用点的旧 `SpeechPlayer.jsx` 和 `useSpeech.js`；播放器及其过去的行为由新 provider 和组件测试覆盖。`/__mascot__` 是已有独立设计预览路由，保留但明确不属于新闻阅读流程。

验收：`npm run typecheck`、`npm run lint`、`git diff --check` 通过；完整 `npm run test:run -- --configLoader native` 为 43 个测试文件、252 项通过；Vite production build 使用 `--configLoader runner --outDir /tmp/newsagg-p5-build --emptyOutDir` 通过。

本地浏览器在隔离 Vite (`127.0.0.1:5181`) + 合成 API mock (`127.0.0.1:9527`) 验收，只有虚构新闻、合成登录和静音 WAV：键盘登录焦点与 Tab 环绕/Escape 返焦、列表分类+搜索+语义模式、详情、收藏及收藏列表、全文抓取、翻译、聊天、仅本地研究、Provider 创建/重测、语音播放/暂停/续播、跨文章切换与播放器设置均已看到预期 UI。浏览器标签已标记为可交付，验收画面在会话中捕获；CUA 没有提供可写入本机文件的截图路径。没有连接项目数据库、真实 API/模型或发送凭据到外部服务。

从全新前端依赖开始，现有命令为：`cd frontend && npm ci && npm run typecheck && npm run lint && npm run test:run -- --configLoader native && npm run build`。开发模式 `npm run dev` 代理 `/api` 至 `127.0.0.1:9527`；按根目录 `README.md` 与 `docs/startup.md` 的既有说明单独启动 Django 即可。

本切片按本地提交保留，未推送；此记录随提交，便于主助手/用户直接复核。

## 2026-10-08 复审补修与本地真实服务

代码补修提交：`e72bef07c5152bb99ef2be960f86780bd1f614d7`，基于 P5 提交 `53116a3ce97be1a33f8cebc1fa16a063428bf4ca`，未推送。

- MediaSession `play` 的 Promise 拒绝处理再次核对当前 Audio 和请求代次；新增旧音轨拒绝发生在切到下一篇或停止后仍不覆盖当前状态的延迟 Promise 回归。
- Header 的 outside-pointer 检查同时排除菜单和菜单按钮；新增 pointerdown → pointerup → click 实序列开关回归。
- 有序列表只在每个列表项的所有锚点都能完整转换为 HTTP(S)/站内根路径来源卡片时才转换；任何列表项含片段锚点、相对地址、mailto 或其他不可完整表示的链接，整表保留标准 `<ol>` 和原 children，避免混合链接被丢弃。

测试数差额可复核：P5 前提交 `3d677bd8f6cfd786b87f075757bf3a32dd23c67b` 全量 41 文件/260 项；P5 提交全量 43 文件/252 项。P5 删除旧 `useSpeech.test.js` 13 项，并新增语音播放器 2 项、登录焦点 1 项、Mermaid 失败回退 1 项、SSE reader cancel 1 项，净少 8 项；无测试路径过滤。`useChat.test.js` 与 `useChat.phase.test.js` 相对 P5 前提交无差异，当前定向 25 项全通过；本补修后完整套件 45 文件/260 项全通过。

本修补验收：`npm run typecheck`、`npm run lint`、`git diff --check`、完整 Vitest 与 Vite production build 均通过。仍未迁为 TS 的 27 个生产模块是待办，而非迁移完成：`components/LoadingSpinner.jsx`；`components/chat/{ChatBubbleButton,ChatHeader,ClearChatDialog,Confetti}.jsx`；`components/mascot/{MascotPreview,XiaowenMascot}.jsx`；`components/news-detail/{ArticleSearchBar,ArticleToc,ErrorBanner,FetchArticleCard,FetchArticleSpinner,FullContentFetchStatus,ScrollToTop,TranslationStatus}.jsx`；`components/ui/{alert,badge,card,skeleton,toggle-group}.jsx`；`constants/index.js`；`hooks/{useArticleSearch,useArticleToc,useScrollPast}.js`；`lib/{shiki,utils}.js`；`main.jsx`。详情页、聊天叶组件、共享加载器/吉祥物和 shadcn primitive 仍有活动调用点；现有 `components.json` 仍配置 `tsx: false`。`MascotPreview` 是单独预览路由；`XiaowenMascot` 同时仍被聊天 UI 使用。后续逐组迁移并补齐 prop/DOM 边界类型。

本机验收服务只监听 loopback：Django `127.0.0.1:9527`，Vite `127.0.0.1:5173`；直连新闻 API 与 Vite `/api/news/` 代理均 HTTP 200。Django 以临时 `RUN_MAIN=true` 跳过 `ApiConfig.ready()` embedding preload，使用手动 `runserver --noreload` 与 Vite 命令；未运行迁移、crawler、scheduler/自动全文采集或 AI 请求，未登录或写入数据库。验收入口 `http://127.0.0.1:5173/`。当前 CUA 与 Codex 页面打开连接都返回 `Transport closed`，因此本轮未完成可视浏览器 QA，也没有保存/上传截图；HTTP 状态不代表最终 UI 验收。审查补丁另存于 Library：`news-aggregator-review-fixes-e72bef0.patch`。
