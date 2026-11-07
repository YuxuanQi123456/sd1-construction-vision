# PPE 影像复核结果契约 v1

使用 SiteWatch 原生 Streamlit 上传与下载，不新增 REST 业务接口。薄适配的文件接口为 `detections.json`，`schema=sitewatch-offline-review-v1`；图像仅传给真实 YOLO 检测器。

| 字段 | 约定 |
|---|---|
| `status` | `processing` / `complete` / `failed`；`complete` 仅表示指定采样处理完成 |
| `source_sha256` / `source_file` | 上传原字节哈希及保留原件；不能用缩放图替代原件哈希 |
| `source_provenance` | 按原件 SHA 匹配登记的作者/许可/来源；未匹配为 `registered=false` |
| `model` | 固定来源提交、权重 SHA、实际类别及设备；本机仅 CPU |
| `settings` | 置信度、缩放、增强、`profile`及视频采样；standard为PPE640、distant为PPE1280加COCO人员640；距离/运动/形状规则均关闭 |
| `frames` | 实际已推理的画面；含帧号、时间、缩放前后分辨率、输入图/框图文件和全部模型框 |
| `detections[].class_name` / `class_id` | 模型实际输出类别；禁止由未检出正类补造 NO-* |
| `confidence` / `bbox_xyxy` | 模型分数和浮点框；坐标相对 `detection_dimensions_wh`，不是原图尺寸 |
| `bbox` | 四舍五入后用于上游绘图的像素框 |
| `ppe_overlay_file` / `overlay_file` | 分别为 PPE 筛选框图与完整类别框图；筛选不删除原始检测 |
| `review_overlay_file` | 默认显示的人员加PPE框图；按大框先、小框后复用原绘图函数 |
| `frames[].model_branches` | 各固定模型去重前原始预测；伴随COCO只允许class0/person，不能充作帽子预测 |
| `manual_review_detection_count` | 跨所有采样帧的直接 NO-* 框次数；不是人数、独立事件数或违规数 |
| `video.timestamp_basis` | 帧序号/容器 FPS 估算，不保证可变帧率的精确 PTS |
| `video.stop_reason` | 指定时长、正常文件末尾、不可验证帧数的 EOF，或解码提前失败；中途失败不得报告完成 |

`preserve_resolution=True`为原片保留模式：不在检测前缩小/增强，PNG输入逐像素等于解码源帧，原件文件字节保留。`settings.max_long_edge=null`、`saved_frame_format=png`；帧`source_dimensions_wh`等于`detection_dimensions_wh`。模型内部仍按明确记录的`inference_imgsz`预处理。原尺寸画框的`annotation_scale`只调整标签线宽/字号，不改预测数值。完全相同的像素可在多个图像字段共用一个路径，下载按该路径原字节返回。

证据 ZIP 至少含上传原件、`detections.json`、来源元数据、全部已完成采样的输入图和两类框图。未知用户素材不套用样例许可。坏图/坏视频/权重缺失或不匹配须可见失败，保留已完成证据；不得静默退化普通 COCO。当前失败证据保存本机，网页成功下载入口不用于伪装失败任务完成。

标准模式不加载人员伴随模型；远景模式逐项校验伴随权重SHA/大小/词表，失败直接报错，不以COCO替代坏PPE模型。合并只以原生IoU过滤与PPE整人框重叠的COCO整人框，不让头部小框压掉整个人；所有PPE框保留，原始分支另存。推理与本帧快照返回在同一锁内，序列化不读取后续帧可能覆盖的共享状态。

NO-* 和内部 `ppe_violation` / `ppe_compliant` 字段均非合规结论。当前允许按用户选定素材调参/微调演示；样例表现和独立泛化验证分别记录。
