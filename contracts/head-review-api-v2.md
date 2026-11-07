# 头部第二意见：可配置 GPT API v2

2026-11-08 用户指定 GPT-6.1 Sol、Max 推理，API Key 后填。仅替换既有头部第二意见后端；YOLO 原分数/类别/裁图/导出不改，保留显式 `qwen_local` 选项，不自动降级。

## 本机配置

`config/review-api.example.json` 随代码；`config/review-api.local.json` 为忽略文件，默认 `provider=openai`、`base_url=https://api.openai.com/v1`、`model=gpt-6.1-sol`、`reasoning_effort=max`、`api_key=""`、`timeout_seconds=180`、`max_output_tokens=4096`。本轮不读取其他项目或通用环境中的 Key。初始化不能覆盖已有本机配置。

官方依据：[模型/Max/图片输入](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[Responses 图像输入](https://developers.openai.com/api/docs/guides/images-vision)、[推理参数](https://developers.openai.com/api/docs/guides/reasoning)。`max` 是 `reasoning.effort`，不是模型名的一部分。第三方可修改 base_url/model，但须实现 Responses 图像协议；不宣称任意兼容站均已验证。

## 稳定接口与边界

- 新模块 `sitewatch/app/review_api.py`：`load_review_config(project_root)` 返回内部配置（包含 Key，仅内部使用）；`api_backend_status(project_root)` 返回安全的 `ready/provider/model/reasoning_effort/url/config_path/error` 等状态，不含 Key，不访问网络。`request_image_opinion(crop_path, project_root, prompt)` 仅在用户点击后发送请求，返回安全后端信息、回答原文及计量/响应 ID 等白名单元数据。
- `region_review.backend_status` 默认分派 API；`classify_crop` 默认通过 API，再沿用 `parse_option`/LABELS/空置信度与既有证据字段。显式 `qwen_local` 走原 Gradio、端口/PID/socket/固定权重验证。配置错误与未知 provider 不回退到另一模型。
- `ready` 对 API 仅表示配置允许发起调用，须同时标记未进行连通性验证；缺 Key 不触网、不导入 Gradio、不要求千问权重。页面准确提示配置状态，保存结果按实际 backend 来源标注。
- Responses：`POST <base_url>/responses`，`model=gpt-6.1-sol`，`reasoning={effort:max}`，`store=false`，一条消息包含原冻结提示与未画框 PNG 裁图的 Base64 `input_image`；不发送检测类别/分数/预期答案。不传 temperature、工具、历史答案；每次新请求。
- 默认 TLS 验证，拒绝跨站重定向；base_url 不允许用户信息、query、fragment，非 HTTPS 仅允许 localhost/loopback 调试。限制响应与裁图体积，超时/HTTP错误/不完整或拒答响应可见失败；不自动重发计费请求，不用空回答伪造成功。
- API Key 不进状态、错误、日志、证据、Git 或交接包。错误与返回文本须脱敏；只保存白名单响应字段，不保存原始请求头或全量外部 JSON。
- 原始 detections.json 字节保持；每次调用保存裁图/提示/实际请求模型/推理强度/回答/空概率、成功或失败 attempt。Max 是用户选定值，不擅自降档。

验收：标准库本地 HTTP fixture 覆盖原 PNG 请求、Max 与 store=false、缺 Key 零请求、错误与脱敏、未知 provider、重定向、超时、不完整/拒答/无文本；实际 CPU 检测与页面配置状态/复核/导出集成另验。缺真实 Key 时只标接口与模拟服务通过，真实 GPT 效果待填 Key 验证。
