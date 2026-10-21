# Ollama Cloud 模型验证 403 的本地配置修复

日期：2026-10-21。运行配置已修复；未发起云端推理，等待用户重新进行能力验证。

## 原因

当前用户新建 minimax-m3.1-flash 后发起的一次文本测试、两次工具测试都记录为 unknown / gateway_rejected。网关 access log 对应三个 POST /v1/chat/completions 均返回 403。问题不在“未点击测试”：用户已主动测试，但被本地项目 Key 的路由权限拒绝。

此前本地网关恢复操作将原 allowed_routes=[] 错误变成了仅 ['/newshub/models/discover']。模型发现因此可以成功，而推理被拒绝。该遗漏来自本次会话之前的运行配置恢复脚本，不是用户 Key 或模型参数已被证实错误。

## 修复与证据

沿用原项目 Key，仅补入文档要求的 llm_api_routes，保留 /newshub/models/discover；模型别名 allowlist 保持完全相同，没有轮换密钥、修改用户用途选择或重建数据库。修改持久保存在既有网关数据库中，不需要重启服务。

PASS：重新读取项目权限，allowed_routes 同时包含 llm_api_routes 和 /newshub/models/discover，模型 allowlist 与修改前相同。

PASS：使用不含服务商 Key、messages=[] 的固定无效本地请求，返回 HTTP 400 / BYOK_TRUSTED_ROUTE_REJECTED，而不是原来的权限 403。该请求由本地校验拒绝，不能到达服务商，不属于模型能力验证。

NOT_RUN：真实 Ollama Cloud 文本/工具推理、默认用途保存、问答/翻译/研究。不能把路由权限修复声明为模型已经验证通过。原来失败的能力记录保持原状态，不伪造 PASS。

## 用户验收

1. 回到 AI 设置，勾选费用确认后重新点击该模型的测试文本能力。
2. 如需深度研究，再主动测试工具能力；文本通过不代表工具已通过。
3. 验证通过后，全局默认选择新模型，将需要继承的新闻问答、全文翻译、问题推荐等用途改为跟随个人默认并保存。
4. 原先显式绑定已停用 DeepSeek 的用途不会因新增连接自动改用 Ollama。

配置修复前的路由列表保存在 /home/lambert/.local/share/newshub/ai-connections-20261021/routes-before-inference-fix.json，可按明确需要回退权限；不操作模型 Key 或用户数据。
