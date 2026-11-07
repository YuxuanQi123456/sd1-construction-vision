# SiteWatch 原生应用本机复现

**新clone先看[项目内环境与资源恢复](../docs/RUNTIME_SETUP.md)。** 现在使用`restore_runtime_assets.py`和`bootstrap_runtime.py`，支持不依赖旧机器路径的PPE CPU模式与full视觉复核模式。下方`prepare.py`和旧环境版本仅为原机历史部署记录，不适用于新机器。

## 水电一局演示界面

页面标题“水电一局 · 施工视觉AI”，使用官网原始组合标识、本地蓝白样式与中文操作。默认进入“清晰演示素材”，自己的照片/视频在侧栏切“自己上传”；启动识别按钮为“开始识别与复核”。模型、场景仍可手动覆盖；阈值与增强位于“高级识别设置”，来源许可保留在折叠区。结果卡仅取本次实际帧数、待复核框次数和耗时，完整原始输出仍可下载。

内存不足时用根目录`scripts/manage_ppe.py stop`停止本项目视觉页面、`vision/scripts/manage.py stop`停止本项目区域模型；不得按通用python进程名清理。缓存最多两组模型配置；断开会话60秒只是惰性过期门槛，不保证定时释放总内存。2026-11-07清理后双服务按同机标书优先安排保持停止，后续演示时使用原启动脚本恢复。

## 高清素材与原片质量

侧栏可在“自己上传”和“清晰演示素材”间切换；素材库本地读取demo-media.json并验证路径/字节/SHA，不通过外部服务推理。默认自动模型/预设按库条目实测推荐解析，仍可手动覆盖；自己上传自动回到SiteWatch并按图片/视频选择标准/远景。

“保留原片画质”默认开启：关闭有效增强，不预先缩小解码图；PNG保存尺寸等于输入尺寸，原始影像按字节保留。大图默认显示，原图可展开、可切左右对照；三个原尺寸下载分别返回原件或对应PNG。页面随屏幕缩放，下载为原字节。高分辨率PNG耗时/空间更多，原生大文件只留downloads/runtime，不重复提交Git；推理输入仍按profile设置独立处理。

两段新视频3840×2160，原轨道1080片无重编码裁切，旧540片保留。新素材恢复可按demo-media.json的download_url取得，并校验其中SHA；prepare_hd_media.py仅探测已下载素材并生成无降尺寸轨道片。该来源恢复脚本不安装依赖，未声称新机器一键安装已通过。先前仅调配置与模型组合，没有训练权重。

保留上游原生 Streamlit 的 Review footage / Live monitoring 页面及 YOLO / 绘框代码。`upstream/` 是未经修改的源码快照；`app/` 是薄适配后的可运行副本；二者的全部改动保存在 `patches/local-review.patch`。上游来源、固定提交和逐文件 SHA256 见 `SOURCE.json`。下载模型和虚拟环境不入 Git。

## 启动

在集成后的项目根目录使用归属受控的后台入口：

```bash
python3 scripts/manage_ppe.py start --wait
python3 scripts/manage_ppe.py status
python3 scripts/manage_ppe.py stop
```

Windows可双击根目录的 `启动施工视觉.cmd` / `停止施工视觉.cmd`，同时管理CPU检测与Qwen区域复核。命令行另运行 `python3 vision/scripts/manage.py start --wait` 加载本地GPU模型，首次需等待几分钟；status/stop同理。CPU可单独使用，Qwen未就绪时局部复核按钮禁用。重复启动不新增进程；停止只作用于核验过的本项目进程。`python3 sitewatch/run.py` 保留前台调试方式；先结束前台服务再用后台管理入口，不自动接管未知端口。

本任务 worktree 中运行时显式指定共享运行资产的主项目目录：

```bash
python3 sitewatch/run.py --project-root /mnt/e/workspace/云枢/水电一局演示Demo
```

访问 `http://127.0.0.1:8767`，选择素材或切换“自己上传”导入原始 JPG / PNG / MP4 / WEBM 等文件，点击“开始识别与复核”。默认 CPU、置信度 0.40、原图不增强，视频只检测起始 8 秒内每秒一个画面，可选起始 1–30 秒及 0.5 / 1 / 2 秒间隔。结果列出实际采样时间，不代表视频全程。

自己上传的默认演示预设为自动：照片标准640；视频远景PPE1280，补充COCO人员640。素材库按条目推荐配置解析。可手动切标准/远景，切换会清除旧显示结果，需重新检测。默认叠框与表格显示人员+PPE；完整类别和两分支原始输出在JSON/ZIP。远景person companion缺失/哈希不符会明确失败，手动切标准可继续使用原PPE；不会静默降级。

人员权重本机在`downloads/ppe-v09/yolov8n.pt`（6,534,387字节）；`prepare.py`仍只恢复原PPE环境/权重，新增人员资产按`person-model.json`固定来源与SHA恢复：`https://huggingface.co/Ultralytics/YOLOv8/resolve/27f858f2dc238503a66ce10248cf7ec71a3ded5d/yolov8n.pt`。本机实际下载和SHA已验证，未宣称新机器全量安装通过。

运行数据全部放在 `<project-root>/.runtime/sitewatch-env/runtime/`：上传原件、逐帧输入、真实框图、`detections.json`、可下载 ZIP。JSON 保存原件 SHA256、模型来源与 SHA256、实际类别、浮点原始框、四舍五入绘图框、分辨率和 CPU 推理耗时。坐标对应 `detection_dimensions_wh`；`source_dimensions_wh` 用于回溯原图缩放比例。时间为解码帧序号除以容器 FPS，不宣称可变帧率视频的精确 PTS。

