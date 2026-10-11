# BYOK Test 契约（尚未执行）

**所有 T00–T14 / T13-A–F 测试均为 NOT_RUN，测试文档是计划不是测试记录。** 每张 [Task 卡](../tasks/README.md) 对应同名 Test 文件。

## 证据级别

| 级别 | 可以证明什么 | 不可以冒充什么 |
| --- | --- | --- |
| UNIT | 逻辑、权限和数据不变量 | SDK 或厂商真的可用 |
| SDK_LOCAL | 真 SDK 经过可控 HTTP 上游发送请求、解流和识别真实事件 | 六个真实厂商已成功 |
| INTEGRATION | Django+Session+CSRF+DB/worker/SSE/React 对应真实操作 | 真实厂商某模型可调用 |
| PROVIDER_REAL | 明确厂商通用 API Key+model+region+日期上的真实调用 | 其它模型/地区也兼容 |
| UAT | 用户在最终运行环境里的真实操作 | 先行自动测试能代替用户验收 |

建议先检查当前脚本后使用：`cd backend && python manage.py test api.tests`；`cd frontend && npm run typecheck && npm run test:run && npm run build`。目标机器依赖或测试失败按事实记 `BLOCKED/FAIL`，没有执行记 `NOT_RUN`。

## 修代码还是改测试

| 同环境结果 | 下一步 |
| --- | --- |
| 旧基线绿、新分支红、预期行为未变 | 修复业务代码，旧断言保持 |
| 旧基线绿、需求经明确确认有变 | 写新语义并只修改相关断言，保留其它旧回归 |
| 旧和新都红 | 调查现有缺陷、环境或 flaky；不冒充新回归 |
| 未真实运行 | NOT_RUN，禁止展示 mock 总数替代上线验收 |

## 每个 Task 不能突破的约束

- Key 和私有内容不串用户；GET 恢复不得产生上游调用。
- 流中 EOF 不能当成功；结果保存与成功事件同事务。
- 旧执行 token 不得覆盖新任务；同幂等意图不隐式二次付费。
- 当前原文 stale 不等于保存失败；历史可在 Key 撤销后只读。
- 新 BYOK 禁用时不能偷偷落到管理员 Key 或 ChatGPT 订阅。
- 旧订阅翻译/问答、研究读取、TTS 等现有行为保持，不能通过修改旧测试隐藏回归。
- 上游 usage 未知按未知展示，不得伪作 0。

各个 Test 文件有**执行证据占位表**；由 Codex 实际执行后填写真实结果。T13 各厂商另有独立的 Test 卡。

