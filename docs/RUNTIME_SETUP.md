# 在新目录恢复视觉演示

本页覆盖 SiteWatch PPE 视频检测和可选的 Qwen3-VL 区域第二意见。资源由 `config/runtime-assets.json` 固定 SHA256 和字节数，环境由 `config/bootstrap-ppe.txt`、`config/bootstrap-full.txt` 固定直接依赖版本。旧库存/物料应用的环境不在本轮交付范围。

## 1. 目标机器

可移植基线为 **Linux x86_64、Python 3.12、glibc ≥ 2.28**，推荐 Ubuntu 24.04 / WSL2。系统需提供 `venv`、OpenCV 的 `libGL.so.1` / GLib，例如 Ubuntu 使用：

```bash
sudo apt-get install python3.12-venv libgl1 libglib2.0-0
python3.12 --version
```

`ppe` 使用官方 CPU Torch，无需 NVIDIA GPU。`full` 使用官方 CUDA 12.8 wheel，需要工作正常的 `nvidia-smi`、NVIDIA 驱动 ≥ 570.26、GPU 计算能力 ≥ 7.0，安装后实际执行 CUDA/NF4 小算子检查。PyTorch wheel 自带所需 CUDA runtime；目标机驱动、显存及实际模型推理仍须验证。脚本不加载模型，安装成功也不代表 Qwen 在某块显卡上可完成业务推理。

