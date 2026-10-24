# <功能> 场景规格

## 需求与真实契约

用户目标：
基线 SHA、真实 API/序列化器/客户端/parser 文件：
允许的合成数据来源：
不允许的网络、密钥、数据库与副作用：

## 业务经历

| ID | 身份/版本/初始状态 | 用户操作 | 服务响应序列 | UI/缓存预期 | 恢复方式 |
|---|---|---|---|---|---|
| <feature>-normal | | | | | |
| <feature>-empty | | | | | |
| <feature>-retry | | | | | |
| <feature>-permission | | | | | |
| <feature>-stale | | | | | |
| <feature>-cancel | | | | | |

删除无意义的行；不要机械组合所有状态。共享 fixture 只共享数据，不共享预期答案。

## 代码改动清单

- 现有 API Client / parser 是否需要修改？变化语义是什么？
- 新 handler 如何决定请求次数、版本、取消与 terminal 状态？
- 未识别操作是否仍失败，而不是默认成功？
- catalog 与独立 Matrix 的新增 ID 是否一一对应？
- 真实组件/页面操作是否被验证，而不是只断言网络返回？
- cookie、viewer、CSRF、AbortSignal 是否仍走原路径？

## 验收记录

指定 Luna xhigh 任务标识：
工作区、候选 SHA 或未提交差异、依赖锁指纹：
命令、范围、退出状态与日志：
PASS / FAIL / BLOCKED / NOT_RUN 分别记录：
真实 Django/引擎/provider/生产/UAT 未覆盖项：
用户验收与提交/推送授权：
