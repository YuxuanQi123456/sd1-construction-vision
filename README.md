# 水电一局 · 施工安全视觉 AI 演示

面向水电一局领导汇报的公开协作项目，优先复现 [SiteWatch 开源应用](https://github.com/AitchEm-bot/sitewatch)，使用真实 YOLO 检测与 GPT 区域复核。云枢源码无法取得；Agent 业务由其他工作区承担。

项目文档：[任务书](docs/VISUAL_TASKBOOK.md) · [Progress：已完成内容与技术实现](docs/VISUAL_PROGRESS.md) · [下一步优化计划](docs/VISUAL_OPTIMIZATION_PLAN.md)。

完整流程：**选择施工照片/视频 → 识别人员、安全帽与反光背心 → 选中头部交给 GPT 复核 → 人工查看与对照 → 下载原图、框图、JSON 与证据 ZIP。** 当前是固定素材演示，允许调参及样例微调，不将其表现当成新工地准确率。

默认视频为 1080p 结构施工作业；另有两条 4K 近景视频、两张高清照片和一张砌筑作业复核对照图。素材自动选择实测更合适的 SiteWatch 或 Constructelligence，也可手动切换。原轨道视频因远景人帽漏检退出演示菜单，原片和上传检测功能保留。“保留原片画质”默认开启，保存原尺寸 PNG，原视频字节不变；模型内部输入尺度另行记录。

SiteWatch 的 **25 是目标类别数，不是 25 项安全功能**：人员 1、防护相关 7、机械设施 6、车辆 11。Constructelligence 为 14 类。本演示重点为人员与 PPE；缺少防护的 NO-* 框是待复核候选，尚无自动违规、动作识别或全程实时监控结论。

YOLO 在本地 CPU 执行，不消耗 API token。GPT 仅在点击“复核所选头部”时发送所选裁图，默认 `gpt-6.1-sol`、`max`；Key 写入忽略文件 `config/review-api.local.json`，见 [API 设置](docs/GPT_API_SETUP.md)。已删除千问模块、权重恢复项及 full 环境，不需要本地大语言模型或 GPU。未配置 API 时仍可检测与导出。

新机器用 Ubuntu / WSL2、Linux x86_64、Python 3.12，先按 [运行说明](docs/RUNTIME_SETUP.md) 安装系统依赖，再执行：

```bash
python3.12 scripts/restore_runtime_assets.py --profile ppe
python3.12 scripts/bootstrap_runtime.py --profile ppe --no-cache-dir
python3.12 scripts/manage_review_api.py init
python3.12 scripts/manage_ppe.py start --wait
```

入口 **http://127.0.0.1:8767**。环境就绪后 Windows 可双击 [启动施工视觉.cmd](启动施工视觉.cmd)，停止用 [停止施工视觉.cmd](停止施工视觉.cmd)。关机后须重新启动服务，浏览器收藏不能自行启动后台。

Git 仅含精简源码与必要验证摘要。模型及允许再分发的测试资源通过 [PPE 资源 Release](https://github.com/YuxuanQi123456/sd1-construction-vision/releases/tag/runtime-20261107-v1) 恢复；五份 Pexels 原件从原站下载并逐项校验 SHA，不上传 Git。所有示例均为有来源的公开实拍，非水电一局现场。

- [共同开发交接](docs/DEVELOPER_HANDOFF.md)、[演示顺序](docs/PPE_DEMO.md)
- [里程碑与验收](docs/MILESTONES.md)、[进度与验证](docs/PROGRESS.md)
- [工作规则](AGENTS.md)、[架构](docs/ARCHITECTURE.md)、[决策](docs/DECISIONS.md)
- [代码、模型与素材许可](sitewatch/NOTICE.md)
