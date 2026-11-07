# 千问视觉问答与区域第二意见

Qwen 是千问，这里使用 **Qwen3-VL-4B-Instruct 的本地 NF4 量化版**，它能读取图像/视频并生成文字。主流程的 YOLO 负责检测人员、防护装备、画框和给出检测分数；千问查看用户选中的头部画面，提供文字第二意见，原检测分数和类别保留。PPE 检测可以只用 CPU 独立运行，千问复核需恢复 full 资源和 GPU 环境。

本目录复现 [Qwen3-VL 官方 Web Demo](https://github.com/QwenLM/Qwen3-VL)，保留真实模型推理和 Gradio 对话。源码、权重及素材许可见 [NOTICE.md](NOTICE.md)。它属于既有视觉流程；Agent 业务由其他工作区承担。

**通用自动隐患判断业务验收不通过。** 原机曾完成 2B / 4B 真实推理、4B 网页 14 项技术检查、三片五问、两张近景照片及追问，但仍漏识别远景吊运，出现设备/品牌错误与过度自信。主流程因此使用专用 PPE 初筛和人工复核，千问仅提供可核对的第二意见。历史结论见[进度](../docs/PROGRESS.md)；已清理大证据记录的说明见[资源保留](../docs/ASSET_RETENTION.md)。

## 新目录恢复

先按[新目录运行说明](../docs/RUNTIME_SETUP.md)准备 Ubuntu / WSL2、Linux x86_64、Python 3.12、NVIDIA 驱动及 GPU：

```bash
python3.12 scripts/restore_runtime_assets.py --profile full --plan
python3.12 scripts/restore_runtime_assets.py --profile full
python3.12 scripts/bootstrap_runtime.py --profile full --no-cache-dir
python3.12 scripts/restore_runtime_assets.py --profile full --verify-only
```

以上命令在仓库根目录执行。[运行资源 Release](https://github.com/YuxuanQi123456/sd1-construction-vision/releases/tag/runtime-20261107-v1) 可用性以正式发布为准。统一清单 `config/runtime-assets.json` 固定当前 NF4 配置、tokenizer、完整权重及分片的实际 SHA256；恢复时保留原字节，受独立分发限制的素材从原站下载并校验。

新安装在 `.runtime/portable-env/`，`vision/.venv/bin/python` 是仓库内相对链接，不再复用原机 `/home/meg` 的 Torch。迁移基线是 Torch 2.8.0 / torchvision 0.23.0 cu128，Transformers 4.57.6；直接依赖见 `config/bootstrap-full.txt`。环境脚本完成后会验证依赖与 CUDA/NF4 算子，目标机仍须实际加载模型并完成一次业务推理。当前尚无完整全新机器安装/GPU 验收结论；原机服务保持停止。

## 启动与操作

资源和环境就绪后，在仓库根目录的 Linux 终端运行：

```bash
env -u PYTHONPATH -u PYTHONHOME -u PYTHONUSERBASE python3.12 vision/scripts/manage.py start --wait
python3.12 vision/scripts/manage.py status
python3.12 vision/scripts/manage.py stop
```

辅助问答页面为 **http://127.0.0.1:8766**。Windows 可双击本目录的 [启动视频AI.cmd](启动视频AI.cmd)，它按脚本目录定位仓库并调用默认 WSL；默认发行版须具备上述环境。结束时双击 [停止视频AI.cmd](停止视频AI.cmd)。关闭浏览器不会卸载模型，关机后要重新启动。主流程入口为 `http://127.0.0.1:8767`，详见[开发交接](../docs/DEVELOPER_HANDOFF.md)。

1. 选择公开实拍样例并点击“载入样例（开启新会话）”，或上传自己的素材。
2. 输入问题，先核对人员、设备及作业描述。视频回答末尾附实际抽样时间；照片没有视频时间依据。
3. 追问可见依据与无法确认的内容，对照原画面人工复核。
4. 换素材时载入另一项样例，或先清空历史再上传。每段会话只分析一张图片或一个视频。

[samples.json](config/samples.json) 包含桥下轨道、室外轨道、挖掘机装车三段视频，以及角磨机和 NIOSH 钻孔作业两张照片。全部为公开实拍，非水电一局现场；作者、来源、许可显示在页面，模型只收到媒体与通用问题，来源说明不作为答案输入。

启动器优先选择完整的 `downloads/qwen3-vl-4b-nf4`，旧 2B 路径仅作为历史兼容候选，本次 Release 不要求它们。实际模型以 `.runtime/vision-process.json`、`.runtime/vision-server.log` 和启动参数为准。`status` 的 `ready` 只表示本项目进程与网页配置就绪，不能替代真实生成验证。

## 当前边界

- 原机为 RTX 3050 Laptop 4GB；视觉与语言线性层均做 NF4 量化，FP16 计算，使用本地模型，无云端推理接口。量化并不等于对演示样例重新训练。
- 网页配置为视频 16 帧、总像素预算 `16×448²`，图片预算 `1024²`，最多生成 384 tokens；提示见 [review-prompt-neutral.txt](config/review-prompt-neutral.txt)。处理器按比例缩放和取整，预算不代表固定长边或完整原片细节。
- 视频限制 60 秒、200MB，顺序解码后只保留抽样帧。快速动作、小目标、防护装备细节和遮挡关系可能漏识别；照片也不能补足画面外信息。
- 输出供人工复核。人员与机械同场不等于违规，模型不能凭画面可靠测量真实距离或判定法规条款。这批素材没有权威事故/违规标签，不能据此报告准确率、召回率或“全场安全”。
- 时间按帧序号/平均帧率估算，可变帧率可能有偏差。实际抽样位置只证明读取了哪些画面，不能证明风险定位准确。
- 原机的 4B 网页五次生成曾为 13.417–32.015 秒，启动等待曾为 177.418 秒；这些历史数字不作为其他机器的耗时或显存承诺。历史详情已按用户要求清理，结论保存在进度记录。

## 版本、来源与验证

未改官方源码在 [upstream/](upstream/)，本地改动在 [patches/local-demo.patch](patches/local-demo.patch)。官方源码及历史 2B 版本见 [upstream-lock.json](config/upstream-lock.json)。官方 4B 来源为 `Qwen/Qwen3-VL-4B-Instruct`，revision `302de2efb1dd6de1ee943eb1277dc6875550563d`，许可 Apache-2.0。

[qwen4b-files.json](config/qwen4b-files.json) 的 13 文件锁对应**官方原始模型**，历史上曾逐项下载核验，不能拿来校验本地 NF4 结果。当前量化权重为 **2,874,045,174 字节**，SHA256 `69d2f15d01e20744dcdb78ed044d06c11592264ae20337aacd0073b3590768d2`，当前配置和其他文件以 `config/runtime-assets.json` 为准。原始大权重已按用户要求清理，本次恢复现有 NF4 无需重新量化；如需重做量化，先通过 `python3 vision/scripts/download_qwen4b.py` 按原始清单恢复，再重新验证。

原机 [requirements.lock.txt](config/requirements.lock.txt) 是历史已装环境记录，不是新机器安装入口。旧四包下载脚本也不能替代新的完整依赖引导；迁移使用[运行说明](../docs/RUNTIME_SETUP.md)与 bootstrap 版本配置。

本次脚本验证见 [R01_PORTABLE.json](../docs/validation/R01_PORTABLE.json)，其中真实临时 HTTP / 离线资源恢复与轻量 venv 测试分别记录，未冒充完整模型安装或 GPU 推理。历史网页技术验证、模型真实生成与业务效果也分别验收；返回文字并不代表判断正确。自动化浏览器使用隔离 profile，不占用日常浏览器会话。

日志在项目 `.runtime/vision-server.log`，进程记录在 `.runtime/vision-process.json`。若 CUDA 不可用，先在具备 GPU 访问的 WSL 终端检查驱动与环境；不要靠反复双击启动来处理依赖或显存问题。
