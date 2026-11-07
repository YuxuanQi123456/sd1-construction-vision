# 施工视频 AI 隐患审查

用户已批准的视觉功能。复现 [Qwen3-VL 官方 Web Demo](https://github.com/QwenLM/Qwen3-VL)，调用本机真实模型，对施工照片/短视频回答“有哪些人员、机械和作业”“哪些情况值得复核”“依据是什么”。源码、权重及素材来源见 [NOTICE.md](NOTICE.md)。照片用于查看近景工具、作业和可辨认的防护装备；视频用于查看动作变化、物体搬运及人员与机械的相对位置。两种输入都需要人工对照原始画面。

**截至 2026-11-06，隐患判断业务验收不通过。** 官方 4B 原始文件、量化与三视频命令行推理已完成，仍漏识别远景吊运并出现不准确细节。2B 网页的 14 项技术流程检查曾通过；当前 4B 网页采用另一组像素预算和精简中性提示，首轮图集取证超时已修复，最终三片五问14项技术检查全部通过；两张近景照片及照片追问也已实跑。模型仍有远景漏识别、设备类型/品牌错误与过度自信，不能作为自动隐患判定。阶段状态见 [进度](../docs/PROGRESS.md)。

## 启动与操作

Windows 双击本目录的 [启动视频AI.cmd](启动视频AI.cmd)，等待模型加载后使用 Windows 默认浏览器打开 **http://127.0.0.1:8766**。管理脚本在后台启动服务，关闭页面或启动终端不会卸载模型；结束使用时双击 [停止视频AI.cmd](停止视频AI.cmd)。脚本目前固定 WSL 发行版 `Ubuntu-24.04` 和本机项目路径，换位置或电脑需修改这两项。

也可以在项目根目录的 WSL 终端执行：

```bash
python3 vision/scripts/manage.py start --wait
python3 vision/scripts/manage.py status
python3 vision/scripts/manage.py stop
```

1. 从“选择公开实拍样例”选择照片或视频，点击“载入样例（开启新会话）”；也可上传自己的素材。
2. 输入问题并发送，先核对人员、设备、物体及作业是否描述正确。视频回答末尾附本轮实际抽样时间；照片没有视频时间依据。
3. 继续追问“这项判断的可见依据是什么？哪些情况无法确认？”，对照原始素材复核。生成完成只代表推理和交互结束。
4. 换素材时载入另一项样例，或先清空历史再上传。每段会话只分析一张图片或一个视频。

样例清单共五项：桥下轨道施工、室外轨道施工、挖掘机装车、Mungai Kiroga 拍摄的角磨机近景、NIOSH 钻孔作业照片。全部为公开实拍，非水电一局现场。作者、来源和许可显示在页面并记录于 [samples.json](config/samples.json)；模型仅收到素材和通用问题，不把作者说明或人工观察作为识别答案。

启动器优先加载 `downloads/qwen3-vl-4b-nf4`，缺少其 tokenizer 时依次回退到 2B NF4、2B 原始目录。实际模型以 `.runtime/vision-process.json` 和 `.runtime/vision-server.log` 为准；不要仅凭页面标题认定已使用 4B。`status` 的 `ready` 表示本项目进程存活且网页配置可读，真实生成另验。本轮4B的`start --wait`等待就绪实测177.418秒；历史2B约147秒，两者均不是其它机器的性能承诺。

## 当前边界

- 本机 RTX 3050 Laptop 4GB。当前启动候选为官方 `Qwen3-VL-4B-Instruct` 的本地 NF4 量化版，视觉和语言线性层均量化；未使用云端推理接口。2B 与视觉层 FP16 对照保留为历史证据。
- 当前网页配置为 16 帧、视频总像素预算 `16×448²`、图片像素预算 `1024²`，最长生成 384 tokens，提示为 [review-prompt-neutral.txt](config/review-prompt-neutral.txt)。预算由 Qwen processor 按比例缩放和取整，不表示固定长边分辨率。这组网页配置已完成14项完整技术回归，隐患判断业务仍不通过。
- 视频限制 60 秒、200MB；顺序解码后只保留抽样帧，不是逐帧语义审查。快速动作、小目标、防护装备细节和遮挡关系可能漏识别；近景照片也不能补足画面外信息。
- 输出为人工复核候选。人员与机械同场不等于违规；模型不能仅凭画面可靠测量真实距离或判定法规条款。
- 页面时间按帧序号/平均帧率估算。历史 2B/8 帧样例的 24 个位置曾与实际帧 PTS 核对一致；其他采样配置和可变帧率素材需另核。采样位置证明读取了哪些画面，不证明每项风险已准确定位。
- 这批公开视频没有权威事故/违规标签，不能据此报告准确率、召回率或“全场安全”。
- 4B/16 帧/512 预算/v2 提示命令行实测三片为 18.168、17.501、19.825 秒，首次从原始权重加载约 351.843 秒，最高分配显存约 3.55GB。这些数字仅对应 [V04/model-probe-16frames.json](../evidence/V04/model-probe-16frames.json)，不能作为当前 448 预算网页的耗时承诺。

## 版本与运行环境

原版源码在 [upstream/](upstream/)，本地改动在 [patches/local-demo.patch](patches/local-demo.patch)。官方源码和历史 2B 版本见 [upstream-lock.json](config/upstream-lock.json)；4B 的逐文件版本与哈希见 [qwen4b-files.json](config/qwen4b-files.json)，13 个文件全部通过校验，记录见 [official-source-verified.json](../evidence/V04/official-source-verified.json)。

当前可运行的4B量化结果在 `downloads/qwen3-vl-4b-nf4`，权重为 **2,874,045,174 字节**，SHA256 为 `69d2f15d01e20744dcdb78ed044d06c11592264ae20337aacd0073b3590768d2`；方法与来源见 [quantized-checkpoint.json](../evidence/V04/quantized-checkpoint.json)。2026-11-06 按用户清理磁盘要求，移除了已完成量化的2B/4B官方原始大权重和重复下载分片，保留全部小配置、来源哈希、2B/4B量化模型及PPE模型，释放12.35GiB，见 [清理记录](../evidence/C01/cleanup.json)。因此 `downloads/qwen3-vl-4b-source` 当前不含原始权重；重新量化前先运行 `python3 vision/scripts/download_qwen4b.py` 恢复并核验。2B原始权重的固定revision和SHA在 `config/upstream-lock.json`。普通2B NF4 probe仍可运行，`--save-quantized` 须先恢复对应原始权重。历史来源验收描述的是当时已实际下载并校验，不代表当前仍保留原始大文件。

本机环境在 `vision/.venv`，不依赖 `/tmp` 虚拟环境。PyTorch/CUDA 通过 `.pth` **只读复用** `/home/meg/venvs/qyx_patent/lib/python3.12/site-packages`，未修改该环境；4B probe 记录 Torch `2.14.0+cu130`。其余已装包记录在 [requirements.lock.txt](config/requirements.lock.txt)。迁移时需自行安装适配目标机器的 PyTorch/CUDA 并重新验证 GPU 算子和模型推理，不能直接复制这个外部引用路径；尚未完成一台全新机器的安装验收。

以下是已有本机环境的四包恢复路径，已安装依赖和 Torch 引用是前提，并非新电脑一键安装方案：

```bash
python3 vision/scripts/download_wheels.py
vision/.venv/bin/python -m pip install --no-index --find-links downloads/vision-wheels bitsandbytes==0.49.2 accelerate==1.15.0 torchvision==0.29.2 gradio==5.49.1
vision/.venv/bin/python -m pip check
vision/.venv/bin/python vision/scripts/probe_model.py --preflight
```

下载脚本仅恢复上述四个固定软件包，文件必须与官方 PyPI SHA256 一致；已验证记录见 [V01/runtime-restore.json](../evidence/V01/runtime-restore.json) 和 [V01/wheels-verified.json](../evidence/V01/wheels-verified.json)。版本锁是本机已装环境记录，不能代替跨机器兼容性实测。4B 原始文件可用 `python3 vision/scripts/download_qwen4b.py` 按逐文件清单恢复并校验；重新量化和推理还需可用 GPU、显存及磁盘空间。

日志位于项目 `.runtime/vision-server.log`，进程记录位于 `.runtime/vision-process.json`。若显示 CUDA 不可用，先在具备 GPU 访问的普通 WSL 终端检查；反复双击不会解决 GPU 权限或依赖缺失。启动脚本通过 Windows 默认浏览器打开页面。

## 验证与证据

| 证据 | 已验证内容 | 业务结论/适用范围 |
|---|---|---|
| [V01/model-probe.json](../evidence/V01/model-probe.json)、[人工观察](../evidence/V01/OBSERVATIONS.md) | 2B 首轮真实推理、耗时、显存和采样；人工 12 帧预览 | 重复、环境误判与漏识别保留；人工预览不是全片审查 |
| [V01/conversation-recovery.json](../evidence/V01/conversation-recovery.json) | 9 项会话回滚边界检查 | 使用假模型，仅验证程序状态 |
| [V02/run-08-final/report.json](../evidence/V02/run-08-final/report.json) | 2B/8 帧网页，14 项检查通过，五次真实生成 15.620—22.832 秒；上传、追问、换片、清空及三片显示 | 技术通过；风险判断在人工对照中不通过，不能继承到 4B 配置 |
| [V03/REVIEW.md](../evidence/V03/REVIEW.md) | 2B/16 帧/512、视觉层 FP16、前 8 秒密采样、原生输入等价性和图片入口对照 | 多种调整均未解决远景吊运漏识别；图片生成成功也不等于隐患识别通过 |
| [V04/EVALUATION_PLAN.md](../evidence/V04/EVALUATION_PLAN.md)、[4B probe](../evidence/V04/model-probe-16frames.json) | 固定口径后实跑同三片，16 帧/512/v2 提示；量化与生成完成 | 仍漏吊运，部分细节不准；隐患判断业务不通过 |
| [V04/browser-failed-gallery/report.json](../evidence/V04/browser-failed-gallery/report.json) | 4B/16 帧/448/neutral 网页首轮，12 项已记录检查通过、五次真实生成 13.388—33.905 秒 | `Page.set_content` 全尺寸抽帧图集取证页面超时，整轮退出 1；该失败轮未完成最终清空及原始输出检查；后续完整通过见下行 |
| [V04/browser/report.json](../evidence/V04/browser/report.json) | 修复取证后14项技术检查通过、三片五次真实生成13.417—32.015秒，含追问、切换、清空及实际SSE | 技术通过；风险判断仍不通过，详见[V04阶段验收](../evidence/V04/ACCEPTANCE.md) |
| [V04/photo-sources.json](../evidence/V04/photo-sources.json)、[角磨机图片报告](../evidence/V04/grinder-photo/report.json) | 两张新增照片来源与哈希；两预设解码显示；角磨机照片真实生成 24.044 秒，技术通过 | 识别角磨机、板材和明显粉尘，可供现场防护复核；“无…等防护装备”措辞过宽，只作辅助线索。[NIOSH照片](../evidence/V04/runway-photo/report.json)21.973秒识别安全帽/反光衣但误认设备；[照片追问](../evidence/V04/photo-followup/report.json)首问9.941秒、追问21.828秒，仍有品牌错误与过度自信；不宣称隐患判断通过 |

浏览器脚本按限定任务维护。自动化使用现有Windows Edge的隔离无头profile，通过CDP连接；不占用用户日常浏览器profile。真实生成与业务判断分别验收，不能用“返回了文字”代替识别正确。

同一影像复核功能的专用PPE补强已复现SiteWatch完整开源应用并合入主分支，入口 `http://127.0.0.1:8767`。V06独立完成实际检测框/类别/置信度、照片/视频、下载、失败恢复和停止重启验证；可操作的AI初筛与人工复核演示已跑通，但存在零检出和裸头误判戴帽，不能宣称自动违规判定可靠。规则告警不作为AI识别证据，详见 [阶段验收](../evidence/V06/ACCEPTANCE.md) 和 [决策记录](../docs/DECISIONS.md)。
