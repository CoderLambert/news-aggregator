# 规划文档的可重复静态校验

以下只检查文档、Git引用和文件范围，不导入产品、访问数据库或启动服务。在规划分支仓库根执行；基线变化应重新审计，不能只修改常量使检查变绿。

```bash
python3 - <<'PY'
from pathlib import Path
import re, hashlib, subprocess
root = Path("docs/plans/rss-engine-migration")
baseline = "878b69081f8d5b3ae965bcf1c855390b059caa33"
assert subprocess.check_output(["git", "rev-parse", "origin/main"], text=True).strip() == baseline
assert hashlib.sha256((root/"ARCHITECTURE.md").read_bytes()).hexdigest() == "a4614cd812d5e0d66a9211e88ecf72500513d0ccafce3aeb046633f2abee99e1"
tasks = {}
for line in (root/"TASKS.md").read_text().splitlines():
    match = re.match(r"\| \[(T\d\d)\].*? \| (.*?) \| (.*?) \|", line)
    if match:
        tasks[match[1]] = re.findall(r"T\d\d", match[3])
assert len(tasks) == 37, len(tasks)
assert set(tasks) == {f"T{i:02d}" for i in range(37)}
for task, deps in tasks.items():
    assert all(dep in tasks for dep in deps), (task, deps)
    for name in ("task.md", "tests.md", "report.md"):
        assert (root/"tasks"/task/name).is_file(), (task, name)
    text = (root/"tasks"/task/"task.md").read_text()
    dependency_text = re.search(r"前置：(.*?)。", text)[1]
    assert set(re.findall(r"T\d\d", dependency_text)) == set(deps), task
    assert "NOT_RUN" in (root/"tasks"/task/"report.md").read_text(), task
active, seen = set(), set()
def visit(task):
    assert task not in active, ("cycle", task)
    if task in seen: return
    active.add(task)
    for dep in tasks[task]: visit(dep)
    active.remove(task); seen.add(task)
for task in tasks: visit(task)
expected_edges = {(dep, task) for task, deps in tasks.items() for dep in deps}
actual_edges = set(re.findall(r"(T\d\d) --> (T\d\d)", (root/"DEPENDENCIES.md").read_text()))
assert expected_edges == actual_edges, (expected_edges ^ actual_edges)
local_links = 0
for file in root.rglob("*.md"):
    for target in re.findall(r"\]\(([^)]+)\)", file.read_text()):
        if target.startswith(("https://", "http://", "mailto:", "#")): continue
        relative, _, anchor = target.partition("#")
        destination = file.parent/relative
        assert destination.exists(), (file, target)
        if re.fullmatch(r"c\d\d", anchor):
            assert f"## {anchor.upper()}" in destination.read_text(), (file, target)
        local_links += 1
changed = subprocess.check_output(["git", "diff", "--cached", "--name-only"], text=True).splitlines()
untracked = subprocess.check_output(["git", "ls-files", "--others", "--exclude-standard"], text=True).splitlines()
assert all(path.startswith(str(root)+"/") and path.endswith(".md") for path in changed + untracked)
assert subprocess.run(["git", "diff", "--check"]).returncode == 0
assert subprocess.run(["git", "diff", "--cached", "--check"]).returncode == 0
print(f"PASS: {len(tasks)} main tasks; 111 task documents; DAG/table/task dependencies agree; no cycles; {local_links} local links valid; canonical source hash and documentation-only scope valid.")
print("Initial ready set after G0: " + ", ".join(task for task, deps in tasks.items() if not deps))
PY
```

产品测试、接口运行、恢复、浏览器和来源质量不在此校验范围；这些仍按 ACCEPTANCE-MATRIX.md 保持NOT_RUN/BLOCKED。
