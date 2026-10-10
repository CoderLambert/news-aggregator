# G1-BUILD-CACHE-PROBE 有界本地依赖层诊断

- Task ID / Depends on / Base HEAD / Goal：NH-PUB-04-cache-probe；G1资源下载根因，Base22214b3a7a4bc52bde9c5149fb74f7bee52a9a9e；验证新增early HOME ENV使本地旧依赖层cache失配。不是更换依赖或复用旧应用数据。
- Owned files / Read-only references：仅Dockerfile（先保持原文件副本，成功才保留最小变动）；可在/tmp保存probe Dockerfile/log，禁止其他源码修改。只读git基线Dockerfile、.dockerignore/requirements/GOAL；共用树保留他人，不派生。
- Decision frozen：原基线early ENV仅PYTHONDONTWRITEBYTECODE/PYTHONUNBUFFERED/PYTHONPATH/HF_HOME；新增HOME=/root改变pip父层cache key。仅将HOME=/root从early ENV移到pip RUN之后、COPY backend之前，最终runtime-base/development HOME仍root，production HOME仍/home/newshub；pip作为root未显式HOME时pwd展开仍/root，不改任何命令/版本/index/源码排除/user/target。无需--cache-from（已证实旧命令尝试registry pull授权失败，不能再重试该import）。用正式Dockerfile/production target/给定SHA和--networkhost、独立newshub:cache-home-probe-SHA构建，最多90秒诊断；pip层若CACHED则允许完成真实image/UID/revision检查，若进入Collecting/download立即取消仅probe。正在运行的原7f build由domain worker控制，不停止它。
local oldimage只读已核对requirements SHA完全相同、Django6.1.2/DRF3.18.3/torch2.14.1+cpu/OpenAI3.26.1/Chroma1.5.9/SentenceTransformers6.1.0、Python3.12.15，不copy旧image应用/env/DB/home，也不把它直接当production。probe若miss还原仅本任务HOME移动（其它人变更不得撤销）并如实返回NOT_HIT；不得无限试其它cache策略。
- Implementation steps：1比原/当前ENV位置，保留当前Dockerfile；2最小HOME移动；3bounded正常Docker build probe；4匹配hit实际image User/revision，miss取消并恢复自有patch；5离线静态测试/范围核验；6返回完整证据。
- Acceptance tests：PYTHONPATH=backend:crawler RUN_MAIN=true backend/venv/bin/python -m pytest tests/backend/test_docker_context.py -q（仅若保留变更）；cache日志明确pip层CACHED或NOT_HIT，成功image UID10001/revision等SHA，runtime环境HOMEroot/prodhome并未改变；git diff --check。
- Negative tests：registry importer错误不得当cache miss层内容证明；不直接FROM旧应用最终image、不读旧env/db/token、无新provider/API费、不取消domain原build、失配90s停止还原。
- Forbidden：不改requirements/pipindex/代理/daemon/生产、无复制旧usr/local/source数据捷径、不commit/派生，不无证据更改方案。
- Return format：paths/diff/HEAD、日志/timeout/exit、cache明确证据与是否还原、成功imageID/User/revision或NOT_HIT；正常完整生产runtime尚待验收，不提前PASS。
