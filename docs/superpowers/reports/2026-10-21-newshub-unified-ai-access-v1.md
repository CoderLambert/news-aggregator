# 统一模型接入的实施进度与可复现证据

最新 UAT 修复见文末「已配置 Ollama 的研究准入与恢复」。此前全量结果属于原代码候选；当前修复使用单独来源绑定及定向、真实模型证据，不能把旧全量结果当作当前候选重新通过。

状态为 **IMPLEMENTED / LOCAL_VERIFIED**：六项实施任务完成，授权的指定 Ollama 真实链路通过。生产上线与用户手工验收另列，未执行。
工作区：`/home/lambert/githubRepos/lambert/news-aggregator-ai-v1`，分支 `feat/ai-unified-access-v1`。
基线：`a6cf437d45b66b962f35e4427ad8c05c589e990a`。设计与计划分别在相邻 `specs/`、`plans/` 目录。

## 已交付

- `f4f8f96`：管理员受信 manifest、纯配置校验、私网用户准入、内容版本路由、模型标签/命名空间、审核设计及计划。
- `3b2b11e`：T01 显式 `api_key/none`、0080 加法迁移、端点策略摘要与新连接 AAD 绑定、旧 AAD/幂等/队列兼容、撤销围栏和 T03 状态；研究/分类共用严格解码。无 Key 不存假 Key，也不需要安装加密 Key。
- `385bca8` / `bcafd00`：所有既有协议拒绝请求级 URL/Header/HTTP client/provider/retry/fallback 覆盖；新增管理员静态路由生成、原生 CustomLLM→成熟 raw adapter、Key/None 准入、DNS/IP pin、原始终态、单次发送、压缩拒绝、媒体预处理限制和错误脱敏。默认 manifest 仍为空。
- `7312a90`：能力收据绑定 route/protocol/adapter/auth，业务 SDK 注入受信 owner/mode；兼容模型问答/分段翻译及工具消费者贯通。已有原生 Responses/Messages 提供明确 buffered 输出，其他旧 Chat 的业务准入保持原限制。0081 增加脱敏 usage 元数据，并将 alias 容量扩至 256，保留最大 profile+model 的 245 字符身份。
- `f93831c`：界面支持批准的 Key/None，切换清空 Key、只读诊断和显式模型目录；保留手填与用户选择，不从 unknown 取得用途权限。问答/翻译入口接受有证明的无 Key 模型，并明确 buffered 输出、未知费用和服务器可能使用云服务。

独立复查发现并解决：创建中途 manifest 改变会重绑 Key 的竞争；兼容端点误删 `openai/` 等模型前缀。已先复现失败，再修复；复审未发现 Task 1/2 重要问题。该复查使用主会话的测试证据，没有冒称独立重复运行。

## 实际验证

