# T04：完成报告

实现状态：REVIEW_READY（2026-10-16）。专项：37 PASS；生产放行：NOT_RUN。
任务提交为本报告所在原子提交；分支 `task/rss-T04-engine-adapter`，基线 `72ab3a1`。PR/CI/集成评审由调度方记录，未在本任务宣称通过。

## 实现与接口

- `backend/api/rss/engine.py`：固定部署配置的官方 `miniflux==1.1.6` 包装；配置来自 `RSS_ENGINE_INSTANCE_UUID`、`RSS_ENGINE_ACCOUNT_ID`、`RSS_ENGINE_BASE_URL`、`RSS_ENGINE_TOKEN_FILE`。token 不进入 repr/异常；首次 `/me` 核对专用非管理员账号，每个 Feed/Entry 核对 user_id，单项读取核对请求 ID。
- `FeedDTO` / `EntryDTO` 使用白名单，剔除密码、cookie、代理、enclosures/icon、引擎 hash 等。内部 ID 为 int，`to_dict()` 使用十进制字符串；时间转 UTC。Entry.content 是给 T06 的原始 HTML，不能直接作为公开 API 内容；T06 仍负责内容内链接/图片安全清理。
- discover/list_feeds/get_feed/create_feed/set_enabled/update_feed_policy/refresh_feed/read_upper_bound/list_entries/get_entry/refetch_entry 均走官方 SDK。唯一端点补充是 SDK 固定 fetch-content 增加 `update_content=true`，随后独立 GET 比对内容和 feed 身份。
- `PolicyBinding` 字段与 T05 对齐，`update_feed_policy` 也接受同字段 ORM 对象；mode 仅 `feed/full_content`，过滤规则仅部署配置的命名批准集合。`PolicyReceipt.applied_policy_version` 只是核对回执，调用方仍必须在短事务内 CAS 当前政策/租约。Adapter 不导入 Django，不读写数据库。
- `EngineError` 只含安全 code、retryable、unknown_result、retry_after。读取最多 3 次（可配 1..5）；遵循 Retry-After，过长则交持久调度延后。控制动作不自动重试；创建在动作前与未知结果后查列表，配置在 PUT 后 GET 核对，修复在动作后 GET 核对。未知创建列表仍为空不能证明远端终止，T08 必须维持 unknown/人工阻塞，不能再次调用 create_feed 冒充安全重试。
- 排他分页固定 `after_entry_id=L,before_entry_id=H+1,order=id,direction=asc`；验证整页数量、升序、重复、身份及上下界后才返回。H=int64 最大值显式 `upper_bound_overflow`，不截断、不猜游标。页超限/残缺响应也不返回部分条目。
- 小型 Requests Session 补丁覆盖所有 SDK 入口：禁环境代理、禁 API 重定向、按 Requests 解压后字节计量，默认最多 8MiB；不含自定义 transport DTO、解压器或流式 JSON 解析器。每个 worker slot 独立 adapter，不能跨并发共享 Session。

## 实际运行证据

独立环境 `/tmp/newshub-rss-t04-py312`，Python 3.12.14、pytest 9.1.1、miniflux 1.1.6、requests 2.34.2、urllib3 2.8.0；只用回环临时端口的合成 HTTP 服务，无 Django/业务库/生产网络。

```sh
PYTEST_DISABLE_PLUGIN_AUTOLOAD=1 PYTHONPATH=backend \
  /tmp/newshub-rss-t04-py312/bin/python -m pytest \
  -c tests/rss_engine_contract/pytest.ini --confcutdir backend/api/tests/rss \
  backend/api/tests/rss/test_engine_adapter.py -q
# exit 0: 37 passed in 18.47s

git diff --check
# exit 0
```

| 专项 | 实测 |
| --- | --- |
| T04-A1 | 创建 HTTP503 或真实 socket timeout 后 GET 找回；只发一次 POST；未找到保持 unknown；成功 ACK 后 GET 失败也不变成可盲重试成功/失败 |
| T04-A2 | 白名单 PUT、独立 GET、未知 PUT 后核对、值不一致拒绝、过期版本不发请求、批准过滤规则键 |
| T04-A3 | 精确 `update_content=true`、GET 内容比对、未持久化拒绝、GET 失败保持未知，不以刷新承诺旧正文重提取 |
| T04-A4 | 所有读/写入口与 `/me` 超限；32MiB gzip 解压响应在 256KiB cap 拒绝，tracemalloc 峰值断言 <8MiB；socket timeout 后同 adapter 可恢复下一调用；401/403账户/秘密字段边界、重定向不跟随、上游错误内容不外泄 |
| 分页/DTO | UTC、int64 JSON字符串、空H、H+1溢出、乱序/重复/越界整页拒绝、残缺JSON不能当空页、内部媒体字段剔除 |

首轮 Python3.14.8 25项通过仅为开发证据，最终验收以上述3.12完整37项为准。Miniflux/PG真实合同复用 [T00报告](../T00/report.md) 和 [`ops/rss/T00`](../../../../../ops/rss/T00/README.md)，不把本地HTTP fixture称为真实Miniflux验收。创建 disabled/crawler 和过滤字段另核对 [Miniflux 2.3.3官方Feed请求结构](https://github.com/miniflux/v2/blob/2.3.3/internal/model/feed.go)。

## 未验证与下游要求

- 未完成生产部署/最终镜像资源限制、持续 trickle 占槽后进程监督终止重启、真实worker租约恢复。socket timeout不是总期限，测试不证明远端取消。T02/T08/T09需要集成这些恢复行为；不能将本报告的超时后新HTTP调用成功扩写为监督重启PASS。
- T00已标明的公网重定向/DNS rebinding/网关真实凭据完整门禁仍未解决。本 adapter 只提供公开 HTTPS 准入语法检查，SSRF DNS/重定向防护依赖引擎与部署；没有开放业务自选cookie/header/proxy/secret。T18网关secret功能接入仍待批准配置和真实证据，不阻塞native fixture实现。
- 响应大小实测适用于以上 Requests/urllib3 版本，最终轻量镜像依赖锁变更须重跑该边界测试。大页无法得到完整身份必须保留游标，调低页大小或调整经测量的上限后重放；不可猜ID推进。
- 服务层必须确保网络调用不跨DB事务，校验refetch授权/政策并在提交时重新CAS；此模块不替代授权、意图、lease或当前正文写权检查。

修改仅限 engine.py、专项测试、miniflux依赖pin及本报告；未改 models/urls/compose，未操作用户DB、main或生产。
