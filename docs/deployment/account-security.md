# 账户安全边界

NewsHub 账户使用 Django session。登录和注册即使在匿名状态也要求服务端验证 CSRF；退出登录要求已有 session，并由 `SessionAuthentication` 校验不安全请求的 CSRF。研究写操作也使用标准 session CSRF。前端传入的 `X-CSRFToken` 只有经 Django/DRF 校验后才有效。

登录与注册限速保存在 SQLite 中，跨进程共用固定窗口：登录按来源 IP 每 10 分钟最多 20 次，并按 IP 与用户名的大小写折叠值每 10 分钟最多 5 次；注册按 IP 每小时最多 5 次，全站每小时最多 100 次。限速键使用当前 `SECRET_KEY` 的 HMAC 摘要，不保存原始 IP 或用户名。客户端地址只取连接层的 `REMOTE_ADDR`；不信任 `X-Forwarded-For`。安全写事务先更新单例写锁。SQLite 忙锁只重试三次；仍无法取得锁时请求失败关闭并返回 `auth_security_busy`，不会继续认证或注册。

生产环境注册必须使用与邮箱匹配、未过期且未消费的一次性邀请，即使 `PUBLIC_SIGNUP_ENABLED=1` 也不会跳过邀请校验。运维人员可用以下命令签发邀请：

```sh
python manage.py create_signup_invite --email person@example.com --expires-hours 24
```

有效期必须为 1 到 168 小时，默认 24 小时。命令只在标准输出显示一次明文 token；数据库只保存 SHA-256 摘要。该 token 需要通过项目实际批准的带外方式安全交付。该流程本身不会发送邮件。

注册始终运行 Django 密码验证器，并检查用户名、邮箱和密码的类型及长度。用户名冲突统一返回 `registration_unavailable`，不透露邮箱是否已有账户。无效、过期、已消费或邮箱不匹配的邀请统一返回 `invite_required`。创建用户、消费邀请和写入登录 session 在同一数据库事务中完成。

当前没有配置邮件发送服务，因此密码重置功能为 **BLOCKED**。本服务没有伪造邮件、重置链接或重置 API；邮箱变更和密码恢复需待邮件服务合同及实现另行批准。
