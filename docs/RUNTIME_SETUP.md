# 恢复施工安全视觉演示

当前只支持 `ppe` CPU 环境：YOLO 检测与可选 GPT API 复核。`full` 和本地千问已移除；旧 full 环境不会被脚本静默覆盖。API Key 只保存在本机忽略文件，见 [GPT 设置](GPT_API_SETUP.md)。旧材料应用不在本轮运行范围。

## 系统与空间

基线：Ubuntu 24.04 / WSL2、Linux x86_64、Python 3.12、glibc ≥ 2.28。

```bash
sudo apt-get install python3.12-venv libgl1 libglib2.0-0
python3.12 --version
```

无需 GPU。Torch / torchvision 使用 2.8.0+cpu / 0.23.0+cpu；直接依赖固定在 `config/bootstrap-ppe.txt`。环境约 1.5–2GB，建议预留 2.5GB 加安装临时空间；资源与下载缓存另计。先查看计划：

```bash
python3.12 scripts/restore_runtime_assets.py --profile ppe --plan
python3.12 scripts/bootstrap_runtime.py --profile ppe --plan
```

## 资源恢复

```bash
python3.12 scripts/restore_runtime_assets.py --profile ppe
python3.12 scripts/restore_runtime_assets.py --profile ppe --verify-only
```

`config/runtime-assets.json` 固定目标路径、字节数、SHA256、来源与许可。当前 11 个资源包共 41 个附件，209 份可分发文件；5 份 Pexels 原件共约 52.6MB 从官方地址恢复，无降清晰度。追加 `--include-training` 才恢复可选对照模型、RF100 的 90 张测试图/90 份标签及头部输入；没有完整 train/valid 数据，也没有新训练结果。

下载完成的附件缓存于 `.runtime/asset-downloads/`，重跑可复用已验证缓存。ZIP 仅接受白名单成员，权重分片与拼接后总文件均验 SHA；拒绝路径穿越、符号链接、额外成员和已有异内容文件，不提供覆盖开关。正确目标会核验并跳过。

离线时，将 Release 附件与五份外部原件置于一个目录：

```bash
python3.12 scripts/restore_runtime_assets.py --profile ppe --assets-dir /path/to/offline-assets
```

附件使用清单 `assets[].name`，外部原件使用目标 basename，也可统一命名 `<sha256>-<basename>`。缺少离线输入会报错，不触网。`--project-root` 可指定另一个已有目录。不要把 `downloads/` 当缓存清理；其中有视频、权重和训练输入。

## 项目内 CPU 环境

```bash
python3.12 scripts/bootstrap_runtime.py --profile ppe --no-cache-dir
```

只安装在本项目 `.runtime/portable-env/`，`.runtime/sitewatch-env` 为项目内相对链接。安装清除 Python 路径注入，禁用用户和系统包目录；不引用其他项目环境。实际依赖解析报告留在环境内；结束时检查隔离、`pip check`、CPU tensor 与 torchvision NMS。

脚本可重试并核对归属标记。已有非托管环境或旧 full 环境会明确拒绝；迁移时先停本项目服务，保留旧环境与其中 `runtime/` 业务数据，再在新路径建 CPU 环境。不能直接删除旧环境中的原视频、上传或验收输入，也不能复制旧 venv 当成迁移完成。移动仓库后需在新路径重建环境。

## 启动与演示

```bash
python3.12 scripts/manage_review_api.py init
# 按 GPT_API_SETUP.md 填本机 Key；也可先不填，仅检测。
env -u PYTHONPATH -u PYTHONHOME -u PYTHONUSERBASE python3.12 scripts/manage_ppe.py start --wait
python3.12 scripts/manage_ppe.py status
```

打开 http://127.0.0.1:8767，按 [演示说明](PPE_DEMO.md) 运行。停止执行 `python3.12 scripts/manage_ppe.py stop`。Windows 根目录启动/停止脚本调用 WSL；关机后需要重新启动。只有页面和真实推理通过，才能认为目标机可演示；Key 已配置不等于 API 已连通。

恢复脚本会拒绝旧含 full/Qwen 项的资源清单，请使用当前 main 的完整代码与清单。历史安装证据见 [CPU 集成](validation/G03_CPU_INTEGRATION.json)，本次移除与新视频回归见 [进度](PROGRESS.md)。
