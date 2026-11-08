# 水电一局施工安全视觉 AI 项目 Progress

更新日期：2026-11-08｜当前功能基线：`e202213`｜用途：汇报、共同开发与后续优化交接。
本页按已提交代码和验收记录整理；详细阶段流水保留在 [PROGRESS.md](PROGRESS.md)。本次编写文档没有重新训练模型、启动新的业务功能或调用付费 API。

## 1. 当前做到哪一步

已完成一个可操作的施工安全影像演示：**选择施工照片/视频 → 本地 YOLO 检测人员及防护装备 → 查看采样画面、框与原始分数 → 点击所选头部获取 GPT 第二意见 → 对照查看并导出证据。**

当前重点是人员、安全帽、反光背心及直接未佩戴候选，面向领导演示与同事开发。采用固定公开样例优化展示；已有真实模型推理、真实 API 调用和浏览器操作证据。尚未开展新权重训练，也没有形成真实工地总体准确率结论。

| 项目项 | 当前状态 |
| --- | --- |
| 文件方式的人员/PPE 检测、头部第二意见、证据导出 | 已完成并记录验收 |
| 水电一局中文展示与清晰素材库 | 已完成；3 视频、3 照片 |
| 独立 CPU 环境、资源恢复、Git 协作 | 已交付；目标新机器需按说明安装并验收 |
| 小规模样例微调/过拟合 | 用户允许，当前未训练 |
| 连续摄像头、人员跟踪、自动告警/整改流程 | 尚未实现 |
| 原会议设备上传、工程监测联动、挖掘机后方 2 米感应 | 尚未实现，属于后续试点需求 |

会议纪要中的安全监测主要是设备数据、工程监测联动与 2 米感应；当前 PPE 是用户后续优先确定的视觉演示切入点。对应关系见 [任务书](VISUAL_TASKBOOK.md)。

## 2. 已完成功能与技术实现

| 已完成内容 | 用什么实现 | 关键代码/配置 | 当前效果与边界 |
| --- | --- | --- | --- |
| 复现已有开源应用 | 固定版本 SiteWatch，保留 Streamlit 页面、YOLO 推理和绘框代码；薄适配形成 patch | `sitewatch/upstream/`、`sitewatch/app/`、`sitewatch/SOURCE.json`、`sitewatch/patches/local-review.patch` | 无需取得云枢源码；27 份上游文件与 13 份适配 Python 文件可核对重建 |
| 照片/视频导入 | Streamlit 素材选择、文件上传、本地文件校验 | `sitewatch/app/app.py`、`sitewatch/demo-media.json` | 支持样例和自己的照片/短视频；未知上传来源不套用公开视频许可 |
| 人员、安全帽、背心等检测 | Ultralytics YOLO + SiteWatch PPE 权重 | `sitewatch/app/cv_pipeline/detection.py`、`sitewatch/model-candidates.json` | CPU 实际推理，原类别、浮点框和分数保留；存在漏检与误检 |
| 近景备用模型与自动选择 | Constructelligence v0.3，按素材条目解析推荐模型；可手动覆盖 | 同上；`demo-media.json` 的 `recommended_model_id` | 部分清晰近景框更干净；没有把其宣布为所有场景的最佳模型 |
| 远景人员补充 | PPE 1280 输入，加官方 YOLOv8n 的 person-only 640 分支；跨分支整人框重叠过滤 | `detection.py`、`sitewatch/person-model.json` | 改善部分人员检出；通用分支不判断安全帽，轨道片仍不足以作主演示 |
| 视频抽帧与时间索引 | OpenCV 顺序解码、按间隔采样，记录帧号/容器 FPS | `sitewatch/app/review_evidence.py` | 默认片头 8 秒每 1 秒一帧；输出采样画面，不是全程逐帧监控或连续叠框视频 |
| 保留清晰度与原件 | 原始文件逐字节保存，保真模式下原尺寸 PNG、禁用有效增强；大图/对照与下载 | `review_evidence.py`、`app.py` | 已核原件 SHA、解码像素和下载字节；模型内部仍按 640/1280 尺度预处理 |
| GPT 头部第二意见 | 本机配置的 Responses 图像接口；固定 A/B/C/D 问题；未画框头部框四边扩展 20% 后送 PNG | `sitewatch/app/region_review.py`、`sitewatch/app/review_api.py` | 仅用户点击所选头部时调用；默认 `gpt-6.1-sol`、推理 `max`；不是整图/整视频隐患问答 |
| 分歧与失败记录 | 原 YOLO 结果保持；记录裁图 SHA、实际模型、原答、意见关系、token 与每次 attempt | `region_review.py`、`contracts/head-review-api-v2.md` | 展示一致/分歧/不确定；没有把 GPT 当作真值，也没有自动改正检测结果 |
| 原件与完整证据下载 | JSON、PNG、ZIP、SHA256 | `review_evidence.py`、`contracts/ppe-review-v1.md` | 可回溯来源、模型、帧时间和实际复核；尚无人工结论录入或整改派单 |
| 页面品牌与中文操作 | Streamlit + 本地 CSS、官网组合标识 PNG | `sitewatch/branding/`、`app.py` | 桌面大图、左右对照与已验 390 宽布局可用；统计卡来自实际结果 |
| 独立环境与资源恢复 | Python venv、CPU PyTorch、依赖版本固定、标准库下载/解包与 SHA 校验 | `scripts/bootstrap_runtime.py`、`scripts/restore_runtime_assets.py`、`config/` | 不借用其他项目包目录；异内容文件拒绝覆盖，资源与源码分离 |
| 启动、停止与共同开发 | 项目进程身份检查、localhost 健康检查、Windows CMD→WSL、Git/GitHub/Release | `scripts/manage_ppe.py`、根目录启动/停止脚本、`docs/DEVELOPER_HANDOFF.md` | 只管理本项目进程；关机后需重新启动；Public 可 clone，直接 push 仍需写入权限或走 fork/PR |

