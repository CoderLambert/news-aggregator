# S05-BACKEND-R1 有证据整改合同

- Task ID / Depends on / Base HEAD / Goal：S05-BACKEND-R1；原S05-BACKEND候选；d7b247b8149625d6a636832616ad9dccd5e35362+candidate；修正总deadline对DNS/慢HTTP头缺口。
- Owned files：仅safe_http.py/test_safe_http.py（完整路径backend/api/services/article_fetcher/与backend/api/tests/）；其余原S05文件只读。
- Decision frozen：ADR012（固定2线程/2pending/立即拒绝busy/future done释放/DNS超时不shutdown等待；同deadline传每跳；DeadlineFile包buffered.read1并socketFacade处理状态行/headers/body；wire2MiB+64KiB/body2MiB；仅GET无data）。
- Implementation steps：1复核主AgentslowDNS实证；2实现有界DNS和剩余deadline；3读取包装器/缓冲/每次源read1期限；4补DNS Event阻塞/饱和释放、慢header/status和GET负例；5跑原五file回归。
- Acceptance tests：原S05五file pytest命令；DNS调用线程在限时内返回、底层pending最多2、释放恢复；正常完整HTTP解析无丢字节、原40功能负例仍PASS。
- Negative tests：旧slowDNS timeout0.01不得等0.1才返回；第三未完成DNS立即busy；fakeClock慢status/header不得超过deadline成功；PUT/POST/request.data拒绝不连接；原DNS重绑定/SSRF/TLS/redirect/byte限额不放宽。
- Forbidden：不编辑其他文件/公开资源/Provider/数据库/前端，不真实联网，不扩展线程池/协议/SSL、不commit/再派生。两次证据修复失败交Sol。
- Return format：TaskID、两owned diff、命令exit/测试数、slowDNS与headers负例实证、HEAD、遗留阻塞。

## 主Agent引用搜索补充
API/command现测试test_provider_comparison_api_command.py:16还引用已移除comparison.socket。授权owned扩展此文件，仅把mock目标改safe_http.socket.getaddrinfo/合法family/type/proto，保留原业务断言；R1验收追加此file，不为测试新增死socket兼容别名。
