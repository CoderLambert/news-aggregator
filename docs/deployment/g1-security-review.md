# G1 安全审核记录

审查者：原生 `security_reviewer` 角色，固定 Sol High；范围：基线 `8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd` 至 `d220f006445986756f86032bd47afeb9764475fc` 的完整 G1 相关 diff 和调用链。仅静态只读，不运行应用或测试，不读取用户数据库与真实凭据。

首轮结论：**4 项 P1，尚未通过**。实施者的测试证据与审查者的静态结论分别记录，不能相互代替。

| 编号 | 位置 | 触发与影响 | 必须补充的验证 |
| --- | --- | --- | --- |
| P1-1 | export-static.sh:178/212/229 | stage0700、asset0600 发布后异UID Nginx不能读，页面403 | umask077及真实Nginx worker读首页、JS/CSS、延迟chunk |
| P1-2 | backup.sh:120–124 | entrypoint重复python必失败；host600 manifest对UID10001不可读 | 真production UID/临时卷/host600 manifest备份、校验、恢复 |
| P1-3 | release_manifest.py:150 | 共享历史assets加入当前release哈希，第二次发布及旧版本rollback失配 | A/B不同chunk连续导出，两个版本各自hash匹配，旧chunk保留 |
| P1-4 | production-containers.md:17 | 直接compose up升级绕过停写、最新备份和维护窗口 | 文档只指受控入口，真实临时project停写→备份→迁移→健康 |
| P2-1 | CapabilitiesContext.tsx:71 | full成功后重取失败仍用旧私有能力 | full→failed/非法schema→success的QueryClient实际测试 |
| P2-2 | local_domain_acceptance.py:145 | health豁免HTTPS跳转，200不能证明secure scheme | 改非豁免API及Fake上游头回显；无观测项明确NOT_RUN |
| P2-3 | sqlite_snapshot.py:449 | 合法prior artifact可能是另库/旧快照，不能证明覆盖前数据已保存 | 持锁停写时完整逻辑schema/rows对应比较，错库/新row负例 |

主Agent审核前后核对：HEAD相同、120项文件hash相同、相关diff SHA256相同（`d5227323dda25405f5d95b797174291fa585266d012f1782fef039c124b6f70b`）。用户运行中SQLite排除，不因其后台修改误判审查者写入。预核对文件 `/tmp/newshub-g1-audit-pre-d220f00.json`。

整改合同：G1-RELEASE-R1、G1-CAPABILITIES-R1；代理验收P2按原ownership补充。整改结果和复审版本待实际完成后追加，不预填PASS。

## R1 增量复审
候选0df4b1e3909da96caa54cbc32af1ecd1472bd0d7，相对已审d220f00。原4P1/3P2静态整改闭环，但新增P1：每release/assets真目录后Nginx仍继承current root，旧chunk HTTP404。High仅复审变化及调用链，仍只读；前后23项文件hash/HEAD/diff均相同（37750611d20e163591ccc31c52f1d7f5ad251a3e37829368767fe81bf95c53ac）。合同G1-NGINX-R2要求两个assets块显式shared root。

主Agent实际隔离Nginx另检出未引用regex花括号的语法问题：nginx -t退出1，line76 unknown directive；Luna已引用两个regex，真实nginx -t退出0。修复后的真实scratch静态fixture验收报告/tmp/newshub-static-runtime-r2-asp3ztzb/report.json：umask077导出A/B、自身文件/hash保留、导出者UID1000和Nginx worker UID101、正式模板TLS证书校验首页/旧新chunk200、缺chunk404无immutable、静态切回A后二版chunk仍200、精确资源清理均PASS。此项仅静态fixture，不替代production app/DB/rollback CLI或完整浏览器验收。
