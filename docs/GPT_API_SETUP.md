# GPT-6.1 Sol Max 头部复核

YOLO 继续在本机检测人员与防护装备。复核默认通过你的 GPT API 查看所选头部裁图、给出第二意见；不需要千问权重或本地 GPU。原检测类别和分数保留，文字意见没有校准置信度。

用户选择“gpt6.1solmax”对应官方 `model=gpt-6.1-sol` 与 `reasoning.effort=max`，支持图片输入。[模型说明](https://developers.openai.com/api/docs/models/gpt-6.1-sol)、[图片输入](https://developers.openai.com/api/docs/guides/images-vision)、[推理配置](https://developers.openai.com/api/docs/guides/reasoning)。

## 填写 Key

在项目根目录运行一次：

```bash
python3 scripts/manage_review_api.py init
```

用编辑器打开 **`config/review-api.local.json`**，把 `api_key` 的空字符串填成你自己的 Key。例如：

```json
{
  "provider": "openai",
  "base_url": "https://api.openai.com/v1",
  "model": "gpt-6.1-sol",
  "reasoning_effort": "max",
  "api_key": "在你自己机器上填写",
  "timeout_seconds": 180,
  "max_output_tokens": 4096
}
```

本机配置已被 Git 忽略，每个开发者各填自己的 Key；初始化不会覆盖已填写内容。不要把真实 Key 写入 `review-api.example.json`、聊天、截图或 Git。程序只读取本项目的配置，不借用其他项目或通用环境里的 Key。

默认地址为 OpenAI 官方 API。如果使用代理或第三方服务，修改 `base_url` 与服务方提供的准确 `model` 名；该服务必须支持 **Responses API 的图片输入及 Max 推理**，仅兼容文字聊天不足以完成本流程。未知接口未验证，不自动切换模型或降低推理强度。

## 启动与验证

恢复、安装仍使用 CPU 的 `ppe` profile，见 [运行说明](RUNTIME_SETUP.md)。环境准备好后：

```bash
python3 scripts/manage_review_api.py status
python3 scripts/manage_ppe.py start --wait
```

Windows 的“启动施工视觉.cmd”会初始化本机配置并按所选 provider 启动。API 模式不启动本地千问；Key 为空时基础检测仍可运行，复核按钮给出配置提示。填好配置后重新操作页面即可读取新值。

打开 `http://127.0.0.1:8767`，先检测一张照片或视频采样帧，再选头部框点击“复核所选头部”。只有点击后才向配置的地址发送未画框头部 PNG 裁图和固定问题，不发送整段视频、原检测类别或预期答案。请求使用 `store=false`，并消耗你的 API 额度；第三方服务自身的数据处理规则以其实际实现为准。

状态“已配置”只说明具备发起请求的配置；是否连通、Key 是否有效及效果以实际调用为准。错误、超时、拒答和输出不完整会保留失败记录，不伪造结论、不自动发起额外计费请求。结果与 ZIP 记录实际模型、Max 配置和回答来源，不把旧本地千问回答标成 GPT 输出。

没有 Key 时只能完成本地模拟接口与 CPU/UI 集成验证；真实 GPT 识别效果留待填 Key 后实测。若要使用原本地后端，把 provider 明确设为 `qwen_local`，再按原 full 环境要求恢复千问。
