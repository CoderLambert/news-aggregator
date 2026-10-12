# G1-CAPABILITIES-R1 失败重取保守关闭合同

- Task ID / Depends on / Base HEAD / Goal：NH-PUB-10-R1；High审查d220f00，派发给定HEAD；已成功full后重取失败也关闭私人功能，不沿用stale权限。
- Owned files / Read-only references：frontend/src/context/CapabilitiesContext.tsx、frontend/tests/context/CapabilitiesContext.test.tsx（现文件若不同先报或新增CapabilitiesContext.refetch.test.tsx）。只读AuthContext/FeatureRoute/API解析/GOAL和react-best-practices SKILL.md；共用树保留他人，不派生。
- Decision frozen：query.isError true时capabilities必须FAIL_CLOSED_CAPABILITIES，即使query.data为旧full；isPending保留loading，failed来自isError。下一次成功重取才恢复服务端有效能力。不能全局清公共news查询，不能增加默认full/test-only绕过。请求非法schema在fetchCapabilities解析器已throw，同样失败关闭。无新API/缓存架构/用户状态字段。
- Implementation steps：1读现context/query测试；2最小条件修复；3真实QueryClient从full成功到强制refetchreject/非法schema，再成功readonly或full；4技能检查与定向type/lint/test。
- Acceptance tests：cd frontend && npm run test:run -- tests/context/CapabilitiesContext.refetch.test.tsx（实际existing测试路径另列）；npm run typecheck && npm run lint。assert重取失败query cache仍有旧full但provider所有private=false/reason capabilities_unavailable/news与keyword可读；恢复成功才开启、retryfalse网络不无限重试。
- Negative tests：不是只测首次失败；不能删缓存模拟问题消失；坏响应也失败关闭，missing provider原保守默认不变；无需收费/真实网络。
- Forbidden：不改Auth/P2以外业务或backend，不commit/派生，不升级包。两次失败交Sol。
- Return format：paths/diff/HEAD、命令exit/test数、full→failed→success证据；不自行称G1复审通过。
