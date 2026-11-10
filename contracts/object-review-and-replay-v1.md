# 局部人工复核与视频回放 v1

## 输入与不变量

输入为本次已完成的 `detections.json`、登记的原始影像和帧索引。原视频、原始检测、类别与分数不改。检测框坐标以 `detection_dimensions_wh` 为基准，裁图映射回原始照片/视频解码尺寸，无增强或生成细节。人工矩形单独标为 `manual_region`，不是模型新框。

## 人工对象记录

`object-reviews/decisions.json` 保存 schema `visual-object-review-v1`，包含 `decisions` 和追加 `history`。每个目标记录真实帧、时间、检测索引或人工区域、原图/裁图坐标与SHA；头部和上身参考只表示裁剪位置。`target_state` 为 pending/confirmed/dismissed/uncertain；`helmet_state`、`vest_state` 为 pending/visible/suspected_missing/uncertain，`judgement_source` 固定 human。备注最多1000字，显式保存；普通裁图浏览不保存意见，不调用AI。

## 关键帧索引

事件 `source_detections_sha256`、总结 `detections_sha256` 必须匹配本次检测，引用的帧位置、帧号、输入文件名必须有效；导航只修改当前任务的画面选择。事件和人工复核均不自动等于违规。

## 连续回放

显式触发 `build_video_replay`，逐帧顺序调用同一检测器、阈值和输入设置。`video-replay/frames.jsonl` 保存每个真实解码帧的框、原始分数、轨迹和时间；不插值造框。独立MP4以H.264重新编码叠框，原视频不变；源奇数尺寸仅为yuv420p补齐边界，manifest分别登记。覆盖时长以当前检测 `max_seconds` 为限，时间仍按帧号/容器FPS估算。

帧数、原文件、检测JSON、MP4、JSONL校验通过才发布 `replay.json` 的 complete 状态。失败不发布部分成片；旧成功可复用但需重新校验全部SHA。回放轨迹与采样轨迹是独立运行，本次影像内有效，不跨摄像头识别人。
