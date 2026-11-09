# 水电一局视觉 Demo 下一阶段深度调研汇报

日期：2026-11-10

## 结论先行

下一次给领导演示，建议不再单纯更换 YOLO 或继续堆类别，而是把现有流程升级为：

**检测 → 跨帧跟踪 → 区域/停留事件 → 关键帧证据 → AI 总结 → 人工确认/导出。**

领导能直接看到同一个人或设备的 ID、轨迹、出现时长、进入/停留区域和事件时间线；这比“某一帧有几个框”更像完整的安全监测系统，也正好复用当前视频、检测 JSON、采样时间和 AI 总结能力。

首选技术是 ByteTrack/现有 Ultralytics track 接口。它的官方仓库是 MIT 许可，并提供检测框到轨迹的实现；论文方法通过高低分框两阶段关联提高遮挡场景下的轨迹连续性。[ByteTrack 官方仓库](https://github.com/FoundationVision/ByteTrack) [ByteTrack 论文](https://arxiv.org/abs/2110.06864)

并行做一个独立 GPU 试验：用 SAM 2 对用户点选的一个人或设备传播视频 mask，生成半透明连续轮廓关键帧。SAM 2 官方代码提供视频 predictor、prompt 和 mask propagation，代码为 Apache-2.0；它最容易带来“视觉上明显更高级”的效果，但不能阻塞 CPU 基础链。[SAM 2 官方仓库](https://github.com/facebookresearch/sam2) [Meta 介绍](https://ai.meta.com/research/sam2/)

## 推荐的领导演示脚本

1. 选择当前结构施工视频，运行现有本地检测。
2. 切换“对象轨迹”视图：显示 track ID、轨迹线、去重人数和出现时长。
3. 在画面上画一个“演示区域/候选区域”，展示人员进入、停留、离开时间。
4. 点击某个对象跳回关键帧，显示原始框、时间、检测分数和模型配置。
5. 如果 SAM 2 GPU 试验通过，展示该对象的连续 mask 和关键帧。
6. 用现有 AI 巡查总结归纳事件关键帧；疑点仍然全部待人工确认。
7. 保存确认/排除、备注，下载事件报告和完整证据 ZIP。

## 开源项目排序

| 顺序 | 项目 | 用途 | 建议 |
|---:|---|---|---|
| 1 | ByteTrack | 人员/设备 ID、轨迹、去重人数 | 直接作为下一条主线 |
| 2 | SAM 2 | 单对象视频 mask、连续视觉证据 | 独立 GPU 试验，成功再接页面 |
| 3 | BoT-SORT | 相机抖动、遮挡、Re-ID 备选 | 只有 ByteTrack ID 断裂明显才引入；根仓库 MIT，FastReID 子依赖另审。[仓库](https://github.com/NirAharon/BoT-SORT) |
| 4 | Depth Anything V2 | 近/中/远深度热图 | 只做空间辅助；没有标定不输出米数。[仓库](https://github.com/DepthAnything/Depth-Anything-V2) |
| 5 | Grounding DINO | 文本描述→候选框 | 做离线候选，不替代 PPE 检测；论文和代码均提示开放集合误报风险。[仓库](https://github.com/IDEA-Research/GroundingDINO) |
| 6 | YOLO-World | 自然语言找“吊钩/临边/洞口”等 | 先固定词表 A/B；根许可证 GPL-3.0，进入当前公开仓库前必须做许可证审查。[仓库](https://github.com/AILab-CVC/YOLO-World) |
| 7 | MMAction2 | 动作识别/时间定位 | 依赖和数据标注成本高，暂不作为下一次主线。[仓库](https://github.com/open-mmlab/mmaction2) |
| 8 | CVAT + FiftyOne | 视频标注、难例分析、数据闭环 | 有真实施工视频后再用于微调。[CVAT](https://github.com/cvat-ai/cvat) [FiftyOne](https://github.com/voxel51/fiftyone) |

SAM 2 官方 README 明确支持视频 inference state、多对象 prompt 和传播；MMAction2 官方文档覆盖视频识别、动作定位、时空检测，但依赖 MMEngine/MMCV；CVAT 官方说明社区版可本地部署并支持检测、分割、跟踪标注；FiftyOne 官方仓库定位是数据可视化、评估和错误分析。这些项目适合不同层次，不能全部塞进一次 Demo。[SAM 2 README](https://github.com/facebookresearch/sam2#video-prediction) [MMAction2 README](https://github.com/open-mmlab/mmaction2) [CVAT 文档](https://docs.cvat.ai/docs/getting_started/overview/) [FiftyOne](https://github.com/voxel51/fiftyone)

## 前后端怎么改

### 前端

- 增加“现场总览、对象轨迹、风险事件、证据报告”四个视图。
- 视频画面叠加 track ID 和轨迹线；时间轴点击事件跳回关键帧。
- 提供矩形/多边形区域编辑，保存原始帧尺寸坐标；名称统一用“演示区域/候选区域”。
- 统计只展示真实值：去重对象数、活跃对象数、区域事件数、采样范围。
- 事件卡片展示对象 ID、事件类型、起止时间、关键帧、原始检测、算法版本和人工状态。
- 增加“领导模式/开发模式”：领导看大卡片和时间线，开发人员展开阈值、模型、SHA 和耗用。

### 后端

不改当前 `detections.json`，新增三个版本化输出：

- `tracks.json`：对象 ID、帧号、时间、bbox、检测 ID、类别、分数、轨迹断裂。
- `zones.json`：区域名称、原始尺寸坐标、创建时间、来源。
- `events.json`：事件类型、对象 ID、起止时间、关键帧、算法版本、输入 SHA、人工状态。

复用当前原子写、锁、TXT/ZIP 导出；事件一律初始 `pending`。CPU 检测/跟踪保持基础环境，SAM 2、开放词汇和深度分别放可选 profile，不能污染默认启动链。

## 里程碑和验收

### M6：轨迹与事件（下一步主线）

依赖当前检测契约。固定 8–12 秒视频上至少 3 个对象拥有连续 ID；去重人数与人工抽查一致；轨迹和时间轴能回到原帧；固定区域进入/停留事件可复现；原视频和 `detections.json` SHA 不变；事件全部待人工确认；不调用外部 API。

### M7：SAM 2 视觉增强

选择一个清晰对象，传播 8–12 秒 mask；关键帧无明显漂移；记录 GPU 显存、每帧耗时和失败；不影响 CPU 默认启动；许可证和权重来源登记。

### M8：开放词汇候选

固定 10 个中英文词表，在 10 个固定画面上记录候选框、误报、漏检、耗时和许可证。结果只叫“开放词汇候选”，不自动写违规；若 GPL 或小目标效果不通过，停止集成。

### M9：数据和微调

用 CVAT 标注 20–50 个真实关键帧，用 FiftyOne 做难例分析；训练和演示素材隔离。只有固定难例确实改善、无明显回归并有权重 SHA/回滚方式，才考虑过拟合微调。

## 明确不建议现在做的事

- 不直接把开放词汇命中写成安全违规。
- 不在无标定情况下展示“2 米预警”或真实米数。
- 不用公开视频数据集的 mAP 代替水电一局现场精度。
- 不先上 MMAction2 做施工动作识别；没有施工动作标签，演示风险大于收益。
- 不为“高级感”接多个远程模型；现有 AI 总结只读取事件关键帧，保存和导出不增加 API 调用。

## 本轮检索证据

本轮完成：60 篇论文去重综述，10 篇核心论文全文深读，8 个 GitHub 仓库实际浅克隆/结构与依赖扫描，另核对 CVAT 官方仓库与文档。没有修改业务代码、下载新模型权重或调用付费 API。

详细研究过程保存在本机 `deep-research-output/construction-safety-vision-20261110/` 和 `github-research-output/construction-safety-vision-20261110/`，不进入 Git 历史；本文件是可交接的结论版。