## 3. 当前模型分别负责什么

### 3.1 两个已接入界面的 PPE 模型

| 模型 | 当前职责 | 类别数 | 当前推荐场景 |
| --- | --- | --- | --- |
| SiteWatch 自定义 YOLOv8m PPE 权重 | 主检测；识别人、防护装备及其他原生目标类别 | 25 | 默认结构施工视频、砌筑复核对照、自动模式的用户上传 |
| Constructelligence v0.3 | 已注册的可选 PPE 模型 | 14 | 两条 4K 近景视频、两张高清照片 |

`model-candidates.json` 还保存 YOLO11n、SafetyVision 等历史对照模型信息；当前运行检测器仅允许上表两者，不代表所有登记模型都已接入页面。远景模式另有 YOLOv8n 人员伴随分支。

SiteWatch 的 **25 是目标标签数**：人员 1、防护相关 7、机械设施 6、车辆 11。没有对应 25 项独立安全业务。当前页面默认重点展示人员与 PPE，其余标签可展开查看。

### 3.2 分数和统计的含义

- YOLO 的 `0.52` 等数值是当前检测框的模型分数，不是该工地准确率。
- GPT 第二意见没有校准概率，不把 YOLO 分数复制成 GPT 的“置信度”。
- `NO-*` 框只表示模型候选；“待人工复核框”是跨帧候选框次数，不是去重人数、独立事件或已确认违规数。
- 人工复核目前是查看和导出，不含人工确认按钮、流程状态或整改销项。

### 3.3 主要技术版本

| 技术 | 当前固定版本/用法 |
| --- | --- |
| Python / 系统 | Python 3.12；Linux x86_64 / Ubuntu / WSL2 |
| PyTorch / torchvision | 2.8.0+cpu / 0.23.0+cpu；检测固定 CPU |
| Ultralytics | 8.3.228 |
| Streamlit | 1.51.0 |
| OpenCV / NumPy | 4.12.0.88 / 2.2.6 |
| SciPy / Pillow | 1.16.3 / 11.3.0 |
| GPT 调用 | `gpt-6.1-sol`、`reasoning.effort=max`，Responses 图片接口；该字符串为本项目实际配置与验收模型名 |
| 安装/资源约束 | 以 `config/bootstrap-ppe.txt`、`scripts/bootstrap_runtime.py` 与 `config/runtime-assets.json` 为准 |

## 4. 当前演示素材与质量处理

