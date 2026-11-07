# 清晰演示素材与原片保存接口 v1

`sitewatch/demo-media.json`从`PROJECT_ROOT`读取，`schema=demo-media-v1`，`entries`含id/title/media_type/relative_path/sha256/bytes/author/license/license_url/source/recommended_profile，可选recommended_model_id（默认sitewatch）、width/height/fps/duration_seconds/description。路径必须在项目根内，读取时校验文件字节数和SHA。作者/标题只用于署名，不进入模型输入。手动模型/场景选择优先于素材推荐。

`review_file(..., preserve_resolution=False)`保持旧调用兼容；True禁止同时增强，不预先缩小解码图，以PNG保存未画框输入和框图。settings记录preserve_resolution/max_long_edge/saved_frame_format，帧source_dimensions_wh等于detection_dimensions_wh。模型内部仍按所选profile的inference_imgsz处理，这与显示/保存尺寸分开。

同形状且逐像素完全相同的框图可与已有文件共用路径，JSON各字段始终指向其实际像素；不保证input/overlay/PPE/review四字段文件名不同。原始上传文件始终逐字节保留。主界面可按屏幕缩放，但原尺寸PNG和原始视频的下载须与服务器原件SHA一致。

保留自己上传和旧视频样例；新增素材库入口、大图/对照切换。切素材、质量、实际模型/配置时不得显示旧检测/Qwen结果。建议默认开启保留原片画质，关闭有效图像增强；下载按钮不触发重新推理。
