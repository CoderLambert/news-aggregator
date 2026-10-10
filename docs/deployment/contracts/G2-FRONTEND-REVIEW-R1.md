# G2 capability generation race remediation

- Task ID / Depends on / Base HEAD / Goal：G2-FRONTEND-REVIEW-R1；Base 66a15233f1b95ff6bcdc64c372821bdf487e32f9；修复独立High发现的1P2旧mutation finally调用旧refresh导致accounts重新开启后身份持续匿名。
- Owned files / Read-only references：仅 frontend/src/context/AuthContext.tsx、frontend/tests/context/AuthContext.races.test.tsx。只读 G2-FRONTEND 合同与CapabilitiesContext。不是唯一工作者，不撤销其他编辑；domain worker仅scripts/docs。不得commit或派生。
- Decision frozen：refresh在开始时捕获layout更新的当前capability generation；canCommit必须同时验证该generation、epoch、sequence、mounted、accounts enabled、pending=0。mutation finally通过layout更新的最新refresh ref调度，不能调用旧闭包。旧login/register直接结果仍受既有epoch隔离，不能为恢复身份绕过fence；新fetchMe才确认当前cookie。保留CSRF轮换、队列、缓存清理、logout错误传播。
- Implementation steps：1定位现测试并增加分turn deferred复现；2新增generation及latest refresh refs并在layout effect同步；3refresh保存捕获generation且重复检查；4finally使用最新refresh；5运行定向与类型/lint。
- Acceptance tests：挂起login A→关闭accounts→重新开启并等待effect因pending不fetch→完成login A→随后fetchMe A；最终user A/loading false，期间不写旧直接身份。运行Auth races及capabilities测试、npm run typecheck、npm run lint，记录实际路径/命令/退出码。fresh HOME/source archive排除db并只overlay两ownedfiles，复用node_modules；不重复全套后端。
- Negative tests：旧fetchMe在关闭/重新开启后不能提交；pending期间无fetchMe；旧login直接结果不恢复身份；失败followup不假登录；既有CSRF/并发logout/缓存隔离回归保持。
- Forbidden：不修改后端/DB/CapabilitiesContext/其他组件、不读取.env/真实key/用户DB、不改变capability协议、不绕过csrf或身份fence；两次失败交主控。
- Return format：两paths/scoped diff、HEAD、复现及回归结果、测试数/命令/退出码/隔离日志路径，尚待High复审；返回final释放槽。
