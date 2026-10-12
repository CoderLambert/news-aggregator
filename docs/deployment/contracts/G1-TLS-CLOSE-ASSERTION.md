# G1 HTTPS 444 curl assertion

- Task ID / Depends on / Base HEAD / Goal：G1-TLS-CLOSE-ASSERTION；Base c10378f，Sol实际CA验证的news HTTPS200后，未知Host返回Nginx444关闭连接，curl8.10.1实际exit56/HTTP_CODE000 SSL_read SSL_ERROR_SYSCALL；既有验收只接受52产生假失败，最小修复HTTPS断言。
- Owned files / Read-only references：仅 scripts/deploy/local_domain_acceptance.py 与 scripts/deploy/tests/test_local_domain_acceptance.py；只读 /tmp/newshub-nginx-coexist-primary-g3kzzm1e/report.json、现NGINX模板。不是唯一工作者，不撤销Chat/Accounts/runner/NGINX改动。自己的/tmp可用。
- Decision frozen：提取纯闭连接判定helper，HTTP仅52且status000；HTTPS允许52或56且status000，stdout不得有任何HTTP/响应状态行。禁止接受TLS握手/证书错误35/60、timeout28、connect7或任意nonzero；禁止接受200/403或有HTTP响应。实际HTTPS未知Host检查必须在同SNI/CA成功的正常HTTPS请求后执行，现有顺序保留；HTTP逻辑不放宽，无-k/insecure，不改其他验收/应用。
- Implementation steps：1复核实际curl56证据；2添加helper并仅接入已有unknown HTTP/HTTPS判断；3参数化真实输出形态的正负回归；4定向测试/compile/scoped diff-check；5回传等待主控冻结SHA后正式domain smoke。
- Acceptance tests：PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest scripts/deploy/tests/test_local_domain_acceptance.py -q；52/000 HTTP与HTTPS、56/000无HTTP响应HTTPS通过。实际完整domain由主控确认SHA后按原合同执行。
- Negative tests：56 HTTP拒绝；35/60/28/7均拒绝即便000；52/56带HTTP状态行拒绝；200/403正常响应拒绝。原真实secureCookie/代理头/SSE3测试保留。
- Forbidden：不commit/派生/改非owned文件；不放宽证书验证、不改nginx/安全规则、无系统hosts/CA/公网/收费/用户DB；测试失败两次给证据。
- Return format：两paths/diff、test数/exit/HEAD、编译与diff-check、完整runtime NOT_RUN；不以helper单测代替域名验收。