| 范围 | 结果 | 限制 |
| --- | --- | --- |
| Task 1 新负控与 T01/T02/Worker | 120 passed、5 subtests | Python 3.12.14，隔离合成 DB |
| Task 2 最终受影响集（profiles/auth/T01/T02/T03/manual routes/research/classification） | 178 passed、25 subtests | `3b2b11e` 对应代码；非整仓全量 |
| 较早的扩大集，另含 T04/T05 | 256 passed、48 subtests | 在最后 TOCTOU/命名空间修复前，不能替代最终受影响集 |
| 迁移状态 `manage.py makemigrations api --check --dry-run` | PASS，No changes detected | frontend 尚未构建，只有 staticfiles.W004 |
| Proxy guard/config/runner tests | 37 passed | 直接 callback/配置单测 |
| T00 harness 自身负控 unittest | 37 passed | 预期的未知参数 CLI 错误属于负控输出 |
| 原有真实 SDK→固定 Proxy→合成上游 | 241 PASS / 0 FAIL | 未增加请求覆盖负控时的基线 |
| 扩展真实 SDK/Proxy 矩阵，含 18 个 raw HTTP 覆盖请求及 18 个独立零调用收据 | **277 PASS / 0 FAIL** | 新泛化流式/私网 egress 尚不在矩阵中 |
| Django→SDK→实际 Proxy→合成上游（问答、翻译、研究、取消与坏终态） | **3 passed** | production settings + 全新 WAL DB；这是合成业务链，不是部署 |
| 临时 direct LiteLLM raw handler 探针 | 2 次合成请求 PASS | 无 Proxy，不能替代最终链路；有 Key/None 分别实际带/不带 Authorization |
| Task 3 最终 Proxy unittest | **61 passed** | `bcafd00`；含新真实 HTTP/TLS/取消/deadline 负控；不是 Docker 镜像验收 |
| Task 3 旧 SDK/Proxy 矩阵重跑 | **277 PASS / 0 FAIL** | 原有静态协议，新增传输不改变旧 parser |
| Task 3 新受信 SDK→Proxy→合成 compatible | **30 PASS / 0 FAIL** | Key/None、命名空间、并发、坏终态/拒绝/压缩、媒体零请求、原子撤销、取消生产者、一次 tools；报告绑定 runtime blob |
| Task 3 profiles/T02/manual routes | **52 passed、23 subtests** | 共享模型校验模块的受影响集 |
| Task 3 CI / harness / config-runner | **50 / 37 / 5 passed** | CI 路由门禁未改变；不是远端 CI |
| Task 3 Django legacy 业务链重跑 | **3 passed，29.33s** | 全新 production-isolated WAL DB，旧问答/翻译/研究/取消；新路由业务待 Task 4 |
| Task 4 最终受影响后端集 | **199 passed、48 subtests，112.46s** | T01/T02/T03/T04/T05、研究/分类/建议/usage/新统一消费者；不是整仓全量 |
| Task 4 Django→SDK→实际 Proxy 业务链 | **5 passed，59.07s** | legacy3 + compatible Key/None2；真实探针、问答、分段翻译、工具、EOF 不落完成、owner usage 隔离 |
| Task 4 受信 Proxy 矩阵 | **31 PASS / 0 FAIL** | 新增严格 JSON object 模式；[原始报告](evidence/2026-10-21-ai-business-proxy.json) 绑定 `7312a90` runtime blob |
| Task 4 CI / Proxy direct / OpenRouter / migration | **50 / 27 / 1 / PASS** | OpenRouter 实际 HTTP 断言关闭上游 fallback；migration dry-run 无缺失；非远端 CI |
| Task 5 前端定向 | **63 passed，7 files** | Node 22.23.3；认证/目录失败/不自动选模型/跨 viewer/问答翻译/usage |
| Task 5 typecheck / build / lint | **PASS / PASS / 0 errors** | lint 仅既有 `useSuggestedQuestions.ts` warning；锁文件及共享依赖未改变 |
| Task 5 后端 / CSRF / Proxy direct | **84 passed、5 subtests / 1 / 64** | owner、会话 CSRF、viewer、撤销、只读不发请求 |
| Task 5 SDK→实际 Proxy→兼容目录 | **38 PASS / 0 FAIL** | Key/None；错误项目 key、缺 model 授权、owner 越权、伪造 none、URL 均零上游；[原始报告](evidence/2026-10-21-ai-discovery-proxy.json) |
| Task 5 production-isolated Django 目录与业务 | **2 passed，35.98s** | Key/None 实际目录、探针、问答、分段翻译、工具与 EOF 围栏；目录无能力收据 |
| Task 5 Chrome 浏览器 | **功能与 DOM 布局 PASS** | 合成 DB/账号/Proxy；宽屏及实际 CSS 413px，文档宽 394px；Enter/Esc/清空 Key/保存/目录/诊断/退出；[检查记录](evidence/2026-10-21-ai-browser-checks.json) |
| 指定 Ollama 真实服务 | **9/9 PASS** | 仅指定模型；见最终证据，不外推其他真实服务 |
| 其他真实供应商、用户 UAT、远端 CI、生产 | NOT_RUN | 本地结果不代表上线验收 |

原始脱敏 Proxy 报告保存在 `evidence/2026-10-21-ai-proxy-admission.json`；包含每条断言、版本、请求次数和清理结果。实际版本：Python 3.12.14、LiteLLM 1.105.0、OpenAI SDK 3.28.0、Anthropic 1.13.0、httpx2 2.13.1、临时 pgserver 0.1.4/Prisma 0.15.0。

