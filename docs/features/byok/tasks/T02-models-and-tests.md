# T02 · 录入模型并显式验证

> **READY FOR REVIEW（2026-10-12）**：模型目录、用户模型 CRUD、文本/工具显式探测和隔离 T00-G LiteLLM Proxy 联调均已实现。当前实现只开放服务端预批准的 DeepSeek Flash alias；手动模型 ID 可以保存，但没有预批准路由时不能测试。没有向真实供应商发请求。完整证据见 [Test T02](../tests/T02-models-and-tests.md)。

本工作树基于 T01 PR #34 的提交 8eb383991e1a0b83de07dd34aa40d5721172e7df。T01 PR #34 与 T00-G PR #35 仍未合并；T02 的评审说明必须保留这两个前置依赖。T02 实现提交为 2bcf1cb22d4f0e070bedc0de14272a90cf4b325d（模型配置）和 80bc47180786071ba651ea256581dffad90c892a（显式探测）。

| 属性 | 内容 |
| --- | --- |
| 前置任务 | [T01](T01-credentials.md)、[T00 本地技术门槛](T00-sdk-protocol.md)、T00-G 受控网关 PR #35 |
| 推荐规模 | M |
| 对应测试 | [Test T02](../tests/T02-models-and-tests.md) |
| PR 目标分支 | feat/byok-user-api-keys；PR 描述需要注明依赖 T01 PR #34 与 T00-G PR #35 |
| 本卡 PR | [#36 Draft](https://github.com/CoderLambert/news-aggregator/pull/36) |

## 交付内容

用户可以在自己的可信服务商连接下添加多个目录模型或手动模型，并执行互相独立的短文本和工具能力探测。模型测试只由用户显式触发，每次调用创建独立的 AICallAttempt；界面在发送前说明可能产生供应商费用。探测请求使用固定短提示、固定服务器 alias、15 秒超时、64 KiB 响应上限，不跟随重定向、不重试、不切换凭据或供应商。响应只保存安全错误码、请求 ID、耗时和 token 数，不保存原始供应商响应或 Key。

测试结果与 credential epoch、model config revision、endpoint profile version 绑定。请求执行期间若任一版本变化，迟到结果只记入原尝试记录，不覆盖当前模型能力状态。能力分别记录；文本成功不会推断工具调用成功。

手动录入模型没有预批准网关路由时，仍可保存和编辑，但测试接口会在发送前拒绝。T02 的显式探测接口仅接受 probe_kind，不接受 messages、文章正文、endpoint、extra_body 或其它供应商参数。上下文上限未核实的模型会在页面显示提示；本卡没有实现 BYOK 业务文章调用。

## 验收路径

创建一个用户连接，添加目录中的 DeepSeek Flash 和一个手动模型；文本/工具按钮只对目录预置模型开放。文本探测可得到独立能力结果，工具探测必须单独发起和判断。替换 Key 后旧状态失效；若旧探测回执迟到，也不能覆盖新 epoch 的状态。整个测试流程使用本地隔离 Proxy 和合成上游，不需要向真实供应商发请求。

## 对应 Test 用例

| Test ID | 可操作情境 | 必须观察到 | 状态 |
| --- | --- | --- | --- |
| T02-01 | 新增多个模型并重新读取列表 | 按用户/连接隔离；目录失败可手动录入；目录模型可编辑、删除 | PASS；未运行浏览器 E2E |
| T02-02 | 显式触发文本/工具测试 | 每次真实 Proxy 上游尝试各自记账；页面提示可能收费；无自动重试 | PASS；合成 Proxy 联调 |
| T02-03 | 文本与工具能力分别验证 | 文本成功不推断工具能力；工具探测不成功时保持 unknown | PASS；合成上游验证 |
| T02-04 | 换 Key 或更新模型/端点配置，旧结果迟到 | 按 credential_epoch/config_revision/endpoint_profile_version fencing | PASS；模型测试竞态和旧配置失效测试 |
| T02-05 | 手动未知模型、URL 或 extra 参数 | 未知模型不能进入 Proxy allowlist；用户不能提交 endpoint 或额外代理参数 | PASS；请求在创建 attempt 前拒绝 |
| T02-06 | 未知上下文模型面对长文章 | T02 不提供文章调用路由；探测接口拒绝用户提交文章正文，页面说明 context 未核实 | 防护 PASS；未来业务调用的上下文裁剪 NOT_RUN |

## 明确边界

当前目录只为 DeepSeek Flash 配置了固定 alias news.deepseek-flash。新增供应商或手动模型的真实探测需要先在运维侧批准并添加受限服务端路由。此卡不做任意模型发现、动态 alias 拼接、完整新闻/研究调用、供应商真实请求或生产迁移。详细验证命令、精确环境、联调输出和未运行项见 Test T02。