| 样例 ID | 内容与原尺寸 | 自动推荐 |
| --- | --- | --- |
| `site-action` | 实际结构施工作业，1920×1080，约 15.6 秒 | SiteWatch / standard；默认入口 |
| `close-worker` | 单人安全帽近景，3840×2160 | Constructelligence / standard |
| `close-team` | 双人现场交流，3840×2160 | Constructelligence / standard |
| `site-photo` | 工人现场照片，5614×3733 | Constructelligence / standard |
| `portrait-photo` | 安全帽近景照片，4000×2667 | Constructelligence / standard |
| `bricklayer-review` | 砌筑作业复核对照，2256×1496 | SiteWatch / standard |

以上均为有来源的公开实拍，非水电一局现场。模型输入不包含素材标题、人工判断或预期答案。

原轨道视频曾出现人帽过小、遮挡、低阈值增加误检的问题。36 次固定帧对照后，停止继续随机调参，撤下两个轨道菜单入口；原视频、训练/验收视频和用户上传通道保留。此次新增合适素材和推荐配置，没有重新训练权重，也没有手工抬高分数。

当前保真模式下，原片、保存 PNG、模型输入尺度与页面显示四层分开：原件不变；保存画面维持解码尺寸；standard 内部推理 640，distant 的 PPE 为 1280、人员伴随为 640；浏览器按屏幕缩放显示。

## 5. 实际做过哪些验证

以下是提交的历史验收事实，来源为 [V13 整体证据](validation/V13_SAFETY_DEMO.json)、[V13 模型对照](validation/V13_MODEL_SELECTION.json) 和 [V12 真实 GPT 调用](validation/V12_GPT_API_LIVE.json)。

| 验证项 | 记录结果 | 解释范围 |
| --- | --- | --- |
| 定向工程单测 | 61 项通过：API 20、管理器 7、环境 17、资源恢复 17 | 不含全部历史模块；不是 61 项识别精度测试，真实 API 另验 |
| 源码与适配可重建 | 27 份上游文件、13 份适配 Python 文件核对通过 | 验证来源与 patch，不代表模型无误检 |
| 新环境视频处理 | 默认 1080p 视频约 0/1.001/2.002 秒三帧均输出人帽，记录处理约 4.99 秒 | 含抽帧/证据处理，不含整套页面冷启动；不能据此承诺实时帧率 |
| 新环境真实 GPT 视频复核 | 选中一个头部，调用一次，返回 A，约 9.1 秒；接口记录 195 tokens | 仅一次固定裁图；费用和耗时不作所有请求的保证；检测阶段零 API 调用 |
| 安全帽照片真实 GPT | 返回 A，与检测器一致，约 12.05 秒 | V12 固定照片与裁图，3130 tokens |
| 砌筑照片真实 GPT 分歧 | 原 YOLO `Hardhat 0.5987058` 保留，GPT 返回 B，约 4.03 秒 | V12 固定照片与裁图，249 tokens；证明能展示分歧，不证明 GPT 永远正确 |
| 真实浏览器四案例 | 默认视频、高清照片、手动模型、旧轨道片上传通过；原件与 PNG 下载字节/像素核对通过 | 浏览器阶段未调用付费 API，未执行 API 意见切换检查；真实 API 全链由 AppTest/CPU/API 组合另验 |
| 显示与状态 | 大图/对照不改检测；素材、模型、画质切换清旧显示；390 宽布局通过 | GPT 本机配置变化不会主动隐藏已有意见，页面保留该次实际模型来源 |
| 迁移与资料保护 | 迁移时 1237 文件约 2.9GB SHA 一致；75 视频、5 份 PPE 权重 SHA 一致；另保留 3 个随包示例视频 | 包括多处保留副本，不等于 75 个独立场景或 75 条菜单素材 |
| 资源与协作包 | 214 个目标文件 SHA 核验；209 份资源新版协作包 CRC、离线 clone 和恢复计划通过 | 当前包代码固定 `1df4e7c`；收到后可 `git pull --ff-only` 更新文档 |

原检测 JSON 与 GPT 调用前后的字节保持一致，ZIP 保存原视频、原检测、裁图和实际意见；Key 未进入证据。当前证据是固定样例演示验收，不是生产安全系统验收。

## 6. 已走过的路线与取舍

