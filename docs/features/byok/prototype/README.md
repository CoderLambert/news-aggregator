# BYOK 静态交互原型

本目录为已确认页面方向的**独立产品交互演示**。原型没有接入新闻站路由、真实 API、SDK、LiteLLM Proxy、加密存储或服务商计费。它不验证网关协议/路由、项目 virtual key 与用户 provider Key 隔离，也不代表真实 provider 兼容。不要输入真实 API Key。

## 本地预览

下载本仓库分支后，直接通过浏览器打开 [index.html](index.html)；如浏览器限制本地文件，可在仓库根目录运行：

```bash
python3 -m http.server 8000 --directory docs/features/byok/prototype
```

打开 `http://127.0.0.1:8000/`。

可依次体验：模型与用途 → 服务商连接 → 添加模拟连接与模型 → 保存用途偏好 → 文章内体验预览 → 查看空账户状态。

## 截图与冒烟验证

要求 Python 的 `playwright` 模块、Chromium 浏览器及相应运行依赖；执行：

```bash
python3 docs/features/byok/prototype/check_ui.py
```

脚本验证基本模拟操作、无浏览器脚本错误、390px 手机宽度无横向溢出，并将桌面和移动端截图写到 `prototype/screenshots/`。截图为原型生成物，默认不纳入源码提交；无需安装任何 AI SDK、填写密钥或连接厂商 API。

注意：此检查只证明静态原型的基础交互，**不代表 React 实现、BYOK 后端、共享 LiteLLM Proxy、本地 SDK/Proxy 集成或真实模型调用通过验收**。
