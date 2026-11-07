# runtime-assets-v1 交接资源契约

目标：当前PPE检测与Qwen3-VL区域第二意见在新目录恢复所需资源；不把大资源写入Git历史。用户2026-11-07明确授权上传必要资源，仓库现为Public。资源发布到GitHub Release，脚本从清单恢复并逐SHA校验；原视频、训练输入和模型不得修改/删除。

清单路径`config/runtime-assets.json`，根字段：`schema="sd1-runtime-assets-v1"`、`repository="YuxuanQi123456/sd1-construction-vision"`、`release_tag`、`bundles`、`external_files`。

`bundles`每项：`id`、`profiles`（包含`ppe`/`full`，可含独立`training`）、`format`（`zip`或`raw-parts`）、`assets`、`files`、`license`/`source`可选说明。默认profile为full；ppe只选profiles包含ppe的项，full只选包含full的项；`--include-training`额外选择profiles包含training的项。

`assets`每项：`name`、`bytes`、`sha256`、`url`；url为固定Release下载地址，列表顺序即raw-parts拼接顺序。每项小于2GiB，根打包可流式分片不复制大权重。

`files`每项：`path`（相对项目根）、`bytes`、`sha256`。zip中成员名与path完全一致，只可按白名单解压，拒绝绝对/上级/符号链接路径；raw-parts只允许一个files目标，按顺序拼接后核总SHA。恢复只使用受校验内容，已有相同SHA文件跳过，已有不同文件默认拒绝覆盖。

`external_files`每项：`path`、`bytes`、`sha256`、`profiles`、`url`、可选`headers`、`source`、`license`和`reason`。Pexels四条原文件按许可走官方地址恢复，带Mozilla User-Agent与Pexels Referer；不作为公共原文件附件再分发。外部文件也必须核SHA/大小，不得替换为低清版本。

示例：

```json
{"schema":"sd1-runtime-assets-v1","repository":"YuxuanQi123456/sd1-construction-vision","release_tag":"runtime-20261107-v1","bundles":[{"id":"ppe-models","profiles":["ppe","full"],"format":"zip","assets":[{"name":"ppe-models.zip","bytes":123,"sha256":"...","url":"https://github.com/YuxuanQi123456/sd1-construction-vision/releases/download/runtime-20261107-v1/ppe-models.zip"}],"files":[{"path":"downloads/sitewatch/repository/models/sitewatch_best.pt","bytes":52043602,"sha256":"c2db52b9be8ccd5bcc09d6e0f9498a6e442e47eb6f6b62850db11530b77651ab"}]}],"external_files":[]}
```

恢复脚本`scripts/restore_runtime_assets.py`仅用标准库（含urllib/zipfile/hashlib），支持`--profile ppe|full`、`--include-training`、`--manifest PATH`、`--project-root PATH`、`--assets-dir PATH`离线包输入、`--verify-only`已恢复核验和`--plan`仅列需求。下载缓存位于忽略的`.runtime/asset-downloads`，支持清单中分片顺序，失败不生成伪完成文件。

环境脚本`scripts/bootstrap_runtime.py`在本项目内创建所需venv，不引用/home/meg或原项目其他venv；支持`--profile ppe|full`和`--plan`。检测CPU可独立使用；full需要匹配的NVIDIA/PyTorch/CUDA和bitsandbytes。不得称新机器GPU已实测。依赖可按PyPI/官方PyTorch索引核验调整，本机环境锁只作来源记录，不盲目复制不能安装的版本。