| 阶段 | 做过的工作 | 当前结论 |
| --- | --- | --- |
| 初始开源调研与技术试跑 | 阅读会议需求，调查已有应用；早期材料库存链路曾技术试跑 | 用户明确要求实际视觉 AI，库存试跑已停止，未列入当前产品 |
| 本地通用视觉模型路线 | 复现 Qwen 官方网页、量化和视频采样，尝试施工影像问答 | 技术可运行，但通用隐患判断有漏识别与错误推断，未通过该业务目标 |
| 专用 PPE 应用 | 复现 SiteWatch，增加真实照片/视频检测、证据和错误处理 | 形成当前可演示主线 |
| 模型与尺度对照 | 对比已有 PPE 权重，加入可选 Constructelligence、远景人员分支 | 根据样例选择，未找到所有场景通用替换方案 |
| 清晰素材与展示 | 保留原片、增加 4K/1080p 样例、水电一局品牌与中文页面 | 改善演示观感与可查看性；内部输入尺度仍独立记录 |
| GPT 与轻量运行 | 改接用户 GPT API，删除本地千问及 full 依赖，重建隔离 CPU 环境 | 不需要本地大语言模型或 GPU；GPT 仅按点击使用 |
| 协作交付 | 精简 Git、Release 清单、离线协作包、恢复与启动说明 | 源码与大资源分离，便于朋友一起开发 |

本地千问代码、相关权重/配置目录、旧借用依赖及远端 689 个千问附件均已移除。历史记录保留路线判断依据，旧 `qwen_local` / `full` 指令不再适用。

## 7. 资源、目录与运行入口

| 口径 | 含义 |
| --- | --- |
| 基础 `ppe` | 17 个包内目标文件 + 5 份原站素材 = 22 个目标文件；需 32 个 Release 资源附件 |
| 加 `--include-training` | 总计 209 个包内目标文件 + 5 原站素材 = 214；共 11 个资源包、41 个资源附件 |
| 209 份协作包资源 | 可分发权重、素材、许可与测试输入的文件数，不是 GitHub 附件数 |
| 5 份外部原件 | Pexels 三视频、两照片，合计 52,617,151 字节；按官方地址和 SHA 恢复，不重发原文件 |
| RF100 可选数据 | 90 张测试图、90 份标签及相关说明，不是完整训练/验证集 |

源码位于 GitHub 的 `sd1-construction-vision`；模型、视频、环境、Key 和大运行输出不进 Git。资源路径与下载地址以 `config/runtime-assets.json` 为准。

新目录运行：

```bash
python3.12 scripts/restore_runtime_assets.py --profile ppe
python3.12 scripts/bootstrap_runtime.py --profile ppe --no-cache-dir
python3.12 scripts/manage_review_api.py init
python3.12 scripts/manage_ppe.py start --wait
```

系统依赖与离线方式见 [运行说明](RUNTIME_SETUP.md)。页面为 `http://127.0.0.1:8767`；Windows 可使用根目录启动/停止脚本。关机后需要重新启动服务。

Key 仅填 `config/review-api.local.json`，见 [GPT 设置](GPT_API_SETUP.md)。未填 Key 时基础检测和导出仍可使用。GitHub 仓库为 Public，朋友可以 clone；直接 push 原库需要协作者权限，也可 fork 后提交 PR，见 [共同开发交接](DEVELOPER_HANDOFF.md)。

## 8. 当前问题与下一步重点

1. **识别仍有重复、漏检和误检**：优先在固定演示素材上评估阈值、同类重叠处理和模型推荐；不为凑高分手改输出。
2. **缺少可直接播放的带框演示成片**：当前只提供采样画面和证据；是否增加独立派生成片见优化计划。
3. **业务结果以人工查看为止**：尚无审核结论录入、跟踪去重、自动告警或整改闭环。新增流程需先确认用途与范围。
4. **GPT 只覆盖被检测到的头部**：未检测到头部时没有复核入口；不能写成全图安全审查。扩大 ROI 或改用整图属于后续候选。
5. **真实监测仍缺输入条件**：设备协议、工程数据与物理距离依据尚未接入，应从原会议三项需求中选一条试点，不能用像素距离冒充 2 米。

下一步按 [优化计划](VISUAL_OPTIMIZATION_PLAN.md) 的优先级执行：先把已有演示做稳、做清楚，再视缺口决定是否对固定样例微调；现场实时和设备联动另设验收。
