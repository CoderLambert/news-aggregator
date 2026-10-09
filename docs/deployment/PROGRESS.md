# 执行证据与下一任务

## 2026-10-10 P00 / 重启目录确认
- 当前合同已移动至根 GOAL.md；保留用户 START_HERE.md、.codex 和参考文档。
- git fetch origin 退出0；origin/main 与 HEAD：8c2823e1fcf8cbea38e9bb7c4e98a33232025fbd。计划旧基线 80d28756f1236347d104e69a76c86e6d707b1376 已过时。
- 工作分支 feat/news-public-readiness。backend/db.sqlite3 是用户已有未提交修改，未覆盖/迁移/提交；用户其他未追踪文档保留。
- 已读 README、docs/startup.md、compose.yaml、Docker/Waitress/entrypoint、settings、API urls/权限、测试命令、Provider 路由、研究 CSRF、Chat 归属及 Mermaid；具体发现见 ARCHITECTURE。
- codex --version=0.161.0；features list goals/multi_agent=true（退出0）；原生工具发现所需 implementer 与 security_reviewer 固定角色。子 Agent 尚未派发，不将配置文件存在等同模型实测。
- Docker info 退出0，daemon 29.7.2。Python venv/Node依赖存在；dig/nginx 缺失。公网 DNS/证书/真机只读检查 NOT_RUN，生产写入与真实 API/OAuth EXTERNAL_BLOCKED。
- P00 状态 TESTED（本地盘点与架构/任务方案），不是部署成功；功能测试、check --deploy、镜像/恢复、安全里程碑审核均 NOT_RUN。
- 下一任务：NH-PUB-01 只读预检脚本与离线负例；同时主 Agent 冻结 NH-PUB-03 配置/代理/探针完整合同，再派发实现。G1→G2→G3→条件G4按合同推进。