Torch/torchvision 的迁移配对为 **2.8.0 / 0.23.0**，CPU 与 cu128 分开从[官方索引](https://pytorch.org/get-started/previous-versions/)安装。历史本机记录中的 Torch 2.14.0 / torchvision 0.29.2 不作为迁移版本。Transformers 保留 **4.57.6**，因为现有视频适配对该版本有明确检查。所有直接依赖均通过[官方 PyPI 元数据](https://pypi.org/)核对发布与 Linux/Python 3.12 wheel；CUDA/bnb 要求见 [bnb 0.49.2 安装说明](https://huggingface.co/docs/bitsandbytes/v0.49.2/installation)与 [CUDA 12.8 发布说明](https://docs.nvidia.com/cuda/archive/12.8.0/cuda-toolkit-release-notes/index.html)。

## 2. 先查看资源与空间

在新 clone 的仓库根目录运行；资源脚本只用 Python 标准库：

```bash
python3.12 scripts/restore_runtime_assets.py --profile ppe --plan
python3.12 scripts/bootstrap_runtime.py --profile ppe --plan
```

默认 profile 是 `full`。`ppe` 选 PPE 所需资源，`full` 额外选 Qwen；具体选项以清单中的 `profiles` 为准。`--include-training` 额外恢复可选的训练相关资源；当前交接仅含已保存的 RF100 **90 张测试图及 90 份标签子集**，没有提供完整训练/验证集，也不构成新增训练结果。

资源计划会列出缺少的文件、缺少输出字节和下载字节上限。网络下载缓存保留在 `.runtime/asset-downloads/`：大权重按有序分片下载，逐片验证后流式拼接为唯一目标权重，不创建另一个完整权重副本。空间至少预留缺少的目标文件与下载缓存总量；计划还给出保守的最大单文件临时空间说明。恢复成功后再次执行会哈希确认已有文件，并跳过对应下载。下载中断可重试；完成且有效的分片会复用，未完成临时文件会删除。

## 3. 恢复原字节

```bash
python3.12 scripts/restore_runtime_assets.py --profile ppe
python3.12 scripts/restore_runtime_assets.py --profile ppe --verify-only
```

需要 Qwen 时把 `--profile ppe` 改为 `--profile full`。脚本从固定 GitHub Release 恢复模型与可分发素材；受原站独立分发要求约束的 Pexels 原片从清单中的官方地址下载，并使用其中规定的 User-Agent / Referer。不会换用低清文件。

ZIP 只允许白名单中的原相对路径；权重分片需同时通过每片与拼接后总 SHA256。路径穿越、符号链接、归档额外成员、已有异内容文件均会拒绝；脚本不提供覆盖开关。若现有文件不同，先人工核对并移到安全位置，再重试。失败不会生成伪完成的目标文件；此前已验证恢复的其他文件可留作下次复用。

离线时将 Release ZIP、全部分片和按官方地址取得的外部原片放进一个目录：

```bash
python3.12 scripts/restore_runtime_assets.py --profile full --assets-dir /path/to/offline-assets
```

ZIP / 分片使用清单 `assets[].name`；外部原片使用目标 `path` 的 basename。同名输入可统一命名为 `<sha256>-<basename>`，脚本优先查此名称。离线输入原地读取，不复制到下载缓存；缺少输入即报错，不连接网络。`--manifest PATH` 与 `--project-root PATH` 可指定清单和新目标目录；目标根目录须已存在。

恢复后可先执行 `--verify-only`，再手工删除本仓库的 `.runtime/asset-downloads/` 释放缓存；后续如全部目标仍完整，不需要缓存即可再次验证/运行。请勿把 `downloads/` 当成缓存删除，那里包含业务原片、模型和训练输入。

## 4. 安装仓库内环境

```bash
python3.12 scripts/bootstrap_runtime.py --profile ppe
```

只在本仓库 `.runtime/portable-env/` 安装依赖，清除安装进程的 `PYTHONPATH` / `PYTHONHOME` 等注入，禁用用户和系统 site-packages。pip 缓存放在 `.runtime/pip-cache/`；磁盘紧张时追加 `--no-cache-dir` 禁用持久 wheel 缓存，安装期间仍需临时下载空间。PPE 环境解压占用粗估 1.5–2GB，建议为环境预留 2.5GB，再另计资源和安装临时空间；实际占用以目标机安装为准。直接依赖固定版本，实际解析的间接依赖与来源保存在环境内 `*-install-report.json`。安装结束执行 `pip check`、隔离检查、CPU tensor 与 torchvision NMS 算子检查。

现有管理器通过仓库内相对链接使用该共享环境：

| 路径 | 用途 |
| --- | --- |
| `.runtime/sitewatch-env/bin/python` | PPE 管理器；始终提供 |
| `vision/.venv/bin/python` | Qwen 管理器；仅 full 提供 |

新安装不再引用旧机器的 `/home/meg` 或其他项目的 `.venv`。任何已有的非本脚本管理的环境都会被拒绝，脚本不会自动删除或覆盖。若在旧 clone 使用，请先人工确认并移动这些旧环境再安装。

同一命令可以重跑：归属标记记录 `installing/failed/ready`，失败保留本仓库环境供重试，成功且配置未变时仅重做验证。`ppe` 可升级为 `full`：

```bash
python3.12 scripts/bootstrap_runtime.py --profile full --plan
python3.12 scripts/bootstrap_runtime.py --profile full
```

Full 会把共享环境的 CPU Torch 换成 cu128 构建；PPE 管理器仍明确在 CPU 运行。开始安装 full 后，`--profile ppe` 继续校验 full 环境，避免静默降级。若确需回到纯 CPU，先停止本项目服务，人工将 `.runtime/portable-env/` 改名保留，再以 `ppe` 重建；两个已有相对链接可复用，vision 链接此时不代表 Qwen 依赖齐全。

## 5. 启动和目标机验收

为避免调用 shell 注入其他 Python 路径，启动时清除相关变量：

```bash
env -u PYTHONPATH -u PYTHONHOME -u PYTHONUSERBASE python3.12 scripts/manage_ppe.py start --wait
```

浏览器访问 `http://127.0.0.1:8767`，使用恢复的真实素材执行一次检测，核对模型、图片框与可下载证据。PPE 的区域复核入口在没有 Qwen 后端时显示未就绪，主页面顶层不导入 `gradio_client`；实时摄像头分支由现有启动器禁用。

Full 在依赖/算子验证后，另启动已有 Qwen 管理器：

```bash
env -u PYTHONPATH -u PYTHONHOME -u PYTHONUSERBASE python3.12 vision/scripts/manage.py start --wait
```

访问 `http://127.0.0.1:8766`，并在 PPE 页面实际提交一次区域第二意见。服务健康、算子通过和模型业务效果分别核验；4GB 显存仍可能因输入/输出规模不足而失败。停止时分别执行相同管理器的 `stop`。虚拟环境内含绝对启动路径；移动整个仓库后应在新路径重建环境，已恢复资源可继续核验复用。

本轮机器证据见 [R01_PORTABLE.json](validation/R01_PORTABLE.json)：资源恢复使用真实临时 HTTP 与离线字节完成验证；bootstrap 使用真实轻量 venv 配合模拟依赖安装验证路径、幂等与恢复。随后主智能体在独立新目录安装了真实CPU环境，恢复并校验21资源，实跑两照片/3帧视频、四项失败控制和高清照片AppTest，见[G03_CPU_INTEGRATION.json](validation/G03_CPU_INTEGRATION.json)。未启动Qwen，未完成新环境GPU验收。
