# 本地 NVIDIA GPU 向量编码

目标：在用户 RTX 5060 Ti 16GB 上用 CUDA 执行现有 MiniLM 向量编码，保持模型、384 维向量、归一化及搜索索引契约不变。

构建同版本 GPU 镜像：

```sh
docker build --target production \
  --build-arg RELEASE_SHA="$(git rev-parse HEAD)" \
  --build-arg TORCH_VERSION=2.14.1+cu130 \
  --build-arg TORCH_INDEX_URL=https://download.pytorch.org/whl/cu130 \
  -t newshub:gpu-cu130 .
```

默认构建仍是 CPU 版本。GPU 镜像首次下载 CUDA/cuDNN 依赖体积较大。CPU CI lock 不变；GPU 构建需另做实际硬件验证。

`EMBEDDING_DEVICE=cuda` 明确使用 CUDA，设备加载失败不自动退回 CPU；`cpu` 可显式回退，未设置时保持 SentenceTransformer 自动检测。加载日志包含实际 device。

标准部署叠加 `compose.gpu.prod.yaml`，仅为 app/indexer 开放 NVIDIA CDI 设备；前提是宿主已配置 NVIDIA Container Toolkit/CDI。不可因 CDI 未配置而重启共享 Docker daemon 或覆盖现有 daemon 配置。

当前机器的 CDI 未配置、非交互 sudo 不可用。可在指定本地容器使用显式 NVIDIA 字符设备与只读驱动库映射，避免修改宿主系统配置。该映射绑定当前驱动文件，驱动升级后应重新生成；通用 Compose overlay 不硬编码宿主驱动版本。

只改变计算设备，不启用原本关闭的语义索引、不启动全站重建、不清空向量库、不改变现有 Worker 锁与数据库访问。

验证要求：纯设备选择/模型单例/显式 CPU/CUDA 失败不降级的四项回归；真实 CUDA 张量计算；相同公开 MiniLM 模型的 CPU/GPU 编码维度、有限值、归一化与余弦一致性。真实编码验证使用合成短句和独立/只读公开模型缓存，不读取文章历史，不写站点 DB 或 Chroma。

回退：本地 app 恢复原镜像及服务配置；保留原 CPU 镜像和模型缓存。仓库设备配置可独立 revert，无数据库迁移。

2026-10-21 验证结果：Python 3.12 下四项设备回归通过；GPU Compose 合约解析通过。实际容器 PyTorch `2.14.1+cu130` / CUDA 13.0 检测到 RTX 5060 Ti、计算能力 12.0，编译架构包含 sm_120，CUDA 矩阵计算通过。离线公开模型对 96 条合成短句编码得到 96×384 有限归一化向量，与 CPU 余弦最小值为 1.0。预热后各 3 次样本，中位数 CPU 0.132 秒、GPU 0.018 秒；此结果仅代表该短句批量编码，不代表整站搜索或索引提速。

本地 GPU 镜像构建通过，复用当前应用镜像仅替换同版本 PyTorch 并打包本阶段 embedding 模块，既有 UI/服务挂载继续保留。完整 pytest、全量 CI、真实文章索引与用户语义搜索流程未运行；语义索引开关保持原值。
