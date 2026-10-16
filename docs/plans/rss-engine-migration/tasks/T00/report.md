# T00：完成报告

日期：2026-10-16。实验实现已交付，完整任务验收 **PARTIAL / BLOCKED**，不标 DONE。产品和生产均 NOT_RUN。

基线17d48915bbacd6a448578c64676a6dac4c2f263e，worktree `/tmp/newshub-rss-T00`，分支 `task/rss-T00-engine-contract`。本报告与实现同属任务原子提交，交付 SHA/推送结果由主调度按实际 Git 回执记录，避免自引用 SHA。PR/CI/独立评审未执行。

| 专项 | 实际证据 |
| --- | --- |
| A1 PASS | 真正空库 H=0；8个引擎条目3/3/2升序页；同cursor重放；H包含、裸before=H排除H；L=H空页；limit=0有界、1001拒绝；int64 H+1溢出离线拒绝 |
| A2 PASS | config-dump两个显式90；仅调整本次合成PG的created_at/published_at/read状态；91天read/unread删除并有2个tombstone；89天创建但200天发布保留；91天starred/shared保留 |
| A3 PASS | crawler=true创建得到version1；改变合成网页后普通refresh完成仍旧文；SDK fetch_entry_content返回version2但GET仍旧文；最小扩展update_content=true后独立客户端GET读到version2 |
| A4 PARTIAL | 独立guarded引擎/空库private=0；私网DNS、IPv4/IPv6环回、元数据IP明确private-network错误；file/ftp拒绝；HTTP503/坏XML不注册；Feed BasicAuth不带正文；跨主机跳转移除认证 |
| A4完整门禁BLOCKED | 缺受控公网HTTPS/DNS/TLS/网关端点；未证公网到私网跳转、DNS重绑定、认证网关禁跳转、同源跳转/完整日志错误凭据隔离。跨主机strip不是禁跳转证明 |

不可变制品见 [versions.json](../../../../../ops/rss/T00/versions.json)，资源边界与接口见 [README](../../../../../ops/rss/T00/README.md)。实际 Linux amd64、Docker29.7.2/Compose5.5.1、Miniflux2.3.3、PG17.6、SDK1.1.6；主机Python3.14.8，仓库Python3.12 CI兼容性仍未验证。测试服务器镜像Python3.12.12不能替代主机运行证据。

命令与结果：

- 拉取 miniflux/miniflux:2.3.3、postgres:17.6-alpine、python:3.12.12-alpine3.22 均退出0；Compose锁定真实返回digest，未用latest。
- 按tests.md建立独立venv安装测试依赖退出0；最终离线命令退出0：16 passed,13 deselected in0.01s（包含最小SDK的坏JSON/503反例）；git diff --check退出0。
- `/tmp/newshub-rss-t00-venv/bin/python ops/rss/T00/run_live.py` 最终有效运行退出0：13 passed,16 deselected in18.34s；项目newshub-rss-t00-a729a2af2709。
- 首轮Docker29 internal网络不发布随机宿主端口导致readiness失败；改为独立bridge网络后复验通过。不是上游API失败；未复用失败环境。
- teardown后仅该项目的ps为空，合成PG数据销毁；无用户数据库、现有服务、生产秘密、切源或部署操作。

仅修改自有实验/证据文件，未改应用模型、共享依赖、部署Compose或集成状态。T04可采用实测的SDK最小参数扩展及独立GET确认；T09依排他边界及全保留对账实现，不以published_at过滤。生产响应大小/DTO脱敏由T04，真实网关由T18继续验证。低ID晚提交/并发清理及重启恢复没有在本任务重复宣称通过。

主调度追加验证：集成72ab3a1上的测试代码在独立Python3.12.14环境 `/tmp/newshub-rss-t00-py312` 运行 `python ops/rss/T00/run_live.py`，真实13 passed / 18.49s（退出0）；日志 `/tmp/newshub-rss-t00-py312.log`。该结果补齐runner/SDK Python3.12兼容证据，不改变A4公网门禁。
