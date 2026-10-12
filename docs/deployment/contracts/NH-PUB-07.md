# NH-PUB-07 官方申请材料实施合同

- Task ID / Depends on / Base HEAD / Goal：NH-PUB-07；P00/ADR015；dispatch最新HEAD；提供可提交审阅的OpenAI托管接入申请材料，不提交申请、不执行OAuth。
- Owned files：仅docs/deployment/openai-hosted-integration.md。Read-only：GOAL/ARCHITECTURE ADR015、subscription service与docs/chatgpt-subscription-oauth.md；其他文件不得编辑。不再派生，不撤销他人。
- Decision frozen：NewsHub/https://news.lambert.host、CoderLambert/news-aggregator；精确回调候选https://news.lambert.host/api/chatgpt-subscription/callback/（候选不等于已注册）；website_identity_approved=false与hosted_plan_usage_approved=false分别EXTERNAL_BLOCKED。真实client ID/secret/批准scope/resource/token-endpoint-auth-method/issuer契约/credential托管刷新条款/模型许可未知，列待官方确认字段，不虚构值、不复制本地client/tokens到服务器。正式条款/隐私/联系人还未发布，列待站点所有者补充而非造虚假链接/承诺。主Agent已依OpenAI Docs检索并实际抓取官方source：https://developers.openai.com/siwc/website（website限试用/OIDC/精确注册callback/认证方法；身份不等于plan）与https://developers.openai.com/siwc/token-sharing-open-source（远程托管使用须interest申请）。简短中文概括各source，不复制长示例；primary链接贴支持声明旁，日期2026-10-10。账户/迁移/缓存/收费均不在本任务变更。
- Implementation steps：1读GOAL07/ADR015/现本地订阅文档；2写项目/域名/产品场景与两批准申请摘要；3列网站client注册/回调/OIDC与plan托管许可的完整确认表及未知项；4列每用户存储加密、撤销删除/刷新隔离/无管理员共享/无站点收费fallback承诺和待上线政策；5列请求2获准测试账户与真实验证清单，默认flags disabled；6离线验证文档不含实际credential且所有门槛明确。
- Acceptance tests：文档包含项目/回调候选/两approval独立表/全部未知契约字段/官方来源/上线政策未完成项/真实测试NOT_RUN列表；backend/venv/bin/python小脚本assert这些字段与不存在本地secret/token/伪造client_id，git diff --check。只有材料完整标TESTED，不是官方批准PASS。
- Negative tests：明确拒绝OSS dynamic_agent_client+换HTTPS callback；identity授权不能启plan；订阅失败不能管理员或site收费fallback；没有approved client永不跳token；未知联系人/隐私URL不得伪造已有发布。
- Forbidden：不改代码/用户数据、不申请/提交表单/发消息，不真实OAuth/收费/生产操作，不commit或派生Agent，不编造协议/审批/secret。
- Return format：路径/diff摘要、离线校验命令exit、HEAD、两批准EXTERNAL_BLOCKED与需要用户/官方提供的资料清单。
