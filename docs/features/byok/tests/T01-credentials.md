# Test T01 · 个人 Key 连接增删改停

> **PLANNED**：本文件为未执行的实施/测试契约，所有测试当前 NOT_RUN。实施时以 `origin/feat/byok-user-api-keys` 最新 HEAD 为准，勿把设计 SHA 当作当前代码。

对应：[T01 Task](../tasks/T01-credentials.md)。

| 用例 | 场景 / 失败注入 | 正确性约束 | 状态 |
| --- | --- | --- | --- |
| T01-01 | A 新增/更新/停用/删除连接，重新进入仍反映最新状态 | GET 无原始 Key，数据加密且 AAD 绑定身份及端点 | NOT_RUN |
| T01-02 | B/匿名/跨站请求尝试访问 A 的连接 | 不可读取或修改，必须 CSRF 与 owner 校验 | NOT_RUN |
| T01-03 | 替换/撤销 Key 后旧 credential_epoch 请求仍在队列 | 旧凭据不可再获调用或提交权限；旧订阅不受影响 | NOT_RUN |
| T01-04 | 只打开页面、保存 Key 或改别名 | provider 调用次数为 0，记录不谎报“已验证” | NOT_RUN |
| T01-05 | 生产只读、开关关闭、缺主密钥 | 拒绝新写操作，无法降级为明文或站点 Key | NOT_RUN |

## 如何证明

- **基线**：先用该卡涉及的旧测试在同一环境记录原始结果，再引入代码修改；不要凭“测试数量全绿”掩盖不相关回归。
- **实际测试**：新 Django unit/DB/HTTP/worker 或 Vitest/浏览器测试按必要范围补齐；没有业务路径运行的模拟测试不能算功能完整。
- **SDK/Proxy 真实程度**：真实官方 SDK + 受控 upstream 为 SDK_LOCAL；锁定 LiteLLM Proxy + 真实 SDK + 受控 upstream 为 PROXY_LOCAL；只有指定真实 provider/model/region 请求为 PROVIDER_REAL。三者分开记录，缺少对应真实执行证据时标 NOT_RUN。
- **回归**：每个改动了旧测试的文件列出 diff，说明产品语义的变更依据；不准无依据放宽断言。
- **用户验收**：用户 A 保存 DeepSeek 通用 Key→刷新看到脱敏连接→替换→停用→删除；用户 B 无权查看/更改。

## 执行证据（后续任务填写）

| 项目 | 结果 |
| --- | --- |
| 本卡状态 | **NOT_RUN** |
| 精确基线 HEAD 与本任务 HEAD | NOT_RUN |
| DB / SDK / 浏览器 / OS 版本 | NOT_RUN |
| 定向测试和原始 stdout | NOT_RUN |
| 旧基线与增量回归对照 | NOT_RUN |
| SDK_LOCAL / PROXY_LOCAL / PROVIDER_REAL / UAT 分别记录 | NOT_RUN |
| 测试代码 diff（包括旧断言修改） | NOT_RUN |
| 可复现功能演示结果 | NOT_RUN |
| 未验证、失败原因、修复 PR | NOT_RUN |

任何来源缺失，保留 NOT_RUN，不能伪造 PASS。

