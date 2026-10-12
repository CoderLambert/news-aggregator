# G1-NGINX-R2 共享资产路由整改

- Task ID / Depends on / Base HEAD / Goal：NH-PUB-02-R2；High增量审查0df4b1e3909da96caa54cbc32af1ecd1472bd0d7；修复真实release/assets布局后旧chunk HTTP不可达。
- Owned files / Read-only references：仅deploy/nginx/news.lambert.host.conf及scripts/deploy/tests/test_nginx_templates.py。只读export-static/release_manifest/local-domain合同/ADR020/GOAL；共用树保留他人，不派生。
- Decision frozen：两个assets location（hash regex与/ assets prefix）均显式root /srv/newshub，使$uri /assets/x映射共享/srv/newshub/assets/x；全站root仍/srv/newshub/current。不得用alias捕获不完整的regex或改API、TLS、SSE、缓存策略。hash200 immutable一年，404无immutable；非hash no-cache、缺失404。per-release硬链接/hash保留，不改export布局。
- Implementation steps：1读现两location继承root触发；2各加显式共享root；3模板测试分别确认两个块根目录、缺失404/cache不变；4定向测试并返回；真实A/B HTTP由主Agent独立验证，不先声称PASS。
- Acceptance tests：PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest scripts/deploy/tests/test_nginx_templates.py -q；git diff --check。后续真实Nginx A→B→A index/旧新chunk200、缺资源404不immutable，以及两release自身hash仍匹配；保存真实退出/报告。
- Negative tests：不全站root改共享、不API落SPA、不404immutable、不从current/assets遗漏旧hash、不改变正式9527上游。
- Forbidden：只改两文件、无生产/系统Nginx/证书操作、无费用/OAuth/用户DB，不commit/派生，不放宽TLS。
- Return format：paths/diff/HEAD、命令exit/test数、实际HTTP仍NOT_RUN；build在后台继续，改这两文件不影响其既捕获上下文。

## 实际语法检查补充
主Agent实际nginx -t退出1，line76 unknown directive "8}-[0-9A-Fa-f]"；原UUID与hash资源regex的未引用花括号被Nginx当配置delimiter。两条含量词花括号的完整regex必须用引号包围，pattern语义不变。模板测试block parser须跳过引号内量词，真实独立network-none Nginx+临时SAN证书检查必需退出0，不能只以pytest代替语法有效。

R2 High无P0/P1，另发现generic static regex抢先匹配非hash/assets。冻结其negative lookahead排除api/和assets/（^/(?!api/|assets/)），不把assets prefix改^~（否则跳过hash immutable规则）。新增精确模板断言，真实共享目录独有非hashSVG/font200/no-cache、missing404/hash200immutable由主Agent验证。