新增报告为 [30 项原始脱敏证据](evidence/2026-10-21-ai-trusted-proxy.json)，候选 `bcafd00`、runtime blob、命令和退出 0 均在文件内。连接层使用固定 httpx 0.28.1/httpcore 1.0.9。真实 TLS fixture 验证：缺 CA 拒绝、信任临时 CA 且正确 SNI 通过、错误 hostname 拒绝；未关闭证书验证。实际流取消和加速 deadline 均关闭生产者、没有终态、没有第二次发送。

主会话临时日志：`/tmp/newshub-ai-v1-task2-final.log`、`/tmp/newshub-ai-v1-task2-regression.log`、`/tmp/newshub-ai-v1-business.log`。它们只含合成测试结果；不能依赖临时文件永久存在。

## 已分类的失败

- 第一次隔离 venv 的 T01/Worker 运行缺 `chromadb`，导致 URL 模块导入失败；补装 CI lock 约束下的私有依赖后通过。未修改共享 venv。
- 一次 Proxy pytest 命令遗漏 PYTHONPATH，在收集前失败；按仓库约定补齐后 37 项通过。
- 扩展 HTTP 负控初次结果 `268 PASS / 9 FAIL`：全部上游收据均为零，但 URL/NESTED 由 LiteLLM 的 virtual-key 准入提前返回 401，fallback 指向未经项目授权的模型提前返回 403，原用例错误地要求统一 400。修正为 URL/NESTED 接受明确的 400/401 拒绝，并将 fallback 目标改为本项目已授权模型、仍严格要求 guard 返回 400；最终 277/0。没有放宽“上游必须零调用”的断言。
- Task 3 审查发现媒体 URL 被成熟 adapter 提前下载、HTTPx 压缩放大越过预算、malformed body 反射原文、refusal 被归一化丢失；分别观察 RED 后修复。新路由限定文本/function 数据、raw identity 正文、静态错误、原始 refusal 拒绝。独立复查只读，进程结果明确标为复用。
- 单文件 bind mount 可能固守旧 inode；已改挂专用配置目录，进程探针使用 `os.replace` 撤销。此证据不冒充实际 Docker mount 验收。管理员重新启用必须提升 version；禁止通过恢复旧文件复活旧身份。
- 新增 GET 记录后，Django 业务探针最初 2 项失败：启动已有 legacy unknown OpenAI fixture 路由时，LiteLLM 用实验室专用 sentinel 做两次目录检查。改为明确记录并验证这个启动基线，再严格要求设置保存新增零请求；未忽略未知认证或新路由启动请求。修正后 2 项通过。
- 浏览器发现目录后，原生 select 会视觉选中首项而 React 状态仍为空；回归先失败，再增加空选择占位，保持用户明确选择。默认视口截图成功并展示；模拟视口下 CDP 截图超时，窄屏只确认实际 DOM 布局与功能，未冒称窄屏截图验收。视口已恢复，临时账号退出，验收标签与独立进程已清理。

## 实施完成与交付边界

Task 1–6 均完成。通用分段使用产品预算，context/output 的供应商最大值仍为未知，失败不重试、不切换。旧 DeepSeek clean EOF 与新 Chat stop+DONE 合同独立。保留本地分支与 worktree；未推送、建 PR、合并、迁移真实 DB 或部署。管理员发布实际端点与模型、项目目录权限和全量远端 CI 属于后续交付边界。

逐任务过程已归档到本报告和原始证据；计划临时目录在验收后清理。授权 Ollama 复现脚本在原始证据压缩包内，读取关闭回显的 stdin，仅允许指定主机及临时解析的公网 IP；普通合成测试仍严格只允许 loopback。

## 重现关键门禁

所有命令从隔离 worktree 根执行。`.venv-ai` 是此任务独立 Python 3.12.14 环境；`.venv-sdk/.venv-proxy` 使用 `tools/byok_t00_probe` 两个原有 lock，Proxy 已运行 `prepare_proxy.py`，无需修改宿主 Python/Node。