## 模型与判断边界

自己上传在自动模型下使用 SiteWatch 原权重 `sitewatch_best.pt`，25 个实际类别见 `SOURCE.json` 和界面模型来源栏；远景另加载固定COCO人员伴随模型。素材库自动模型按条目推荐，当前两张新照片使用Constructelligence。缺失、损坏、SHA256 不符或类别不符都会明确失败，禁止以COCO替代坏PPE模型。原类别中的人员、机械框作为观察展示；仅直接 `NO-*` 类别计入待人工复核框次数，不能据此认定法规违规。未检出不代表缺少装备或安全；次数不是人员去重统计。

侧栏可显式选Constructelligence v0.3的14类固定对照；来源/revision/SHA登记在`model-candidates.json`。它仍误判砌砖工，不满足默认替换门槛；公共集AP不是现场准确率。`prepare.py`恢复基线环境和原权重，候选权重与Qwen持久模型另按各自固定manifest恢复，本机以外的全新安装未实测。

完成检测后，选择可见的直接头部框，再点击“复核所选头部”。页面显示未画框裁剪、原检测分数、Qwen原答及两者是否分歧；无头部框不猜是否戴帽。原始检测JSON不改写，证据ZIP递归包含head-reviews里的裁剪及全部调用attempt；重试不覆盖失败。区域服务要求固定4B NF4，启动器若回退2B仍不能做本轮已验证的区域复核。原Qwen通用隐患判断不通过结论保持。

离线上传复核不调用运动、像素距离、形状或“未检出即缺少”的规则。上游运动和实时监控源码完整保留；本机启动入口明确禁用实时摄像头，不导入 WebRTC、不申请相机权限。`ppe_compliant` / `ppe_violation` 是为保持上游绘框兼容而沿用的内部类别字段，不是合规结论。

已跑的真实照片和视频不属于水电一局现场。NIOSH 照片是公有领域；角磨机照片为 Mungai Kiroga / CC BY-SA 4.0；Florenc 视频为 ŠJů / CC BY 4.0。完整来源见`media-sources.json`和`../vision/config/samples.json`。

## 历史原机安装记录（不用于新clone）

专用环境路径为 `<project-root>/.runtime/sitewatch-env`。它只读绑定原有 `vision/.venv/lib/python3.12/site-packages` 的 Torchvision 等包，以及 `/home/meg/venvs/qyx_patent/lib/python3.12/site-packages` 的 Torch，不修改这两套环境。此次实际版本包括 Python 3.12.3、Torch 2.14.0、Torchvision 0.29.2、Ultralytics 8.3.228、Streamlit 1.51.0。所有在专用环境中新装的包固定在 `requirements-lock.txt`；外部依赖版本与来源在 `evidence/V05/runtime-packages.json`。

以下命令依赖原机外部环境，仅保留作历史记录；新机请使用页首的新恢复入口：

```bash
python3 sitewatch/prepare.py --project-root /mnt/e/workspace/云枢/水电一局演示Demo
```

该命令仅写专用环境和 `downloads/sitewatch/`，下载固定提交的原模型并验证 SHA256，不下载 COCO 模型。包缓存也留在专用环境的 E 盘目录。网络沙箱下需按工具权限流程批准必要下载。

源码 MIT，保留 Hani Moustafa 及 SiteWatch 贡献者署名；Ultralytics 与其衍生权重适用 AGPL-3.0，原说明在 `upstream/LICENSE`，完整 Ultralytics 许可证在 `licenses/`。分发或进一步使用应遵循对应许可。

## 验证

```bash
.runtime/sitewatch-env/bin/python sitewatch/verify.py --project-root /mnt/e/workspace/云枢/水电一局演示Demo --output evidence/V05/cpu-rerun
.venv/bin/python sitewatch/browser_verify.py --project-root /mnt/e/workspace/云枢/水电一局演示Demo --output evidence/V05/browser-rerun
python3 sitewatch/verify_provenance.py --output evidence/V05/provenance-rerun.json
```

每次 CPU 验证使用新的输出目录，以免覆盖已有原始证据。浏览器脚本复用已启动的隔离 Edge 调试端口 9226，创建全新浏览器上下文；不使用个人浏览器配置。Windows CDP 的下载临时文件不能直接保存到 Linux 路径，因此脚本点击原生下载按钮并验证其本机 HTTP 响应内容。报告不把跨系统 `Download.save_as` 当作通过。

实际效果：NIOSH 近景直接检出 Hardhat 0.8218、Safety Vest 0.9233；同图钻孔机械被误标为 Excavator 0.5515，并出现设备细节误检 Person；角磨机近景默认阈值下零检出，保留为漏检；Florenc 0 秒采样直接输出 NO-Safety Vest 0.7302，须对照画面人工复核。轻量 YOLO11n 候选同图也漏检角磨机，未接入默认应用。以上仅是有限样本实测，不是施工安全总体准确率验收。

浏览器脚本可加 `--additional-image <Path> --expected-additional-class NO-Hardhat`，将附加原图插在两张基准图之后、视频之前。可加 `--negative-video <损坏MP4>`，验证明确失败后再上传正常图片恢复。最终扩展黑盒回归状态见 V05/ASSESSMENT.md，不因脚本存在而认定通过。

当前默认显示人员和PPE；“显示全部25类”可查看其它设备与误检，完整原始JSON和all-overlay从不被筛除。ZIP的source-provenance.json按原件SHA归属已登记样例；未知上传明确未登记。抹灰工标准配置直接检出NO-Hardhat0.90215；砌砖工裸头被误检Hardhat0.85502，完整对照均保留。
