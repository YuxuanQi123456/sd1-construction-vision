# 来源与使用说明

水电一局品牌组合标识来自https://1j.powerchina.cn/ 官方网站原始PNG，按原字节保存于branding/logo.png，来源/尺寸/本地SHA见branding/SOURCE.json。仅用于用户指定的水电一局演示界面识别，不重绘或重新授予该企业标识开源许可。

新增清晰演示素材清单及原字节SHA见demo-media.json。两段3840×2160视频为Mikael Blomkvist/Pexels（8963856、8964378）；高清照片为This Viktọ（10202856）和Antoni Shkraba（4981775）。来源及Pexels License链接随素材显示；用于装备识别演示，非水电一局现场，不暗示人物为本产品背书。原件下载后本地锁定SHA，发布方未提供官方摘要，不冒称官方哈希验证。原片未增强/缩放；框为模型输出。许可适用https://www.pexels.com/license/ ，不能把人物用于负面/冒犯或背书语境。

Hostivar原1080p前8秒以视频流复制方式提取，首帧解码像素核对与原文件相同；未覆盖既有540p派生视频。保留画质模式保存原尺寸PNG，完全相同像素的多个视图字段可共用文件；原输入不画框，模型分数不改。模型内部仍有显式输入尺度，显示/保存原片不代表网络处理了全部原片像素。

SiteWatch 原作者为 Hani Moustafa 及 SiteWatch project contributors，固定源码提交为 `72c4d18135fd07afd188fecaac37c5b90ec674b4`，来源 https://github.com/AitchEm-bot/sitewatch 。原始源代码适用 MIT，未经修改的许可保存在 `upstream/LICENSE`；本地薄适配的可复现差异在 `patches/local-review.patch`。

Ultralytics YOLO 及 `sitewatch_best.pt` 衍生权重适用 AGPL-3.0；完整 Ultralytics 许可证保存在 `licenses/Ultralytics-AGPL-3.0.txt`。模型二进制未提交，仅保存固定来源、SHA256 和实际类别清单。后续分发、网络服务和修改应遵循相应许可。

公开实拍示例的作者、来源、许可、原件 SHA256 和视频派生说明集中保存在 `media-sources.json`。复核按上传原字节 SHA256 匹配登记信息，写入 `detections.json` 与 ZIP 内 `source-provenance.json`；来源元数据只用于署名和追溯，不进入模型输入。未登记的用户素材明确标为来源与许可未知，不套用示例许可。全部公开示例均非水电一局现场，也不是法规违规真值标签。

界面默认显示人员和PPE类框，完整专用模型类别与带框图始终在证据包中，可切换显示。存在已记录的设备与人物误检、裸头误检为Hardhat、标准模式角磨机照片零检出。NO-*是模型类别，只能作为人工复核线索；未检出不能推导缺少装备或安全。视频时间使用帧序号/容器FPS估算，可变帧率视频不保证精确时间。

候选对照权重Constructelligence v0.3来自 https://huggingface.co/constructelligence/construction-site-safety-hazards ，固定revision79673cff5a8bb249fc8ec9cca3daa19e2ef95191，权重AGPL-3.0，实际14类。来源、下载地址和SHA锁在model-candidates.json；只作为明确选择的对照，不悄悄替换原默认。公共测试指标不能当现场准确率，已知裸头误报仍保留。

区域第二意见默认使用用户配置的GPT-6.1 Sol Max API；该服务调用不代表本项目重新分发其模型权重。显式本地Qwen3-VL官方Gradio应用和已核验4B NF4权重继续保留，其Apache-2.0来源见 ../vision/NOTICE.md。只提交未画框的裁剪图和固定视觉分类问题，不传人工预期答案。原始检测类别/分数不修改，复核文字没有校准概率，分歧需人工核对。裁剪、原文和实际模型信息保存在完整证据包。

远景演示配置补回上游原本的通用人员分支：Ultralytics官方YOLOv8n COCO权重，固定HF revision27f858f2dc238503a66ce10248cf7ec71a3ded5d、SHA31e20dde3def09e2cf938c7be6fe23d9150bbbe503982af13345706515f2ef95、AGPL-3.0，只允许class0/person。manifest见person-model.json。PPE专用模型仍是原固定权重；照片640/视频1280配置及人员640分支分开记录，保留去重前原始分支。当前为固定素材演示适配，不把样例调参或同片训练效果当泛化成绩。
