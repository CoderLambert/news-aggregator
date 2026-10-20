# 统一模型接入的实施进度与可复现证据

目标保持完整；状态为 **IN_PROGRESS**，不是全功能完成或上线验收。
工作区：`/home/lambert/githubRepos/lambert/news-aggregator-ai-v1`，分支 `feat/ai-unified-access-v1`。
基线：`a6cf437d45b66b962f35e4427ad8c05c589e990a`。设计与计划分别在相邻 `specs/`、`plans/` 目录。

## 已交付

- `f4f8f96`：管理员受信 manifest、纯配置校验、私网用户准入、内容版本路由、模型标签/命名空间、审核设计及计划。
- `3b2b11e`：T01 显式 `api_key/none`、0080 加法迁移、端点策略摘要与新连接 AAD 绑定、旧 AAD/幂等/队列兼容、撤销围栏和 T03 状态；研究/分类共用严格解码。无 Key 不存假 Key，也不需要安装加密 Key。
- 当前 Task 3 增量：所有既有协议拒绝请求级 URL/Header/HTTP client/provider/retry/fallback 覆盖；真实进程新增原始 JSON 负控并核对上游零调用。

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
| 真实供应商（含指定 Ollama）、浏览器 UAT、全量 CI、生产 | NOT_RUN | 不得据上述结果宣布全功能完成 |

原始脱敏 Proxy 报告保存在 `evidence/2026-10-21-ai-proxy-admission.json`；包含每条断言、版本、请求次数和清理结果。实际版本：Python 3.12.14、LiteLLM 1.105.0、OpenAI SDK 3.28.0、Anthropic 1.13.0、httpx2 2.13.1、临时 pgserver 0.1.4/Prisma 0.15.0。

主会话临时日志：`/tmp/newshub-ai-v1-task2-final.log`、`/tmp/newshub-ai-v1-task2-regression.log`、`/tmp/newshub-ai-v1-business.log`。它们只含合成测试结果；不能依赖临时文件永久存在。

## 已分类的失败

- 第一次隔离 venv 的 T01/Worker 运行缺 `chromadb`，导致 URL 模块导入失败；补装 CI lock 约束下的私有依赖后通过。未修改共享 venv。
- 一次 Proxy pytest 命令遗漏 PYTHONPATH，在收集前失败；按仓库约定补齐后 37 项通过。
- 扩展 HTTP 负控初次结果 `268 PASS / 9 FAIL`：全部上游收据均为零，但 URL/NESTED 由 LiteLLM 的 virtual-key 准入提前返回 401，fallback 指向未经项目授权的模型提前返回 403，原用例错误地要求统一 400。修正为 URL/NESTED 接受明确的 400/401 拒绝，并将 fallback 目标改为本项目已授权模型、仍严格要求 guard 返回 400；最终 277/0。没有放宽“上游必须零调用”的断言。

## 下一实施边界

Task 3 尚未完成。新端点目前不能靠配置直接获得业务流式权限，必须继续实现并证明：

1. 管理员 manifest 生成/激活 Proxy 路由，两端同一内容版本；无 Key admission 只准批准 profile，用户不能升级到其他模型服务。
2. 实际 HTTP client 的 DNS/IP pin、TLS 原主机校验、禁重定向/环境代理、每次 dispatch 严格单次发送。LiteLLM `AsyncHTTPHandler.post` 有独立 reconnect retry，不能仅设 `num_retries=0` 就宣称无自动重试。
3. 固定版本支持 `EXPERIMENTAL_OPENAI_BASE_LLM_HTTP_HANDLER`，临时探针已证明其输出为 `CustomStreamWrapper` + `OpenAIChatCompletionStreamingHandler`，model `org/model:cloud` 未丢失，None 不发送 Authorization。应复用成熟 raw 路径并限定到新受信路由；不要未经回归全局改变旧协议。
4. 普通 OpenAI SDK 路径记录的是 `model_dump` 后的响应，重复 JSON key 已不可追溯；新完成证据必须来自真正 raw body/SSE。新 Chat 策略要求 stop+DONE，旧 DeepSeek clean EOF 策略保持独立。
5. 完成 Task 4 真实消费者与能力/协议绑定，Task 5 UI/发现/诊断，Task 6 指定 Ollama 及最终 F01–F09/S01–S08/R01–R08 验收。深研/tools、usage、分类按完整合同逐项验证。

执行状态与下一任务见 Git ignored `.superpowers/sdd/2026-10-21-newshub-unified-ai-access-v1/progress.md`；临时 raw handler 脚本在 `/tmp/newshub-ai-v1-raw-handler-probe.py`，属于可删除调查脚本，未作为生产实现交付。

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
