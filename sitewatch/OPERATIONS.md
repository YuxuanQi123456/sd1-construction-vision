# SiteWatch 运行说明

当前为本地 CPU YOLO + GPT API，已删除千问本地服务。新 clone 按 [运行说明](../docs/RUNTIME_SETUP.md) 恢复资源与隔离环境，按 [演示说明](../docs/PPE_DEMO.md) 操作。

```bash
python3 scripts/manage_ppe.py start --wait
python3 scripts/manage_ppe.py status
python3 scripts/manage_ppe.py stop
```

Windows 使用根目录“启动施工视觉.cmd”/“停止施工视觉.cmd”；页面 http://127.0.0.1:8767。关机后需要重启服务。停止仅影响归属确认过的本项目进程，不按通用 Python 进程名清理。

环境路径 `.runtime/portable-env`，相对链接 `.runtime/sitewatch-env`；运行文件位于其 `runtime/`，包含上传原件、逐帧 PNG、JSON 与 ZIP。不得作为缓存删除训练/验收视频。日志与PID由本项目管理器保管，端口被未知服务占用会明确拒绝接管。

默认清晰素材库为 3 视频/3 照片；结构施工用 SiteWatch，4K近景/照片用 Constructelligence，均可手动覆盖。阈值 0.40，保存原片画质，默认起始8秒每秒1帧，未分析全程。原轨道视频撤下菜单而保留文件与上传入口。

模型 SHA、类别及许可证严格验证；无自动 COCO 替代坏 PPE 权重。远景模式只用官方 COCO 补人员。原始分数/类别完整保留；NO-* 框待人工复核，不构成法规违规判断。

GPT Key 位于本机 `config/review-api.local.json`，默认模型 `gpt-6.1-sol` / `max`；详情见 [设置](../docs/GPT_API_SETUP.md)。未配置时只禁用区域复核，基础检测与下载可用。配置状态不证明联网成功，实际调用证据单独记录。复核只发送选中的未画框头部PNG与固定问题，失败可重试、原检测JSON不变。

上游 pristine 副本、MIT源码与AGPL权重说明保留；所有 Python 适配由 `patches/local-review.patch` 可重建，`verify_provenance.py` 完整核对。自己的上传不套用公开示例许可，已登记示例按SHA标注作者与许可。
