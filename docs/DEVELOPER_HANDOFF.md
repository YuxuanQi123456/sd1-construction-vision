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

## 运行与共同开发

当前已移除千问，使用本地 CPU YOLO 和可选 GPT API，无需 GPU。按 [运行说明](RUNTIME_SETUP.md) 恢复 `ppe` 资源与隔离环境；[API Key](GPT_API_SETUP.md) 每人只填自己的本机忽略文件，不共享提交。当前 Release 保留 41 个 PPE/可选训练附件，不必重新上传视频或模型；五份 Pexels 原件约52.6MB从官方恢复。

```bash
python3.12 scripts/restore_runtime_assets.py --profile ppe
python3.12 scripts/bootstrap_runtime.py --profile ppe --no-cache-dir
python3.12 scripts/manage_review_api.py init
python3.12 scripts/manage_ppe.py start --wait
```

打开 http://127.0.0.1:8767，按 [演示顺序](PPE_DEMO.md) 操作。关机后重新启动。代码与依赖安装独立于模型资源，不能复制旧 venv；旧 full 安装不再支持。根目录启动器只启 PPE 与检查 GPT 配置。

V15 已增加检测结果下方的 AI 巡查总结、待确认问题与三状态/备注保存，接口见 [总结契约](../contracts/safety-summary-v1.md)，验证见 [V15](validation/V15_SAFETY_SUMMARY.json)。复用现有图像配置，无新模型/依赖；旧本机配置缺少 `summary_max_output_tokens` 时默认8192，头部仍4096。总结只按按钮发一次请求，人工保存和导出不触网。`.runtime` 的任务及人工记录不进Git，当前没有历史任务页面；分享实际报告请用TXT/ZIP，不共享Key。

## 资源在哪里

统一清单 `config/runtime-assets.json` 固定全部字节与SHA。[资源 Release](https://github.com/YuxuanQi123456/sd1-construction-vision/releases/tag/runtime-20261107-v1) 继续复用原有 41 份非千问附件，千问附件已删除；以当前清单为准，旧 tag 的源码归档属于历史版本，开发请 clone 当前 main。

| 资源 | 方式 |
| --- | --- |
| SiteWatch、Constructelligence与人员权重 | `ppe` 恢复；AGPL-3.0 |
| 可再分发的公开视频、原图与验证输入 | Release，保留原字节与许可 |
| 三视频、两照片的Pexels原件约52.6MB | 官方原站下载与SHA校验，不在Release重发 |
| RF100 90图/90标签测试子集、对照权重、头部输入 | 追加 `--include-training`；无完整train/valid集 |

资源恢复会跳过正确已有文件，支持 `--assets-dir` 离线恢复。模型、视频、环境、Key、授权与大输出不进入Git；项目内`.runtime/asset-downloads`可在核验全部目标后清理，`downloads`与业务runtime不是可整体删除的缓存。

旧离线 bundle 固定旧提交，不代表已获得最新代码。优先 GitHub clone 当前 main，再按清单恢复；如收到新版协作包，核对其中 code_commit 并按附带说明复制资源。朋友直接 push 原库仍需协作者权限；fork + PR 无需该权限。
