# 国内医疗来源动态接入

本目录记录动态来源注册系统及首批国内医疗来源的实施与验收证据。生产调度默认关闭；代码完成、fixture 测试和本地试运行均不等于生产验收通过。

## 入口探测结论

探测时间为 2026-10-15（Asia/Shanghai）。每个来源只请求一个列表入口，成功列表最多检查三篇详情；没有翻页、历史回填、验证码处理或反爬绕过。响应正文未纳入仓库，机器可读摘要见 `source-probes.json`。

| 渠道 | 入口 | 结论 | 限制 |
| --- | --- | --- | --- |
| 中国新闻网健康 | 官方 RSS | `SUPPORTED` | Feed 可解析，但最近更新时间停在 2026-03-06 |
| 中国疾控中心要闻 | 官方 HTML | `SUPPORTED` | 受控 CSS 选择器；初始不翻页 |
| 国家卫生健康委新闻动态 | 官方 HTML | `BLOCKED` | 普通 HTTP 客户端返回 412，不绕过 WAF |
| 国家医保局医保动态 | 官方 HTML | `SUPPORTED` | 受控 CSS 选择器；初始不翻页 |
| 国家药监局要闻 | 官方 HTML | `BLOCKED` | 普通 HTTP 客户端返回 412，不绕过 WAF |
| 国家药监局 UDI 每日增量 | 官方 RSS | `SUPPORTED` | 作为 `regulatory_data` 发布通知，不下载产品主数据 |

## 安全边界

- 新来源必须依次完成探测、审批和人工启用；保存与迁移不会自动调度。
- 摘要与正文许可分开配置。没有当前配置版本的正文审批时只保存摘要和原文链接。
- HTML 与 JSON 配置仅允许有限字段映射和 CSS/点路径，不允许脚本、模板、XPath 或后台代码。
- 所有网络入口都限制 HTTP(S)、官方域名、公开 DNS、响应大小、超时、重定向和请求频率。
- 运行历史、文章、收藏、订阅和聊天记录不会因来源停用而删除。

## 实施与运维

- [功能实现总结](feature-summary.md)
- [实施记录](implementation.md)
- [验收清单](acceptance.md)
- [停用与回滚](operations.md)

迁移初始化的六个渠道中，`chinanews_health`、`china_cdc_news`、`nhsa_news`、`nmpa_udi_daily`
为 `probed`，`nhc_news`、`nmpa_news` 为 `blocked`。它们都没有审批记录，
`CrawlerTarget.enabled` 均为 `false`；迁移、探测和本地测试不会自动开启生产调度。