```sh
env -i PATH=/usr/bin:/bin PYTHONPATH=backend:crawler RUN_MAIN=true \
  .venv-ai/bin/python -m pytest -q \
  backend/api/tests/test_ai_endpoint_profiles.py \
  backend/api/tests/test_ai_connections_auth_modes.py \
  backend/api/tests/test_ai_connections.py backend/api/tests/test_ai_worker_fencing.py \
  backend/api/tests/test_ai_task_preferences.py backend/api/tests/test_ai_models_t02.py \
  backend/api/tests/test_ai_manual_model_routes.py backend/api/tests/test_research_byok.py \
  backend/api/tests/test_classification_evidence.py

env -i PATH=/usr/bin:/bin LANG=C.UTF-8 .venv-sdk/bin/python \
  tools/byok_t00_probe/probe.py --proxy-python .venv-proxy/bin/python \
  --report /tmp/newshub-ai-v1-proxy-admission-final.json
```

Django 业务链严格沿 `.github/workflows/ci.yml` 的 T00 production-isolated 命令运行：全新 TMPDIR/HOME、WAL DB、CHROMA/TTS 目录、仅合成 secrets、`T00_PROXY_PYTHON` 指向私有 Proxy venv，再执行 `pytest -c backend/pytest.ini -o 'python_files=t04_*.py' -q tools/byok_t00_probe/t04_django_localproxy.py`。勿直接用生产目录或用户 DB。

交付边界：尚无 PR/远端 CI；未推送、未合并、未部署，原工作区数据库与现有预览未操作。回滚代码不能替代 schema 回滚；0080 的加法列保留，停用新增端点即可撤销其后续执行。


## Task 6 最终证据

运行代码候选 **`b98f153e2a4970c77fa2d49a9d5be4d653c451df`**，基线 `a6cf437d45b66b962f35e4427ad8c05c589e990a`。随后只提交证据与文档。可从仓库根运行 `python3 docs/superpowers/reports/evidence/2026-10-21-validate-ai-final.py` 检查来源、25项要求及证据完整性。完整命令、退出码、候选及来源绑定见 [最终门禁](evidence/2026-10-21-ai-final-gates.json)，原始日志/动态覆盖审计/JUnit/安全复现脚本见 [原始归档](evidence/2026-10-21-ai-final-raw.tar.gz)。

| 最终门禁 | 结果 | 说明 |
| --- | --- | --- |
| 三根后端 hybrid | **2243 passed / 16 skipped / 0 failed** | serial52 + 两 worker loadfile2191；2259 collected/executed 身份一致；未放宽 skip 审计 |
| 全量前端 | **739 passed / 105 files** | Node22；typecheck/build PASS；lint0 errors、1个既有 warning；最终候选的前端 tree/lock 未变化，复用有效 |
| Proxy direct / harness+config | **65 / 40 passed** | 含取消、TLS、压缩、原始终态、assistant-only 文本 reasoning 续接 |
| 既有协议真实 Proxy 矩阵 | **295/295 PASS** | [结果](evidence/2026-10-21-ai-proxy-final.json)；新增 retry policy/global/max 的三协议零请求负控 |
| 新受信真实 Proxy 矩阵 | **38/38 PASS** | [结果](evidence/2026-10-21-ai-trusted-proxy-final.json)；Key/None、目录、终态、撤销、无隐式发送 |
| production-isolated Django 业务 | **5 passed，67.68s** | 旧3 + Key/None2；同文显式切换两个模型问答、翻译 retry，旧译文不变；真实 Proxy、合成上游 |
| CI 结构 / migration dry-run / diff | **50 / PASS / PASS** | 不是 GitHub CI；No changes detected；未迁移用户数据库 |
| 指定 Ollama | **9/9 PASS** | [脱敏结果](evidence/2026-10-21-ai-ollama-live.json)；真实文本/tools 探针、同模型工具结果回放、流式问答/翻译及落库；临时资源全部清理 |
| 秘钥检查 | **0 matches** | 用户提供的测试 Key 未出现在 tracked/deliverable untracked 文件；不保存实际 Key 或用户文章 |

完整后端收集开始于 `f47f9a6`；之后的 `b98f153` 只修正测试根以外的 T04 断言，所有被收集的源码与测试字节相同。T04 最终业务、指定真实 Ollama 及新受信 Proxy 矩阵在 `b98f153` 完成。旧协议矩阵执行后只增加新路由的 assistant 文本续接字段，既有协议/guard 未变，来源绑定在证据中明确记录。

