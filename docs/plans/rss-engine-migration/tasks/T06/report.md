# T06：完成报告

实现状态：READY_FOR_REVIEW。专项验收：PASS（30 项）。产品集成、CI、浏览器和生产运行尚未验证。

## 实现与消费接口

`backend/api/rss/content.py` 提供纯函数：

```python
convert_html(html: str, *, base_url: str,
             max_html_bytes: int = 2 * 1024 * 1024,
             max_markdown_bytes: int = 2 * 1024 * 1024) -> ConvertedContent
```

`ConvertedContent` 是冻结 dataclass，字段为 `markdown`、`raw_hash`、`canonical_hash`、`conversion_version`。`ConversionError(ValueError).code` 为 `html_too_large`、`markdown_too_large`、`invalid_html` 或 `invalid_base_url`；不携带正文或 URL。空输出交给调用者按 C04 拒绝，不标记完整性或可读状态。

`raw_hash` 为精确输入 HTML UTF-8 SHA256；只有文章 URL 和转换版本均未变化时才可据此跳过转换。`canonical_hash` 为 LF Markdown UTF-8 SHA256。T07 负责组装带身份/政策/写权令牌的 BodyCandidate、历史正文保护和 CAS；本模块不导入模型、不改库、不获取网络、不识别主体、不调用旧修复代码。

白名单清理删除脚本、事件属性、样式、嵌入文档和 SVG/MathML。相对资源按服务器给定文章 URL 解析；链接只保留 HTTP(S)，图片仅 HTTPS，拒绝 userinfo、私网/环回/元数据 IP、本地主机名、危险 scheme。Markdown 目的地址、图片 alt、实体文本和代码围栏分别转义，避免 HTML 清理后经 Markdown 重新注入。代码块保留文本、空格、tab 和空行（HTML 解析语义、CRLF/CR 转 LF 除外）；代码中反引号决定围栏长度。

## 版本与许可证

Python 3.12.14；nh3 0.3.7（MIT）、markdownify 1.2.3（MIT）、BeautifulSoup 4.15.0（MIT，现有依赖改为精确锁定）。许可证由安装包 LICENSE 实际核查；[nh3 API](https://nh3.readthedocs.io/en/latest/) 与 [markdownify 官方项目](https://github.com/matthewwithanm/python-markdownify) 用于核对清理及转换 API。转换版本 `rss-html-v1:nh3-0.3.7:markdownify-1.2.3:bs4-4.15.0`；清理策略/格式或依赖变化须更新版本。

隔离环境 `/tmp/newshub-rss-T06-venv`，没有使用主工作区 venv 或用户数据库。测试依赖 pytest 9.1.1；独立人工渲染检查使用 markdown-it-py 4.2.0，仅装在测试环境，未增加生产依赖。

## 实测证据

```bash
PYTHONPATH=backend /tmp/newshub-rss-T06-venv/bin/python -m pytest \
  -c /dev/null -p no:cacheprovider -q backend/api/tests/rss/test_content_conversion.py
git diff --check
```

退出码均为 0；专项 30 passed。以 `-c /dev/null` 隔离仓库 Django 配置（无 Django 安装或连接数据库），禁用 cacheprovider 避免在 `/dev` 创建 pytest cache。

- T06-A1：脚本/event/style/iframe/SVG/object、22 种危险 scheme/内部地址/凭据/端口反例、相对 URL、HTTPS 图片及 Markdown 注入，PASS。
- T06-A2：标题、表格（含管道字符）、嵌套列表、引用、粗体/斜体、代码块和 inline code，PASS。
- T06-A3：默认 2MiB HTML 限额、UTF-8 字节边界、Markdown 转义膨胀限额、明确错误码且不截断，PASS。
- T06-A4：同输入/版本结果一致、原始和规范 hash、LF、冻结结果、原始输入不变，PASS。本模块完全不涉及历史数据库；历史正文 CAS 在 T07 验证。
- 补充：CommonMark 实际渲染四个实体/alt/代码注入样本，断言没有 `<script>` 元素，PASS；这是有限样本检查，不是 T13/T27 浏览器验收。

## 交付、门禁与风险

分支 `task/rss-T06-content`；提交为本报告所在原子提交，SHA 由主调度记录，PR/CI 尚未运行。待主调度评审和集成；不修改接口合同、状态文件、模型或路由。

BeautifulSoup 是既有共享依赖，本次 pin 同时约束旧采集路径可安装版本；没有改旧逻辑，旧路径全量回归留待集成检查。

URL 防护为无网络的词法判断：不能证明公共域名的 DNS 结果、可达性或后续重绑定安全，部署/渲染媒体策略仍需验收；不宣称完整 SSRF 防护。浏览器渲染、真实引擎、历史正文写入和全仓回归不属于本专项，尚未验证。无生产操作，无数据写入，恢复仅回退模块和依赖版本（已写历史正文不做规范化）。
