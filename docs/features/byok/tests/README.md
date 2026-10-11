# BYOK Test 契约与执行状态

每张 [Task 卡](../tasks/README.md) 对应同编号 Test；T00-G 为独立网关运维 Test。各卡的 READY FOR REVIEW、PARTIAL、NOT_RUN 和失败项以同编号 Test 文档中的实测证据为准；当前 T02、T03、T04 已有实现和执行记录，不能再用本页的一段总述覆盖单卡状态。

## 证据级别

| 级别 | 可以证明什么 | 不可以冒充什么 |
| --- | --- | --- |
| UNIT | 业务逻辑、权限和数据不变量 | SDK、Proxy 或厂商真实可用 |
| SDK_LOCAL | 真实官方客户端 SDK 经过受控合成 HTTP upstream 发送/解析请求 | LiteLLM Proxy 集成或任何真实厂商兼容 |
| PROXY_LOCAL | 固定真实 LiteLLM Proxy + 真实客户端 SDK + 受控 upstream 端到端集成 | 真实 provider/model/region 可用 |
| INTEGRATION | Django+Session+CSRF+DB/worker/SSE/React 的业务操作 | 网关部署或某个 provider 真实兼容 |
| PROVIDER_REAL | 指定 provider、model、region、日期使用有界真实请求 | 其它模型、地区、产品套餐、参数或未来版本兼容 |
| UAT | 用户在最终运行环境执行的真实操作 | 自动化或本地测试可代替用户验收 |

本计划当前指定的真实 provider 首轮只有 DeepSeek。其余厂商保持 NOT_RUN；本地 Proxy 测试通过不能提升状态。

旧任务基线曾记录 219 passed、3 warnings（功能分支基线 ea2ce55 的旧业务回归准备）；它只作为历史旧回归参考，不证明任何 SDK_LOCAL、PROXY_LOCAL、PROVIDER_REAL、共享网关运维或当前业务集成状态。

## 修代码还是改测试

| 同环境结果 | 下一步 |
| --- | --- |
| 旧基线绿、新分支红、预期行为未变 | 修复实现，保留旧断言 |
| 旧基线绿、需求经明确确认有变 | 更新契约并只调整相关断言，证明其它旧行为未变 |
| 旧和新都红 | 调查已有缺陷、环境或 flaky；不冒充新增回归 |
| 未真实运行 | NOT_RUN，禁止以 mock 总数替代验收 |

## 每张 Test 必须记录的证据

- 精确基线 HEAD 与本次实现 SHA；Python、SDK、Proxy、容器/DB、浏览器等适用版本。
- 可复制的执行命令和脱敏 stdout/stderr；Key、Authorization、新闻正文、私有 continuation 一律不得进入输出。
- 旧测试变更前/后的同环境结果；旧断言 diff 或明确“无断言 diff”。不得无依据修改旧断言。
- SDK_LOCAL、PROXY_LOCAL、PROVIDER_REAL、UAT 分别记录；适用状态没有执行即 NOT_RUN。
- 操作失败、请求计数、错误类型、真实 Provider 的模型/地域/日期与明确请求/输出上限。没有来源或证据保留 NOT_RUN。

## 每个 Task 不能突破的约束

- Key 和私有内容不串用户；GET 恢复不产生上游调用。
- EOF/incomplete 不冒充完整终态；结果保存与业务成功事件同事务。
- 旧执行 token 不得覆盖新任务；同一幂等意图不隐式二次收费。
- 新 BYOK 失败时不得落到管理员/平台 Key、其他用户 Key、跨模型 fallback 或直连 provider。
- 用户 provider Key 不等于 Proxy 项目 virtual key；业务项目彼此隔离；master key 不进业务运行时。
- 共享网关故障时旧新闻与已保存历史仍可读，新 BYOK 请求失败关闭。
- 旧订阅问答/翻译、新闻、TTS、研究等现有行为保持，不能通过放宽旧断言隐藏回归。
- 上游 usage 未知按 unknown/null 展示，不得伪作 0。

