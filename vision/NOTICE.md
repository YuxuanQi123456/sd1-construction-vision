# 来源与改动

官方演示来自 [QwenLM/Qwen3-VL](https://github.com/QwenLM/Qwen3-VL)，固定提交 `96588727e44c78b25ba03ea03b8e12f7e64fd0da`。未改原版 [web_demo_mm.py](upstream/web_demo_mm.py) 与 [Apache-2.0 许可](upstream/LICENSE) 保存在 `upstream/`；版本与文件哈希见 [upstream-lock.json](config/upstream-lock.json)。

当前候选模型为 [Qwen/Qwen3-VL-4B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-4B-Instruct)，Apache-2.0。权重与配置固定 revision `302de2efb1dd6de1ee943eb1277dc6875550563d`，模型卡固定 revision `0196dc7bb23f3c742616147c3254d0e4f1207787`。13 个原始文件从 Qwen 官方 ModelScope 仓库取得，并与官方 Hugging Face 哈希逐项比对通过，见 [qwen4b-files.json](config/qwen4b-files.json) 与 [历史来源验证说明](../docs/ASSET_RETENTION.md)。本机生成的 NF4 权重为 2,874,045,174 字节，SHA256 `69d2f15d01e20744dcdb78ed044d06c11592264ae20337aacd0073b3590768d2`，方法及来源见 [当前资源清单](../config/runtime-assets.json)。

历史 2B 基线来自 [Qwen/Qwen3-VL-2B-Instruct](https://huggingface.co/Qwen/Qwen3-VL-2B-Instruct)，revision `89644892e4d85e24eaac8bacfd4f463576704203`，Apache-2.0；量化来源见 [历史记录清理说明](../docs/ASSET_RETENTION.md)。两种 NF4 版本均由官方原始权重经本机 bitsandbytes 转换，不来自第三方量化发布者。

视频适配参考 Transformers 4.57.6 的 `BaseVideoProcessor.fetch_videos` 与 PyAV 读取函数；保留 Qwen 处理器的抽帧规则、视觉处理、时间戳编码、模型 `generate` 与 Gradio 问答流程。本地改动包括 4GB 显存的 NF4 加载、抽帧与像素预算、低内存解码和容器规范化、中文提示、串行推理及清理、素材入口和归属、采样时间说明。补丁见 [local-demo.patch](patches/local-demo.patch)。没有固定答案表、预写风险事件或模拟模型输出；来源说明和人工观察不喂给模型作为答案。

公开素材的完整下载地址及归属保存在 [samples.json](config/samples.json)，新增照片哈希另见 [照片来源登记](../sitewatch/media-sources.json)。

| 素材 | 作者与来源 | 许可 |
|---|---|---|
| 桥下轨道施工视频 | [ŠJů / Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Rekonstrukce_smy%C4%8Dky_Florenc,_p%C5%99en%C3%A1%C5%A1en%C3%AD_koleje.webm) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| 室外轨道施工视频 | [ŠJů / Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Praha-Hostiva%C5%99,_p%C5%99en%C3%A1%C5%A1en%C3%AD_kolejnic_kolejov%C3%BDm_bagrem.webm) | [CC BY 4.0](https://creativecommons.org/licenses/by/4.0/) |
| 挖掘机装车视频 | [KEmel49 / Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Excavator_digging_land_and_loading_truck.webm) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| Working the Grinder 近景照片 | [Mungai Kiroga / Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Working_the_Grinder.jpg) | [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/) |
| 跑道施工人员操作钻孔设备照片 | [NIOSH / Wikimedia Commons](https://commons.wikimedia.org/wiki/File:Runway_construction_worker_operating_a_dowel_drilling_machine.jpg) | [公有领域：美国联邦政府作品](https://commons.wikimedia.org/wiki/File:Runway_construction_worker_operating_a_dowel_drilling_machine.jpg#Licensing) |

原始素材不修改；分析缓存可能进行容器、格式和分辨率转换，抽帧图片是原视频的派生内容。对外分发缓存、抽帧或标注图时应保留来源、作者、许可及修改说明，CC BY-SA 素材的改编内容遵守相同方式共享要求。

全部示例为公开实拍，非水电一局现场，没有权威事故/违规标签。素材标题及作者说明提供来源语境，不能作为隐患判定真值；本项目人工观察与模型原始输出分开记录。

本地NF4 checkpoint与原始13文件的字节不同。跨机器恢复应以`config/runtime-assets.json`中的本地实际文件哈希为准；原始来源清单仅用于追溯。Qwen3-VL是千问视觉语言模型，当前在YOLO定位后查看头部裁图并给出第二意见。
