# NewsHub 托管 ChatGPT 接入申请准备材料

**更新日期：** 2026-10-10

**状态：** 内部审阅草稿；**未提交申请、未取得官方批准、未执行真实 OAuth 或订阅调用**。

## 项目与申请意图

| 字段 | 当前资料 |
| --- | --- |
| 产品 | NewsHub，项目 `CoderLambert/news-aggregator` |
| 网站 | `https://news.lambert.host/` |
| 网站运营者/申请联系人 | 待站点所有者补充；目前没有可用于申请的正式联系人资料 |
| 网站身份回调候选 | `https://news.lambert.host/api/chatgpt-subscription/callback/`；候选地址，尚未登记或获批 |
| 当前接入状态 | `CHATGPT_AUTH_MODE=disabled`；网站身份与订阅调用均关闭 |

NewsHub 希望先申请网站 OAuth/OIDC 身份客户端，再单独确认是否允许由远程托管网站使用用户各自授权的 ChatGPT plan。产品设想是在用户明确连接并选择自己的账号后，供其使用聊天、建议问题和文章翻译。此描述是待申请审阅的产品意图，不表示现有本地开源流程已经适用于公网，也不表示任何功能已获准上线。

官方资料核对日期为 2026-10-10。OpenAI 网站身份资料当前说明该接入经指定合作方试用，需按网站客户端流程注册并使用登记的精确回调和客户端认证配置；开源 token-sharing 资料区分本地/开源与远程托管场景，远程托管 plan usage 需要另行申请。应以官方对本项目给出的书面配置和协议为准：[Website identity integration](https://developers.openai.com/siwc/website)，[Token sharing for open-source applications](https://developers.openai.com/siwc/token-sharing-open-source)。

## 两项独立批准

| 门槛 | 请求内容 | 当前状态 |
| --- | --- | --- |
| `website_identity_approved` | 为 `news.lambert.host` 申请正式网站身份客户端；确认网站注册要求、回调登记和 OIDC 客户端配置 | `false` / **EXTERNAL_BLOCKED** |
| `hosted_plan_usage_approved` | 单独申请远程托管网站使用用户 ChatGPT plan 的资格及完整调用契约 | `false` / **EXTERNAL_BLOCKED** |

取得网站身份客户端不等于获准调用用户的订阅额度。即使第一项先获批准，第二项未获批准或契约未实现时，订阅调用仍必须关闭。项目不会把本地 OSS 的 `dynamic_agent_client` 与 loopback 流程替换成 HTTPS callback 来冒充网站 client，也不会据此直接尝试公网授权。

## 待官方确认的客户端与协议字段

本材料不填写推测值。只有官方给出与 NewsHub、网站域名及用途匹配的正式契约后，才能决定对应实现。

| 字段 | 待确认内容 |
| --- | --- |
| Website client | 是否批准；正式 `client_id`、是否签发 `client_secret`、适用环境及登记主体 |
| 回调地址 | 是否批准候选地址 `https://news.lambert.host/api/chatgpt-subscription/callback/`；开发/测试/生产各环境的精确登记值 |
| OIDC issuer | 正式 `issuer`、discovery/JWKS 约定、受众和身份声明验证要求 |
| Scope / resource | 网站身份所需 scope，以及若 plan usage 获批，其独立授权 scope、resource/audience 和用户同意方式 |
| 客户端认证 | 正式 `token_endpoint_auth_method` 及 Token endpoint 支持的认证方法。**不假定存在 `client_secret`**；若签发，仅由后端按官方要求保管，绝不进入仓库、浏览器或静态资源 |
| 授权与 Token 端点 | 正式授权、兑换、刷新、撤销端点；PKCE、授权码寿命、错误响应及重试约束 |
| Hosted plan usage | 是否允许本产品形态和预期功能；可用模型、请求限制、额度耗尽语义、政策及禁止用途 |
| Token 托管条款 | 网站能否代用户安全保存/刷新/撤销凭据；期限、轮换、撤销、泄露响应与删除义务 |
| 运行标识 | 网站场景是否需要 host/install 标识、其生成和持久化要求；不得自行沿用本地 OSS 参数 |

`openid profile email` 等身份 scope 本身不构成订阅推理授权。不能自行添加本地 OSS 使用的 `chatgpt.tokens.use.direct` 或其他 scope 来推断取得 plan usage 权限。

## 用户凭据与费用边界（拟采用政策，待官方条款确认）

- 每个授权连接归属于发起连接的 NewsHub 用户；只使用该用户明确授权的连接。一个人的 ChatGPT Token、账号、模型选择或缓存不得提供给其他用户或管理员使用。
- OAuth 凭据只在服务端加密保存并按用户/连接隔离；浏览器和静态产物不接触 Token，日志不记录 Token、授权码、PKCE verifier 或敏感完整授权 URL。密钥轮换、备份、保留期限和删除时限须在上线政策中明确。
- 用户主动断开或授权撤销后，立即停止使用该连接并清除本地 access/refresh/ID Token；若远端撤销失败，需如实提示并遵循官方重试和保留条款，不得自动重新授权。
- 订阅连接不可用、额度不足或上游失败时，**不改用管理员订阅、其他用户 Token 或站点付费 API 作为静默 fallback**。未获准或无法按用户授权路径调用时，功能明确关闭并告知用户。
- 上述为拟申请的隔离与费用边界；数据处理说明、留存/删除时间、用户同意文案、隐私政策及服务条款必须由站点所有者审定并发布后，才能作为正式公开承诺。

## 站点所有者待补资料

以下信息目前未提供，故不伪造联系人、正式隐私链接、服务条款链接或已经发布的政策：

- 法律/运营主体、申请联系人姓名、职务、工作邮箱及官方要求的验证资料。
- 正式隐私政策、服务条款和面向用户的 AI/订阅数据处理说明 URL；当前尚无已核实的正式链接。
- 服务地区、目标用户、账号支持与删除联系渠道，以及数据保留、备份过期、用户撤销和删除流程。
- 两个经官方批准可用于真实验收的测试账号及其各自明确的授权同意；本材料不索取或记录账号密码、Token 或恢复码。
- 预算与功能负责人，以及订阅额度不足、撤销失败和服务中断时的用户提示与支持流程。

## 获批后的真实验收清单

取得正式批准、配置和测试授权之前，下列项目全部为 **NOT_RUN**，不能用 mock、当前本地 OSS 流程或文档检查代替：

1. 用获批网站 client 完成两个获准测试账号的真实 HTTPS 授权，核实回调、issuer/audience、身份绑定和用户可见授权说明。
2. 验证两名用户分别只访问自己的连接、模型选择和凭据；并发授权、重新授权或撤销一方不得改写另一方数据。
3. 按正式契约验证 Token 兑换、刷新、撤销、服务重启后的密钥/连接恢复，以及已撤销或失效 Token 的隔离。
4. 验证 plan usage scope/resource、允许模型、额度不足和上游失败行为；确认失败时不会转用管理员 Token、其他用户凭据或站点付费 API。
5. 验证用户断开、账号删除、数据清理、日志脱敏和官方约定的数据留存策略。

## 当前安全门槛

在两项批准独立取得、官方契约完整、代码按契约完成并通过审查前，必须保持：

```text
website_identity_approved = false
hosted_plan_usage_approved = false
CHATGPT_AUTH_MODE = disabled
CHATGPT_PLAN_USAGE_ENABLED = 0
PUBLIC_AI_ENABLED = 0
```

本材料仅为待审申请准备稿；它不是申请已提交、网站 client 已注册、身份登录已获批、plan usage 已获批或公网功能已启用的证明。
