# 水电一局 · 施工影像 AI 演示

这是面向水电一局演示的公开协作仓库。源码通过 Git 管理，模型、视频和可选数据通过 Release 资源清单恢复；原仓库的大历史与已清理的截图/验收输出不上传。新开发者先看[开发交接](docs/DEVELOPER_HANDOFF.md)和[新目录运行说明](docs/RUNTIME_SETUP.md)。

[运行资源 Release](https://github.com/YuxuanQi123456/sd1-construction-vision/releases/tag/runtime-20261107-v1) 的可用性以正式发布为准；恢复命令下载后逐项核对 SHA256，clone 本身不包含运行资源或 Python 环境。

当前主流程为 **施工照片/短视频的防护装备AI初筛→头部区域AI第二意见→人工复核→证据导出**。页面以水电一局官方组合标识、蓝白配色和中文操作展示，默认打开高清素材库。复现 [SiteWatch开源应用](https://github.com/AitchEm-bot/sitewatch) 原生页面和YOLO模型，复用已部署的Qwen官方接口做局部判断。两模型意见并列保留，原检测分数和类别不改写；CPU检测、GPU复核均在本机执行。

**Qwen 就是千问，这里使用的是 Qwen3-VL 视觉语言模型。** YOLO 负责框出人员/防护装备并给出检测分数；Qwen3-VL-4B 的本地 NF4 量化版查看选中的头部画面，给出文字第二意见。它属于现有视觉流程；`ppe` CPU 模式可以只运行检测，`full` 模式再启用千问复核。

新增清晰演示素材：侧栏选择“清晰演示素材”，可直接载入两段4K近景视频、两张高清照片，以及原轨道视频的1080p版本；旧540p视频和自己上传入口保留。默认开启“保留原片画质”，原件按字节保留、画面按原尺寸无损PNG保存；默认大图展示，可切左右对照，并下载原尺寸输入、框图和原视频。页面按屏幕缩放，模型内部推理尺度单独记录。

当前按固定素材优化演示效果，允许样例适配。自己上传时自动使用照片标准/视频远景配置；素材库按每条实测推荐模型和尺度运行，手动选择可覆盖推荐。近景新视频的帽框实测约0.91/0.94；旧Hostivar第7秒两位工人与红衣工人的帽候选仍可演示。此次通过配置与模型组合改善，未重新训练权重；分数未人工修改。

**入口：http://127.0.0.1:8767**

新机器先按[运行说明](docs/RUNTIME_SETUP.md)恢复资源、安装仓库内环境；支持 Ubuntu / WSL2、Linux x86_64、Python 3.12。仅检测可执行 `python3.12 scripts/restore_runtime_assets.py --profile ppe` 和 `python3.12 scripts/bootstrap_runtime.py --profile ppe`；带千问使用 `full`，需可用 NVIDIA GPU。本轮已在独立新目录完成 CPU 安装、21资源恢复与真实照片/视频推理；GPU 业务推理仍须在目标机验收。

环境就绪后，Windows双击 [启动施工视觉.cmd](启动施工视觉.cmd) 启动检测与本地区域模型，冷启动需等待几分钟；结束时运行 [停止施工视觉.cmd](停止施工视觉.cmd)。命令行分别使用 `python3 scripts/manage_ppe.py start --wait` 和 `python3 vision/scripts/manage.py start --wait`，各自支持status/stop。操作顺序见 [演示说明](docs/PPE_DEMO.md)，新目录安装与迁移以[运行说明](docs/RUNTIME_SETUP.md)为准，原机操作参考 [SiteWatch 运行记录](sitewatch/OPERATIONS.md)。

**关机或重启电脑后，需要重新运行启动脚本。** 当前项目采用手动启动；浏览器收藏的127.0.0.1地址不会启动后台服务。启动时保留命令窗口，等待检测页面和区域模型就绪后自动打开网页；若报错，窗口会保留日志位置。

真实砌砖工样例中，检测器误判Hardhat0.855，局部Qwen回答未见工业安全帽，形成可核对的模型分歧；三照片第二意见已实跑。可显式切换固定Constructelligence候选，对照角磨机照片人员检出；候选仍有误检，默认保持SiteWatch。NO-*与第二意见都需人工确认，未检出不能解释为安全；视频默认仅分析起始8秒内每秒一个画面。自动违规判定尚未通过验证。

根集成验收状态以 [进度记录](docs/PROGRESS.md) 为准。全部样例为有许可的公开实拍，非水电一局现场，来源不作为模型答案输入。

- [里程碑、依赖和验收标准](docs/MILESTONES.md)
- [项目工作规则](AGENTS.md)、[架构](docs/ARCHITECTURE.md)、[决策与失败调整](docs/DECISIONS.md)
- [SiteWatch 代码/模型/素材许可](sitewatch/NOTICE.md)

Qwen3-VL 官方应用保留为辅助影像问答对照，访问 `http://127.0.0.1:8766`，使用 [视频AI启动脚本](vision/启动视频AI.cmd)。4B/16帧版本14项网页检查、三视频五次问答、两照片及追问均实跑，但漏识别远景吊运并有事实错误，通用自动隐患判断业务不通过，见 [Qwen阶段验收（记录已清理）](docs/ASSET_RETENTION.md)。

云枢源码不可取得，本项目优先复现开源应用，仅做必要薄适配；Agent业务由其他工作区承担。主智能体负责集成与回归，子智能体在独立worktree完成限定任务。历史材料库存试跑已停止服务，仅保留 [历史验收（记录已清理）](docs/ASSET_RETENTION.md)，采购等扩展不再自动推进。
