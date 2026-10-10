# G1 volume shim argv normalization

- Task ID / Depends on / Base HEAD / Goal：G1-VOLUME-ARGV-R3；Base a334a795a56e5141b4f88104db316684fca60aa8，依赖已完成45单测runner；实际Docker metadata exit125证实重复network参数，最小修复后完成真实备份恢复验收。
- Owned files / Read-only references：仅 scripts/deploy/volume_acceptance.py 与 scripts/deploy/tests/test_volume_acceptance.py；只读原G1-VOLUME-RUNTIME合同与 /tmp/newshub-volume-1288c0b5-ff9cc7d78a/diagnostic/result.json。自己/tmp与自己随机owner资源可用；不是唯一工作者，不撤销G2/其他改动。
- Decision frozen：run/create先用已有_image_index确定image位置，只对image前Docker options解析。逐个验证所有--network/--network=及--pull/--pull=；值分别只允许none/never，包括重复mixed形式中任一恶意值都拒绝。删除所有合法原network/pull选项及其值，再注入恰好一次--network=none/--pull=never。image及其后命令argv逐字不变，不误删Python代码/command参数中同名字符串。其他所有资源/user/mount/label/cleanup策略不变。
- Implementation steps：1复核metadata重复参数；2按上述边界normalize且验证所有值；3新增run/create absent/split/equal/mixed duplicate回归与恶意重复拒绝、image后原样保留；4原45测试全部通过；5回传等主控提交/增量审核后用新git archive helper及1288实际image（app源码相同）重跑原volume合同；6真实命令失败两次即证据上报不无限试错。
- Acceptance tests：PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest scripts/deploy/tests/test_volume_acceptance.py -q；py_compile两文件；重写结果image前network/pull各一次。实际runtime只在主控确认审核后执行，报告包含真实CLI fixture/backup/restore/cleanup。
- Negative tests：重复中host/always任意顺序均拒绝，缺值拒绝；image后--network/--pull作为程序参数完全保留；原拒绝外部mount/ports/root/不属于本次资源仍通过。失败报告不覆盖，用户DB不读取，19527/9527不操作。
- Forbidden：不改Dockerfile/依赖/生产业务/任何其他source，不commit/不派生；不真实公网/收费/OAuth/用户DB；不得仅避开metadata命令掩盖shim根因，不跳过真实恢复。
- Return format：两paths/diff、单测数/exit与HEAD；初轮仅源码结果，实际runner另给image SHA/report/真实checks/cleanup，不能把mock当runtime PASS。
