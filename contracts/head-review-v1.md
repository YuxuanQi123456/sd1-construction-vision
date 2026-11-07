# 头部区域 AI 第二意见 v1

> 历史v1记录：本地Qwen已于2026-11-08移除。当前运行后端与错误语义以[GPT API v2](head-review-api-v2.md)为准；下列Gradio服务条款不再适用于当前代码。

同一施工影像复核范围内复用已运行的Qwen官方Gradio应用，不更改检测分数，不自动认定违规。`region_review.py`接口冻结如下，供原生SiteWatch页面调用：

- `head_indices(frame)`：返回该帧直接头部检测的原始索引，支持Hardhat/NO-Hardhat及已登记同义类，不从Person位置猜头部。
- `backend_status(project_root)`：`ready`、本机URL和已校验模型信息；核对Qwen4B进程启动参数、PID实际持有的127.0.0.1:8766监听socket及固定NF4权重SHA。权重摘要按文件大小/mtime缓存，首次以流式读取核验，不占用整块权重内存。
- `review_head_region(review_dir, frame_position, detection_index, project_root)`：同步执行，返回`ppe-head-second-opinion-v1`记录；原始`detections.json`不改写。保存未画框的采样JPEG裁剪、其SHA、像素框、原始检测和原生接口完整返回。
- `latest_region_review(review_dir, frame_position, detection_index)`：只读本次检测对应的最新成功/失败记录。没有记录返回None；不能把旧帧或旧素材结果显示到新任务。

返回字段：`status`为complete/failed；`opinion.raw_answer`保留原文，`option`仅接受单字母A/B/C/D或冻结提示中该选项的逐字展开（如A＝明确佩戴工业安全帽），其它/含歧义文字返回None；`label`为中文显示，`classification_confidence=null`，不把定位检测分数说成语言模型置信度。`comparison`只说明两模型agree/disagree/uncertain，不是法规标签。

输入是当前帧实际直接头部检测框，四边增加20%上下文并裁到画面范围。二次模型读取页面保存的未画框帧并记录真实输入SHA：兼容模式为解码/缩放JPEG；保留原片模式为原尺寸PNG，后者与该次解码像素相等。不传画框图、原检测类别、作者说明或人工预期答案。每次新Gradio会话，原生`/add_file`后`/submit_and_predict`，不改Qwen生成或模型算法。

记录保存在`head-reviews/frame-...-detection-.../attempts/<唯一ID>/`；裁剪完成后开始的服务调用失败也保留，`latest.json`原子更新。读取/坐标等预检失败在调用前拒绝并显示错误，不创建模型调用记录。证据ZIP包含嵌套文件。服务不可用、错模型/权重、裁剪无效、上传30秒或模型作业120秒超时必须可见失败，不生成替代答案。超时取消为后台best effort，取消HTTP时限2秒；服务可能仍需完成正在执行的生成，不能声称已经强制停算。

解析只剥离既有图片后端追加的逐字固定尾注，不截断任意`---`；含额外判断或互相冲突选项的正文返回None。客户端和启动环境关闭Gradio/Hugging Face telemetry。

检测器依旧默认SiteWatch。`Detector(conf_threshold=0.4, model_id='sitewatch')`保持原调用兼容，可显式选`constructelligence-v03`做候选对照；两个版本均强制清单SHA/实际names校验，不静默降级。`detector.provenance`写所选模型真实来源，`Detection.source`区分模型；`canonical_class`仅是声明的类ID映射，不是补造预测。仅候选选择不表示默认替换门槛通过。
