# 资源保留与协作目录

GitHub协作项目：`https://github.com/YuxuanQi123456/sd1-construction-vision`。

| 用途 | 本机目录 |
| --- | --- |
| 后续代码协作、提交与GitHub推送 | `E:\workspace\云枢\sd1-construction-vision` |
| 原演示运行资源、模型与原Git历史 | `E:\workspace\云枢\水电一局演示Demo` |

两者是独立Git历史，禁止相互直接pull或用无关历史合并。精简开发仓库从当前源码快照起步；原Git历史保留本机，停止其GitHub推送入口。后续开发使用精简目录，原机部署时再明确同步代码并做回归，不能把旧运行目录的结果称为新代码已验证。

用户已要求删除历史截图/验收记录，旧大记录从工作目录移除，不再额外生成其重复大归档。精简离线bundle也只包含协作库代码历史。原始Git历史仍占本地Git空间，本次未重写或清除其他工作树历史。

保留原目录的全部`downloads/`、`.runtime/`、训练原图/标签、模型文件和现有素材；也保留全部16个evidence裸视频原路径及原照片/输入裁图。训练资源位于`downloads/ppe-v07/`等目录，本轮没有执行模型训练或删除训练数据。

以下验收视频内容均逐SHA核对保留，特别包含损坏视频负控：

| 内容 | SHA256 | 受保护原件（相对原演示目录） |
| --- | --- | --- |
| Florenc正常窗口 | `5ba18caeb610a7142367d3d99b9693d9bc183bf0f80a90d78430c8976b6a6628` | `.runtime/vision-media/window-florenc-0-8.0.mp4` |
| Hostivar窗口 | `f0ae3900a83c6364056c20679d9a9de030fa59bbfe288a1a1c6bcabaad697062` | `.runtime/vision-media/window-hostivar-0-8.0.mp4` |
| 故意损坏的视频负控 | `44f508c2f0b72adfaefd0b01ca55bb8e55856195e85527b0ea7f22ef64ca37e7` | `.runtime/sitewatch-env/runtime/uploads/44f508c2f0b72adfaefd0b01ca55bb8e55856195e85527b0ea7f22ef64ca37e7/broken-video.mp4` |

4K/1080p/旧540p素材及其他公开视频以`sitewatch/demo-media.json`、`sitewatch/media-sources.json`和`vision/config/samples.json`为恢复清单；原字节、署名、许可随清单保留。资源不写入Git源码历史；本轮按用户进一步授权将必要模型、可再分发原片、90图测试子集发布为Release附件。4份Pexels原件由恢复脚本从原站下载并核SHA，保留画质。新清单以`config/runtime-assets.json`为准，恢复方式见[运行环境恢复](RUNTIME_SETUP.md)；上传是否完成以Release发布状态和最新进度为准。

新开发目录的Windows启动器按自身所在目录启动，避免误启动原运行目录。新目录仍需重建Python/Torch环境并准备模型，不能把修复路径说成新机器安装已通过。旧运行目录启动器保留其原有工作方式。
