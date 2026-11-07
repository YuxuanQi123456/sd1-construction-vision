# 水电一局视觉 AI：共同开发交接

仓库：[YuxuanQi123456/sd1-construction-vision](https://github.com/YuxuanQi123456/sd1-construction-vision)，当前为 **Public**。朋友无需邀请即可查看、克隆及下载已发布的 Release；直接向本仓库推送仍需要所有者在 Settings → Collaborators 添加其 GitHub 账号并由对方接受。也可先 fork 到朋友账号，再通过 Pull Request 贡献。本次未邀请任何未知账号。

源码使用精简开发库，不上传原仓库的大历史。共同开发需要的模型、素材和可选数据由资源清单恢复；历史截图与验收输出已按用户指令清理，原机保留的训练/验收视频、原图、标签和模型见[资源与目录说明](ASSET_RETENTION.md)。

## 取得代码与协作

```bash
git clone -b main https://github.com/YuxuanQi123456/sd1-construction-vision.git
cd sd1-construction-vision
python3 scripts/configure_git.py --name "你的名字" --email "你的提交邮箱"
git switch -c feat/你的功能名
```

邮箱可用 GitHub 隐私 noreply 邮箱；配置脚本只改当前仓库，已有冲突 origin 不会覆盖。朋友使用自己的提交身份和 GitHub 授权。Windows 原生 Python 可用于 Git 配置；下面的运行环境安装与管理命令在 Ubuntu / WSL2 的 Linux 终端执行。

获得写入权限后将功能分支推送到本仓库；使用 fork 时推送到朋友自己的仓库，然后创建 Pull Request。审查后再合并 main，日常更新使用 `git pull --ff-only`，不强推覆盖别人的修改。每个功能单独分支；并行改代码使用独立 worktree，并明确修改范围。

离线代码包可用 `git clone -b main sd1-construction-vision-main-20261107.bundle sd1-construction-vision`，但必须核对 bundle 的提交版本，不能假定已有离线包包含后续更新。bundle 不含模型/视频/环境；离线克隆后 origin 指向 bundle，转在线前先核对 `git remote -v` 再设置 GitHub 地址。

## 恢复资源和环境

完整步骤、系统依赖、空间估算、离线模式和验证要求见[新目录运行说明](RUNTIME_SETUP.md)。基线为 **Linux x86_64、Python 3.12、Ubuntu 24.04 / WSL2**。可先只开发 CPU 检测：

```bash
python3.12 scripts/restore_runtime_assets.py --profile ppe --plan
python3.12 scripts/restore_runtime_assets.py --profile ppe
python3.12 scripts/bootstrap_runtime.py --profile ppe --no-cache-dir
python3.12 scripts/restore_runtime_assets.py --profile ppe --verify-only
env -u PYTHONPATH -u PYTHONHOME -u PYTHONUSERBASE python3.12 scripts/manage_ppe.py start --wait
```

检测页面为 `http://127.0.0.1:8767`。需要千问时将资源恢复与安装的 profile 改为 `full`，确认 NVIDIA 驱动/GPU 条件后，再运行 `python3.12 vision/scripts/manage.py start --wait`，区域模型页面为 `http://127.0.0.1:8766`。两者均只监听本机；关机后需要重新启动。当前原服务保持停止，上传代码/资源不会自动启动服务。

新脚本在本仓库 `.runtime/portable-env/` 安装环境，管理器经相对链接使用它，不再复用原机 `/home/meg` 的包。Torch / torchvision 配对为 2.8.0 / 0.23.0；PPE 用 CPU wheel，full 用 cu128 wheel。直接依赖及安装验证见运行说明。脚本测试、依赖元数据解析和独立目录CPU完整安装/真实照片视频推理已完成，见[CPU集成证据](validation/G03_CPU_INTEGRATION.json)；**CUDA/NF4和目标机业务推理仍需实际验收**，不能直接复制原venv当成迁移完成。

## 资源在哪里

原机上传中可查看`.runtime/release-staging/background-status.json`与`upload-progress.json`；断电后在原机运行仓库外`水电一局_Git交接/继续上传资源.cmd`续传。已校验附件会跳过，只有全部服务端SHA一致后才自动发布。

统一清单为 `config/runtime-assets.json`，固定目标路径、字节数、SHA256、许可和下载地址。[运行资源 Release](https://github.com/YuxuanQi123456/sd1-construction-vision/releases/tag/runtime-20261107-v1) 的可用性以正式发布为准。

| 资源 | 交接方式 |
| --- | --- |
| PPE 基线、高清候选和人员检测权重 | Release ZIP，`ppe` / `full` 恢复 |
| Qwen3-VL-4B 本地 NF4 权重、配置与 tokenizer | Release 配置 ZIP 和有序权重分片，`full` 恢复并校验拼接结果 |
| 允许再分发的原视频、原图、两段验收视频窗口和损坏视频负控 | Release ZIP，保留原字节与来源许可 |
| 4 份 Pexels 高清原片，合计约 41MB | 受原文件独立分发限制，从清单中的原站地址恢复并核 SHA；不在 Release 重发原片 |
| 可选对照权重、RF100 测试子集及头部复核输入 | 追加 `--include-training`；RF100 仅 90 张测试图及 90 份标签，没有完整 train/valid 集 |

Release 资源合计约 3GB，权重由脚本按清单自动下载分片并恢复；以实际清单和发布附件为准。完整运行与可选数据的恢复量不同，下载缓存还会占额外空间，先运行 `--plan`。下载完成的合法附件、外部原片也可放入离线目录，通过 `--assets-dir` 恢复；正确的已有目标文件会核验并跳过。不要把 `downloads/` 当缓存删除。

Git 历史不保存 `downloads/`、`.runtime/`、虚拟环境、模型权重和大运行输出；这些资源可通过 Release / 原站清单交接。保留许可和署名，不把演示照片说成水电一局现场。历史本地演示账号 `config/demo.json` 是公开固定演示值，不能复用于正式系统。

## 两种视觉模型的分工

**Qwen 是千问，Qwen3-VL 是视觉语言模型。** YOLO 产生人员/防护装备的框、类别和检测分数；千问读取选中的头部画面并返回文字第二意见，帮助人工对照分歧。千问不改写 YOLO 分数，两者均在本机推理。只有 CPU 时可以先使用 PPE，区域复核在千问后端未就绪时不可用；这不是另一个新增 Agent 业务。

`vision/config/qwen4b-files.json` 记录官方原始 4B 模型的来源与 13 文件锁，不能用它校验本地 NF4 量化文件。当前可分发量化结果在 `downloads/qwen3-vl-4b-nf4/`，以 `config/runtime-assets.json` 的实际字节与哈希为准。配置优化没有改写模型分数，也不代表重新训练。

## 修改与验证

先读 AGENTS.md、README.md、docs/PROGRESS.md。页面主要在 `sitewatch/app/app.py`，样式在 `sitewatch/branding/`，检测证据在 `review_evidence.py`，区域第二意见在 `region_review.py`，辅助影像问答在 `vision/`。本机代码协作目录为 `E:\workspace\云枢\sd1-construction-vision`；原 `E:\workspace\云枢\水电一局演示Demo` 保留运行资源与旧 Git 历史，不承担 GitHub 推送，禁止直接合并两个独立历史。

修改 app 下 Python 后同步上游 patch，并执行：

```bash
python3 sitewatch/verify_provenance.py --output .runtime/developer-source-check.json
git diff --check
```

资源/环境脚本的针对性测试见 `tests/test_runtime_assets.py`、`tests/test_bootstrap_runtime.py`。浏览器与真实推理需恢复对应环境/资源后实跑，结果如实记录；每个任务提交必要的小份验证摘要到 `docs/validation/`，大运行输出保留本地。原机曾运行成功不能替代新代码、新环境的验收。字节保留规则见 `.gitattributes`，指定 Windows 启动器使用 CRLF，其余避免自动换行损坏来源哈希。

Git 官方：[bundle](https://git-scm.com/docs/git-bundle)、[换行属性](https://git-scm.com/docs/gitattributes)；GitHub 官方：[邀请协作者](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository)。
