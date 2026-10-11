# Codex 执行交接：新闻资讯 BYOK

先读同目录 BYOK_IMPLEMENTATION_PLAN.md。此文件是执行约束，不是“全功能已有验证”的声明。

## 目标与固定决策

在 news-aggregator 原仓库新增用户个人 API Key 和模型配置，覆盖文章问答/分析、全文翻译、推荐问题、研究。保持网站登录与模型凭据独立。

- 使用 openai、anthropic 官方Python SDK；3个薄适配器：Responses、Chat Completions、Messages。
- 六家第一批官方通用Key：OpenAI、Claude、GLM、DeepSeek、Qwen、Kimi。
- 不引入LiteLLM Proxy/SDK、LangChain、新队列、新独立项目、新状态库、第二套翻译任务系统。
- 不接Coding/Token Plan，不使用站点环境Key或订阅Token对BYOK自动兜底，不开启用户任意Base URL。
- 复用ResearchRun/ResearchRunEvent、ChatGPTTranslationTask、现有执行器、SSE和用户隔离。
- 旧订阅入口/数据保持兼容。扩展翻译任务/结果表凭据变体及数据库XOR约束，不复制新任务表。

## 先确定执行基线

已核查参考：
- main@8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd
- feat/news-public-readiness@b874405f31ae303e772d1ed6ef618b68938febed

1. 读取实际工作目录指导文件、当前分支、工作树、远端引用和并行修复。不覆盖未提交改动。
2. 记录真正实施base/head。参考HEAD变化时对差异重新界定，不假装仍在审核旧提交；不要自动合并无关分支。
3. 在同一个可复现环境保存未修改测试的基线日志。标明已有失败/环境失败，不以调整断言制造绿灯。
4. 根AGENTS在参考版本未找到，不等于实际工作目录没有上级/子目录指导。

## 第一个开发任务只做 T00 SDK 协议验证（单张卡）

安装目标环境可用的SDK并记录lock/hash和许可证；不要顺带全面升级依赖。用实际SDK面对可控本地HTTP上游或其匹配传输层，而非仅mock业务返回值。

同一套协议用例覆盖：
- 显式凭据、可信endpoint、并发两个用户的Key/模型不串用。
- 正常完整终态；partial后EOF；length/incomplete；HTTP错误；流内error。
- 工具调用→工具结果→完整回答，保留native continuation及必要reasoning/signature。
- SDK零自动重试、无fallback、超时/关闭资源可观测。
- 应用complete只能来自持久化事务成功，不能由迭代器结束推断。

T00 的完整交付只要求实际 SDK → 受控上游 → 原始终态/工具往返的可运行探针，**不要求同一任务开发连接管理、数据库任务、私有结果与 GET 恢复**。完整个人配置、模型验证、用途偏好、首个文章问答分别交给 T01–T04，私有译文从 T05 开始。缺真实Key时记录厂商实测 NOT_RUN。

真实Key仅从本地Secret/受控配置取用，不输出到聊天、GitHub、日志或提交。每家指定模型实际验证文字流与研究所需工具往返，尤其思考模式。遇到明确适配缺口，只修薄适配器；不要回退自建网关或转移到另一个大框架。

## 后续串行实现顺序

P0–P5 仅用于描述整体技术阶段，**实际单次 Codex 工作只遵循 [tasks/README.md](tasks/README.md) 的 T00–T14 单卡任务及同编号 Test 卡**。T13 单厂家分拆 T13-A..F；范围较大时再沿完整用户流程拆子卡。

P0通过后在同一明确方案内连续推进，不把每个小文件当成一道审批。

## 不可破坏的不变量

1. 恢复模块只有GET读取/重放能力，无创建/dispatch/SDK依赖；后端GET也不能隐式收费。translation.wait_for_update现有派发行为不可用于新的只读入口。
2. request_hash与execution_digest分开；命中旧幂等请求先返回其固定快照，不用新默认模型重新解析。
3. 输入正文/历史、模型参数和提示词版本固定；不能用新正文配旧hash。
4. selection revision、credential_epoch、task generation/run_token分开；选默认模型不抹掉已保存事实。
5. 换Key/删除连接后旧调用不能继续获准、旧回执不能提交；已发出请求不承诺零费用或立即取消。
6. SSE关闭只是断开订阅；明确POST取消后按服务器回执显示取消。未知在途结果不自动重发。
7. BYOK完整结果默认私有，公共发布分支不能被误调用；任务状态、结果和完成事件在同一事务提交。
8. owner在入口和写入边界都验证。恢复历史不要求连接仍启用或Key可解密。
9. native continuation只在服务端受版本/协议约束保存；对前端投影只返回可见内容，不用思考内容当权限指令。
10. 测试结果和异步UI更新绑定user/task/config revision，不覆盖新状态。使用次数按上游尝试记，未知Token不记0。

## 测试失败的决策

旧基线通过、新分支失败且行为未变：修实现。明确的新需求变更行为：先更新契约，再改对应断言，保留未变功能证据。两边都失败：调查已知缺陷/环境/不稳定性，单独记录，不通过删除用例掩盖。

交付必须展示修改过的测试diff及理由。附带的validation是隔离设计原型，不能直接复制成生产实现，不能计为项目测试已经通过。

## 最终报告

精确base/head、增量文件/数据迁移、复用内容、被结构性禁止的错误路径、同环境基线对比、实际SDK/厂商/浏览器验证分别列出、未验证项、开关与安全回退方式。没有实际执行的步骤写NOT_RUN；不要用总通过数量替代证据。

