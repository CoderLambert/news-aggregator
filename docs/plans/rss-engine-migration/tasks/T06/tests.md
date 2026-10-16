# T06：专项验收

状态：PASS（30 项纯函数测试）；集成/CI/浏览器验收未运行。实现与具体风险见 [report.md](report.md)。

- T06-A1：脚本/event/style/嵌入文档清理；危险 scheme、内部媒体与凭据 URL 拒绝；相对 URL、HTTPS 图片和 Markdown 注入边界。
- T06-A2：标题、表格、嵌套列表、引用及代码字符/空格/tab/空行/反引号围栏保真。
- T06-A3：HTML/Markdown 各默认 2MiB；UTF-8 字节边界和转义膨胀明确抛 `ConversionError`，不截断。
- T06-A4：同输入/版本确定 raw/canonical hash、LF；输入字符串不变且返回结果冻结。历史正文写库/保护由 T07 测试。

## 执行与证据

独立 Python 3.12.14 环境解析安装了以下版本。下列前两条可复现环境，后两条为实测验证命令：

```bash
uv venv --python 3.12 /tmp/newshub-rss-T06-venv
uv pip install --python /tmp/newshub-rss-T06-venv/bin/python \
  nh3==0.3.7 markdownify==1.2.3 beautifulsoup4==4.15.0 pytest==9.1.1
PYTHONPATH=backend /tmp/newshub-rss-T06-venv/bin/python -m pytest \
  -c /dev/null -p no:cacheprovider -q backend/api/tests/rss/test_content_conversion.py
git diff --check
```

专项及 diff 检查退出码 0，30 passed。无需 Django 配置/插件/数据库；`-c /dev/null` 避免仓库级 Django 启动。依赖安装使用网络，转换函数和专项用例不访问网络。没有修改主工作区 venv 或使用用户数据库。

纯函数专项即可验证本任务；浏览器渲染交由 T13/T27，候选 CAS/历史正文交由 T07。公共域名 DNS/可达性由部署/渲染侧保证，本模块只做词法地址检查，不声称网络认证。真实引擎、上线与完整回滚证据未运行。

## 完成条件

专项已通过，等待实现评审、集成及 PR 必需检查。任务模块实现不等于产品集成或生产放行。