Ollama 官方区分 CLI `minimax-m3.1-flash:cloud` 与云 API 模型名。目录实测返回 `minimax-m3.1-flash`，验收明确使用该官方映射，没有字符串猜测或转用其他模型。[官方云说明](https://docs.ollama.com/cloud)、[OpenAI 兼容接口](https://docs.ollama.com/api/openai-compatibility)。

真实首轮并未通过：8-token 文本探针原始 `finish_reason=length`、空正文；32-token 工具预算也不足，业务因此保持不可用。保留 [首轮结果](evidence/2026-10-21-ai-ollama-initial.json)。新 manifest 探针单次上限改为512，旧协议预算不变；未将截断冒充成功，也未自动重发。工具回放首轮被有效 tool_calls 附带的说明文字/测试脚本的通用 model_dump 额外字段阻断，保留 [首轮回放](evidence/2026-10-21-ai-ollama-replay-initial.json)；修复校验与同模型文本续接，并使用业务原有 serializer 后，最终全部通过。工具前缀只保存在服务端续接，不作为报告或公开消息。

独立全分支审查发现1项 Important：请求 `model_group_retry_policy` 可让实际 Proxy 将500失败发送3次（普通对照1次）。`f47f9a6` 拒绝该字段及其他 retry override；准入负控先出现12个失败，再通过；最终真实 Proxy 三协议相关请求均在上游前拒绝。Critical0 / 未解决 Important0 / Deferred minors0。审查者未判断的真实 Task6与生产效果在本轮分别验收或明确 NOT_RUN，没有伪称复审覆盖新增代码。

其他已分类失败：完整后端首轮2185 passed、3 failed、16 skipped；两项测试仍断言原生协议不可用于文章，与已批准 buffered 行为冲突，现断言 buffered、非流式且能力仍未知；第三项是隔离环境未设置 HOME，改为全新 private HOME。最终动态全量门禁通过。新增跨模型翻译用例曾引用不存在的 task.model_id，改为读取不可变 execution_snapshot；业务断言未放松，最后5项通过。一次 harness 命令漏 PYTHONPATH，在收集前失败；修正路径后40项通过。

## F / S / R 要求对应

下表 PASS 指本地实现及所列证据；真实供应商的独立运行状态仍受最后一列限制。通用 adapter 的合成证明不代表每种服务版本、实际网络或生产配置通过。

| ID | 实现与回归 | 最终证据及边界 |
| --- | --- | --- |
| F01 | 原有 DeepSeek guard、T04/T05/T09 | 旧矩阵295、业务5、后端全量 PASS；真实 DeepSeek NOT_RUN |
| F02 | ai_model_registry / ai_gateway；native Responses/Messages buffered；管理员 qwen compatible profile | 原生协议/手工路由/用途回归、全量 PASS；真实 OpenAI/百炼 NOT_RUN |
| F03 | ai_endpoint_profiles / opaque model ID；OpenRouter 无 provider fallback | namespaces及实际 HTTP断言 PASS；真实 OpenRouter/硅基 NOT_RUN |
| F04 | auth_mode、无假 Key、同一 transport与UI | Key/None实际业务两组 PASS；指定 Ollama真实9项 PASS；LM Studio真实 NOT_RUN |
| F05 | vllm 服务预设及受信 Chat profile | 共用已验证 compatible transport；真实 vLLM NOT_RUN |
| F06 | t04_unified_localproxy 同文两模型问答及显式翻译 retry | 业务5 PASS，model_source/快照逐一匹配，旧结果保持 |
| F07 | ai_model_capabilities / research.byok_execution / assistant continuation | 未证tools不启用研究；合成全量及指定模型真实工具回放 PASS；不代表整份真实研究质量验收 |
| F08 | manual model API、AIModelsManager | 手填、目录失败保留手填、完整命名空间；frontend739/后端全量 PASS |
| F09 | 保存与GET无推理、显式目录/probe | 实际 Proxy启动基线与保存0新增请求、浏览器显式选择 PASS |
| S01 | PinnedBackend / OneShotClient | 固定 DNS→数值 connect、IP/port/TLS、禁代理/redirect、恶意网络负控 PASS |
| S02 | 纯 manifest / 静态 config 生成 / 目录挂载 | 配置/atomic replace负控 PASS；生产 mount及重启 NOT_RUN |
| S03 | ProviderKeyGuard 共享 override admission | 295矩阵含 URL/header/provider/client/retry/fallback 零上游；review重复发送缺口修复 |
| S04 | connection/model/views/worker owner、CSRF与viewer | 后端全量、真实Proxy目录负控、浏览器退出 PASS |
| S05 | 内容摘要 alias、immutable connection digest、epoch/version | 同版变更、撤销、晚结果、原子替换 PASS；管理员恢复旧身份违反发布合同 |
| S06 | 0080/0081、原v2 AAD、新v3绑定、严格旧snapshot解码 | 兼容/幂等/迁移用例、dry-run PASS；真实DB迁移 NOT_RUN |
| S07 | none准入、严格模式、Key replacement拒绝 | API/DB/实际Proxy Key/None/伪造模式负控 PASS |
| S08 | 服务端凭据、safe DTO、无URL/Key日志、无浏览器缓存 | 脱敏异常、UI清空、secret scan0；证据不含实际Key |
| R01 | raw/normalized completion、stop+DONE+clean body | direct65、可信矩阵38、真实Ollama问答翻译 PASS |
| R02 | 缺stop/DONE、截断、异常EOF | 负控不释放terminal，不保存completed；保留旧DeepSeek cleanEOF合同 |
| R03 | raw error/refusal/重复terminal | Proxy负控、probe unknown、研究拒绝 PASS |
| R04 | 总deadline、正文预算、identity-only、分段产品预算 | direct及业务/全量 PASS；未知模型context不伪造已知值 |
| R05 | 取消关闭producer/连接，viewer abort | 实际取消生产者、Django取消、前端/浏览器 PASS；在途计费只能best effort |
| R06 | owner/content/revision/epoch/lease/generation commit fence | 统一消费者晚提交负控、T04/T05/T09全量 PASS |
| R07 | 单次dispatch，SDK/Router/client零retry，不换模型 | 重试policy实际3次复现→准入零请求；跨模型仅显式retry；不自动重发unknown |
| R08 | usage owner、route metadata、未知费用/token | AICallAttempt及UI回归 PASS；失败/取消不宣称未计费 |

## 发布与人工验收

生产 manifest 默认空。部署者需按 Proxy README 发布经审核的真实地址/IP/owner准入、同步两端配置、按需授予独立目录 route，再跑最终 SHA 的完整远端 CI/image/G1；此任务没有执行这些操作。停用新增 profile 可阻止后续派发，重新启用提升 version；代码回退保留0080/0081加法列，不能代替数据库回滚。

人工验收只需记录版本及 PASS/FAIL/未测：连接与模型配置、同文切换问答/翻译、取消/退出后无晚结果。现有浏览器是合成验收，不能替代用户部署环境 UAT。

## 实施中裁定及代价

以下完整保留本次执行 ledger 中的 Ruling，按作出顺序排列。早期测试复用和阶段说明是历史证据，最终状态以前文最终门禁为准。

- Ruling: native Python 3.15/Node 24 do not match CI; created private .venv-ai Python 3.12.14 with minimal required packages constrained to CI lock; Node 22 is available via mise. Shared dependencies unchanged.
- Ruling: original DeepSeek permits raw stop + clean EOF. Preserve existing terminal policy and require raw stop+DONE for new chat policy; no blanket whitelist expansion.
- Ruling: profile content hash excludes labels and enabled flag, includes adapter/auth/egress/user ACL; disabling still rejects current route. Per-profile aliases avoid unrelated evidence invalidation.
- Ruling: stored endpoint_policy_digest is immutable and used in v3 AAD only for new manifest connections. Same-version target edits cannot inherit old Key even via a fresh enqueue; old v2 AAD remains unchanged.
- Ruling: shared decode_connection_snapshot accepts exactly full new or full original legacy connection fields. Research and channel must use it so old queued Key jobs remain decodable; partial/transitional snapshots rejected.
- Ruling: respect repository's no redundant test policy by reusing expanded T04/T05 results while their runtime paths remain unchanged; final review changes checked in178-test affected suite. Do not claim whole-repo or production PASS.
- Task 3 override process RED268PASS/9FAIL: all18upstream receipts0 but URL/NESTED early virtualkey401 and unauthorizedfallback403 differed from expected400. Ruling: accept URL/NESTED explicit400/401 plus0receipts; changefallbacktarget to authorizedt00-chat so guardmustreject400. Finalmatrix277PASS/0FAIL; evidence persisted docs/superpowers/reports/evidence/2026-10-21-ai-proxy-admission.json with runtimeblob IDs.
- Task 3: Ruling: use native CustomLLM extension to call pinned BaseLLMHTTPHandler + OpenAIUnknownModelConfig, not a global experimental switch or patched SDK transport; new routes alone receive one-shot raw proof. Cost if wrong: pinned native-extension upgrades must fail closed and be reverified.
- Task 3: Ruling: pre-adapter accepts only text and function definitions/history, with a strict optional-parameter allowlist. Media and built-in tools are outside this text/tools release; their preprocessing can create unapproved network requests. Cost if wrong: unsupported media stays explicitly rejected until a separately approved capability.
- Task 3: Ruling: mount administrator config directory rather than a single manifest file, so atomic replacements can be observed. Reactivation requires higher profile version; administrator rollback to an old identity is forbidden by publishing contract. Cost if wrong: operator violating version discipline can revive old receipts; no claim of adversarial-admin protection.
- Task 4: Ruling: only manifest raw Chat + existing Flash stream; existing native Responses/Messages may deliver explicitly buffered validated one-shot text. Other old Chat aliases retain prior article/translation denial and need a manifest for new business support; do not expand the old parser whitelist. Cost if wrong: administrator must publish those compatible profiles before use.
- Task 4: Ruling: new route capability receipts bind alias/protocol/adapter/auth/policy digest, while complete old legacy receipts remain decodable/current for unchanged legacy contracts. Owner/model/epoch audit rows still required. Cost if wrong: legacy evidence retains its existing terminal assurance and is not advertised as the new raw contract.
- Task 4: Ruling: generic segmented translation reuses bounded Markdown product budgets without claiming a known provider context/output maximum (both None). DeepSeek T06 plan identity and guards remain unchanged. Native text output budget is capped at8000 for its existing adapter contract. Cost if wrong: an unknown model can reject input/output budgets, leading to explicit failure without fallback/retry.
- Task 5: Ruling: model discovery is a separate catalog-only operation inside the existing pinned Proxy via LiteLLM native LITELLM_WORKER_STARTUP_HOOKS. It reuses user_api_key_auth + can_key_call_model and the admitted one-shot pinned client, GET /v1/models only,15s/64KiB/100IDs, no inference/probe receipts. Project key must explicitly add /newshub/models/discover to allowed_routes (alongside llm_api_routes); ungranted keys failclosed. Cost if wrong: operators must grant new catalog route; old connection catalog/manualentry remains available.
- Task 5 actualDjangocatalog first2FAIL because new GETinstrumentation exposed twoexistingLiteLLM startupcatalogreads for lab's legacy unknownOpenAIroutes with syntheticdeploymentsentinel, before anysettingswrite. Ruling: explicitlyclassifyknownsentinelbootstraprecords and assert settings adds0calls; neverignoreunknownauth/newroute startupcalls. Providerlabels updatedonlyfixture. Correctedprocess2tests running; log/tmp/newshub-ai-v1-task5-business-process-final.log, session above. No realcredentials/providers.
- Task 5: Ruling: always show empty discovery-selection placeholder, so native select cannot visually pick first discoveredID while React still has no selection. Cost if wrong: one extra explicit model selection, no implicit inference. Unknownmetadata coercesonly to unknown/false; completelegacyT02 remains usable. Browserfoundselectionbug RED1->GREEN, unknownmetadatapermission RED1->GREEN16focused.
- Task 6: Ruling: new compatible probes use one capped512-token generation, legacy caps unchanged. Real Ollama text8 exhausted at length and tools32 clipped; official CLI :cloud maps to catalog API minimax-m3.1-flash. Cost if wrong: explicit probes may spend more tokens or return unknown, never auto retry/fallback.
- Task 6: Ruling: valid tool_calls may contain a text preface, retained only in server continuation and omitted from visible messages; assistant-only bounded reasoning_content can replay to the exact fenced model. RED preface/replay cases then GREEN. Cost if wrong: provider-specific history remains subject to the same fail-closed body/terminal/owner checks.
- Task 6: Ruling: full suite found two old native-protocol tests asserting article chat unavailable; approved Task4 explicitly adds buffered delivery. Update to assert buffered=true, stream_verified=false, capabilities remain unknown. Third failure was missing HOME in env-i; use fresh private HOME rather than read user config. Cost if wrong: production readiness still requires full canonical CI.
- Final: Ruling: reviewer declined live Task6 and production deployment judgment. Complete authorized real Ollama evidence here; production/image/remote CI remain NOT_RUN and require separate delivery authorization. Cost if wrong: no production claim can be derived from local evidence.

## 已配置 Ollama 的研究准入与恢复

用户本地 UAT 的当前连接仅完成文本验证，工具能力未知。默认用途因此可用，但旧研究面板直接继承了该默认模型；服务端实际在任务创建之前拒绝。客户端丢失结构化 HTTP 错误后，又把明确拒绝误认为可能已发送，持续显示“继续接收”。

修复基于 `04bf2cd0510e9cbed452485a2c4215d37cdee876`，范围为 11 个代码/测试文件：用途 DTO 输出当前 `research_eligible`；研究入口严格要求其为 `true`，缺少能力或失效时显示检查提示。服务端仅在 owner 锁与幂等二次查询后、创建 session/run 前的模型准入失败返回 `request_state=rejected`。客户端仅对当前新建请求、结构化 409、明确标记和允许的错误码清除对应 pending；网络断开、未知冲突、已有任务和续问继续保留原幂等键。

本轮 [脱敏证据与来源摘要](evidence/2026-10-21-ai-uat-fix.json) 绑定每个修改文件的 SHA256；[原始日志及验收脚本](evidence/2026-10-21-ai-uat-fix-raw.tar.gz) 保留失败与通过结果。此前最终全量验证器只适用于其原代码候选，没有修改它来接受新的源码。

| 范围 | 结果 | 边界 |
| --- | --- | --- |
| 缺陷先行复现 | 后端 2 fail / 1 pass；前端 4 fail | 缺少资格字段、错误码、UI 准入及拒绝恢复均有 RED |
| 后端受影响集 | 53 passed、2 subtests | unified consumers、用途偏好、BYOK research、CSRF；合成 DB |
| 前端受影响集 | 71 passed / 5 files | research hook/panel、streams API、SSE、AI API；含未标记 409、非允许码、500 均保留恢复 |
| typecheck / lint / build | PASS / 0 errors / PASS | lint 1 个既有 useSuggestedQuestions warning |
| 用户现有 `minimax-m3.1-flash` | 工具探针、文章问答、简短研究及落库 PASS | 本轮新增 3 次实际模型请求；文本证明沿用用户已有有效收据 |
| 浏览器 | 配置页文本/工具均显示已验证；研究面板显示同模型完整问候 | 未提交用户原来的复杂研究问题 |
| 独立聚焦审查 | Critical 0、Important 0 | 只读审查 11 文件；复用主会话日志，无冒称独立重跑 |
| 整仓全量、复杂工具/联网报告质量、生产 | NOT_RUN | 旧候选全量结果不替代本轮；远端当前头检查以 PR 实际结果为准 |

真实问答首轮验收脚本误按 research 的 `data:` 格式解析，记录 FAIL；问答接口实际使用 `__META__`，随后通过当前 owner 的 HTTP 历史及 terminal DB receipt 确认该次问答已完成，没有重放模型请求。原始 FAIL 与更正依据都保留。研究已收到 complete 事件且 DB 为 succeeded。

本地预览原端口和任务所属 DB 保留。第一次重载把已退出的 zombie 子进程误判为仍运行，导致暂时停服；随后保持原父进程、Proxy、加密材料和 DB，在原端口恢复后端。没有读取或打印用户 Key。原来的待恢复请求没有自动重放，也没有自动切换模型。此修复无迁移；回滚代码会恢复原 UI 缺陷，已取得的有效能力收据可保留。
