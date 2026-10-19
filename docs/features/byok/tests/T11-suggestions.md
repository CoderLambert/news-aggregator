# T11 私有推荐问题实施记录

基线 main `033bfad`。复用 NewsSuggestedQuestionsView、用途偏好、trusted gateway、原文快照与 credential commit 围栏、既有建议预算。

- GET 只读本人当前文章/模型缓存，无缓存时返回 generated:false 的免费模板。客户端首次加载只发 GET。
- 显式 POST 的 model_config_id + consent:true 才调用个人模型；不自动重发。能力/epoch/文章权限变更拒绝派发或保存。
- 新表 PrivateSuggestedQuestions 按 owner/news/source_hash/execution_digest/prompt_version 唯一；source_hash 包含文章元数据和权限版本；个人输出不写公共 News 缓存。
- 输出须为三个不同、非空、长度有界的 JSON 字符串，真实 stop 才保存。格式/网络失败显示错误，不用模板伪装模型成功。
- 前端显示偏好的推荐模型与结果来源，每次生成重新确认费用；缓存键包含 viewer、文章 revision、所选模型和偏好版本。
- 旧订阅显式 POST 保持兼容；本次不扩展订阅推理或站点密钥路径。

验证：前端类型检查、生产 build、相关 hooks/API/助手 18 项最终 PASS；实际 parser 非法格式/重复/类型负例 PASS；Python AST 与 diff 检查 PASS。后端 pytest/PyYAML 缺失，Django/数据库回归 NOT_RUN；真实厂商、迁移/部署及浏览器 UAT NOT_RUN。首次 hook 测试暴露偏好加载状态与 mock 队列问题，已修正并仅重跑失败文件。

迁移 0069 仅新增私有表，未执行生产迁移。回退代码关闭新生成入口即可；保留新增表数据。
