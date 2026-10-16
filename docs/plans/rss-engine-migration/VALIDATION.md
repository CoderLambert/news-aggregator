# 修订规划的可重复静态校验

在规划分支仓库根运行，只读 Git/Markdown，不导入产品、不读业务库、不启动服务。检查固定代码基线对象，而非强迫 origin/main 永远不前进；若实际实施基线变化另行复核。

```bash
python3 - <<'PY'
from pathlib import Path
import re, hashlib, subprocess

root = Path("docs/plans/rss-engine-migration")
baseline = "878b69081f8d5b3ae965bcf1c855390b059caa33"
assert subprocess.check_output(["git", "rev-parse", baseline], text=True).strip() == baseline
assert hashlib.sha256((root/"ARCHITECTURE.md").read_bytes()).hexdigest() == "a4614cd812d5e0d66a9211e88ecf72500513d0ccafce3aeb046633f2abee99e1"
tasks = {}
for line in (root/"TASKS.md").read_text().splitlines():
    match = re.match(r"\| \[(T\d\d)\]\(tasks/[^)]+\) \| (.*?) \| (.*?) \| NOT_STARTED \|$", line)
    if match:
        tasks[match[1]] = re.findall(r"T\d\d", match[3])
assert len(tasks) == 26, len(tasks)
aliases = {}
for folder in sorted((root/"tasks").iterdir()):
    if not folder.is_dir(): continue
    for name in ("task.md", "tests.md", "report.md"):
        assert (folder/name).is_file(), (folder, name)
    task_text = (folder/"task.md").read_text()
    alias = re.search(r"MERGED_INTO (T\d\d)", task_text)
    if alias:
        aliases[folder.name] = alias[1]
        assert alias[1] in tasks and folder.name not in tasks
        assert f"| [{folder.name}](tasks/{folder.name}/task.md) | {alias[1]}" in (root/"TASKS.md").read_text()
        for name in ("tests.md", "report.md"):
            assert f"MERGED_INTO {alias[1]}" in (folder/name).read_text()
    else:
        assert folder.name in tasks, folder.name
        dependency_text = re.search(r"集成前置：(.*?)。", task_text)[1]
        assert set(re.findall(r"T\d\d", dependency_text)) == set(tasks[folder.name]), folder.name
        assert "NOT_RUN" in (folder/"tests.md").read_text()
        assert "NOT_STARTED" in (folder/"report.md").read_text()
    assert "NOT_RUN" in (folder/"report.md").read_text()
assert len(aliases) == 11, aliases
assert set(tasks) | set(aliases) == {f"T{i:02d}" for i in range(37)}
active, seen = set(), set()
def visit(task):
    assert task in tasks, task
    assert task not in active, ("cycle", task)
    if task in seen: return
    active.add(task)
    for dep in tasks[task]: visit(dep)
    active.remove(task); seen.add(task)
for task in tasks: visit(task)
expected = {(dep, task) for task, deps in tasks.items() for dep in deps}
actual = set(re.findall(r"(T\d\d) --> (T\d\d)", (root/"DEPENDENCIES.md").read_text()))
assert expected == actual, expected ^ actual
links = 0
for file in root.rglob("*.md"):
    document = re.sub(r"```.*?```", "", file.read_text(), flags=re.S)
    for target in re.findall(r"\]\(([^)]+)\)", document):
        if target.startswith(("https://", "http://", "mailto:", "#")): continue
        relative, _, anchor = target.partition("#")
        destination = file.parent/relative
        assert destination.exists(), (file, target)
        if re.fullmatch(r"c\d\d", anchor):
            assert f"## {anchor.upper()}" in destination.read_text(), (file, target)
        links += 1
changed = set()
for args in (["git", "diff", baseline, "--name-only"],
             ["git", "diff", "--name-only"],
             ["git", "diff", "--cached", "--name-only"],
             ["git", "ls-files", "--others", "--exclude-standard"]):
    changed.update(subprocess.check_output(args, text=True).splitlines())
assert all(p.startswith(str(root)+"/") and p.endswith(".md") for p in changed), changed
for args in (["git", "diff", "--check"], ["git", "diff", "--cached", "--check"]):
    assert subprocess.run(args).returncode == 0
print(f"PASS: {len(tasks)} active units; {len(aliases)} merged aliases; 111 task documents; {len(expected)} DAG edges; {links} local links; unchanged architecture hash; documentation-only scope.")
print("Dependency-free units: " + ", ".join(t for t, deps in tasks.items() if not deps))
print("Product/runtime checks: NOT_RUN; this is documentation validation only.")
PY
```

另外审查新增语义是否覆盖：共享绑定切换/主写令牌、public/personal 停更、政策更新、兼容字段译文、元数据映射、OPML 确认、开发/集成/生产分层。文本/图检查不能证明产品行为或替代实现评审。

静态检查不运行产品 CI、真实引擎/来源、浏览器、迁移恢复和性能测试；这些继续按 [验收矩阵](ACCEPTANCE-MATRIX.md) 标 NOT_RUN。PR 的 CI 状态以 GitHub 当前结果为准，不将本地文档检查冒充全部 CI。
