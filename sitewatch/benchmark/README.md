# RF100 固定测试集原生评测

本目录仅做数据下载锁定和类ID薄适配，全部匹配、AP与P/R来自已安装的Ultralytics `YOLO.val`。8.3.228原生验证器的NMS漏传classes，因此使用 `ClassRestrictedValidator` 子类仅向同一原生NMS补传该参数，在NMS前限制共同预测类；其余匹配/统计方法直接继承，未自行实现。原未限制预测的run保留为对照，最终采用native-640-filtered。不修改服务和模型默认配置，不训练，不推导缺失装备。

数据目录为项目专属 `downloads/ppe-v07/benchmark/rf100/`，只包含 `test/images`、`test/labels`（各90文件）、原始YAML/署名文档和 `dataset-lock.json`。下载必须给不可变HF提交，不允许main。完整原始测试图不提交Git；锁定元数据和原生评测输出保存在证据目录。

父任务已经取好原件时，`--dataset-root` 指向其只读 `downloads/ppe-v07/rf100-source/` 即可，不重复下载。每模型的派生GT与输入副本写入专属 `downloads/ppe-v07/benchmark/<revision>/<输出目录名>/<模型>/<任务>/`；逐图输入/重映射标签SHA与YAML哈希写入证据 `mapping.json`。YAML的train为null、val/test共用测试alias仅为上游评测兼容，绝未用于训练。首次native-640跑完后只搬移派生输入到缓存，保留原路径符号链接，使原生args.yaml及原始指标仍可回溯；未改写任何得分。

```bash
python3 sitewatch/benchmark/prepare.py --dataset-root <主目录>/downloads/ppe-v07/benchmark/rf100 --revision <40位HF提交> --evidence evidence/V07/benchmark/dataset-lock.json
<主目录>/.runtime/sitewatch-env/bin/python sitewatch/benchmark/evaluate.py --models <主目录>/sitewatch/model-candidates.json --project-root <主目录> --dataset-root <主目录>/downloads/ppe-v07/benchmark/rf100 --output evidence/V07/benchmark/native-640 --imgsz 640
```

manifest格式为父任务冻结的 `ppe-model-comparison-v1`；`models[].classes` 是canonical类别到原始权重ID的明确映射。权重SHA和实际names必须匹配，不符立即失败，不能猜测或改manifest。core4只比较helmet/no_helmet/person/vest；支持no_vest的模型另列full5，不把不同分母平均分混比。

每次必须使用新的输出目录及末级目录名，已有证据或派生cache拒绝覆盖。本轮prepare.py只做编译检查，原始数据由父任务既有下载入口实取并校验；不能将备用下载器的存在视为其网络复现通过。最终报告在 `native-640-filtered/report.json`，`verify_artifacts.py` 另行验证全部输入/重映射标签SHA、类别分母及原生预测ID，没有重算AP。

默认CPU两线程、imgsz640、conf0.001、NMS iou0.7、batch1、workers0。官方P/R来自其最佳F1工作点，不是页面置信度0.40；AP匹配使用官方IoU0.50:0.95实现。评测原件/GT按每模型原始类别ID重映射，原始数据不改。GT必须先目视确认头部/整人框粒度；可能存在候选训练重叠，不宣称独立现场泛化或法规准确率。四张公开演示图只做额外回归，不进入训练或本测试统计。
