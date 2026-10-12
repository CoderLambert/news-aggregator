# G1-VOLUME-RUNTIME-R2 审查两项P2整改

- Task ID / Depends on / Base HEAD / Goal：11/12-volume-R2；High只读08838fe增量审查，派发HEAD以主控消息为准；修复超时intent清理与report目录竞争，不扩展runner范围。
- Owned files / Read-only references：仅scripts/deploy/volume_acceptance.py与scripts/deploy/tests/test_volume_acceptance.py；只读原runtime合同/正式CLI。共用树不撤销他人、不派生。
- Decision frozen：cleanup验证owner label==本次token、resolve实际ID合法后，**先fsync写对应name+已验证ID台账**，再走原shim rm ID；只有已验证owner才允许补ID，错label拒绝且不删除。台账空ID且container真实存在的超时情形必须可精确清理，无全局扫描/prune。
run在_prepare_workspace尚未成功mkdir并持有自身workspace时，不写report/ledger/log/cleanup文件；竞争创建report目录或最终组件symlink导致mkdir失败，应返回非0、原内容/permissions/路径完全不变。finally _save_report只在workspace_created且仍自有真实目录时执行，避免不属于自己的路径被覆盖；不能靠先删已有目录解决。已有私有文件权限与成功流程保留。
- Implementation steps：1复现两个High路径；2补已验证ID台账；3guard workspace ownership写报告；4新增真实shim策略cleanup timeoutID、wronglabel不删、目录/symlink竞争sentinel不变tests；5原40+新增定向pytest/compile/diff-check；6返回供主控增量复审。
- Acceptance tests：PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest scripts/deploy/tests/test_volume_acceptance.py -q；py_compile两owned文件；完整fakecleanup调用必须实际经过secure_docker_argv，不只断言拼字符串。没有正式production image，本任务Docker runtime NOT_RUN。
- Negative tests：未验证label不能补ID/删除；空ID且存在ownedcontainer清理成功；daemoninspect异常cleanupFAIL；mkdir竞争/变symlink不得读写或覆盖sentinel、chmod，不Docker调用；原安全mount/network/pull/UID拒绝保留。
- Forbidden：不改formalCLI/其他源码，不prune/userDB/WAL/生产/公网/收费/OAuth，不commit/派生；两次失败交Sol，不放松owner检查。
- Return format：paths/diff/HEAD、pytestexit/数、实际策略cleanup与原report不变证据、runtimeNOT_RUN；复审由主控安排。
