# 水电一局视觉AI：朋友接手开发

GitHub：`https://github.com/YuxuanQi123456/sd1-construction-vision`，私有仓库。所有者在Settings → Collaborators添加朋友，朋友接受邀请后才能克隆或提交。

用户已选择**精简开发库**：当前源码、接口、来源许可与项目说明从新快照起步；不上传原仓库的大历史。历史截图与验收输出已按用户指令清理，训练/验收视频、原图、标签和模型保留本地，见[资源与目录说明](ASSET_RETENTION.md)。

## 取得代码

```bash
git clone -b main https://github.com/YuxuanQi123456/sd1-construction-vision.git sd1-construction-vision
cd sd1-construction-vision
python3 scripts/configure_git.py --name "你的名字" --email "你的提交邮箱"
git switch -c feat/你的功能名
```

Windows原生Python可将`python3`换成`py -3`。邮箱可用GitHub隐私noreply邮箱，不是密码。配置脚本只改当前仓库，已有冲突origin不会覆盖；朋友需使用自己的提交身份和GitHub授权。

离线交接可把第一行换成：

```bash
git clone -b main sd1-construction-vision-main-20261107.bundle sd1-construction-vision
```

该bundle包含精简协作库的main历史，不含原仓库旧大证据历史。离线克隆后origin指向bundle；转在线前先核对`git remote -v`，再手动将origin设为上述GitHub地址。

## 开发与部署分开

本机代码协作目录为`E:\workspace\云枢\sd1-construction-vision`。原`E:\workspace\云枢\水电一局演示Demo`保留运行资源、视频和原Git历史，不再承担GitHub推送；禁止把两个独立历史直接pull/强制合并。

新开发目录的四个Windows启动器按自身目录定位，不再启动旧目录代码。新目录仍需要自己的Python环境、权重与素材；原运行目录原先能运行，不代表新代码已在新环境验收。原机部署更新应明确同步代码并重新回归，不能用旧页面截图冒充新代码结果。

当前原机验证为Windows＋Ubuntu-24.04 WSL、Python3.12：PPE检测用CPU，区域第二意见使用NVIDIA4GB显存的Qwen4B NF4。朋友只有CPU时可先开发PPE检测，Qwen另行恢复。

**新机器完整一键安装尚未验收。** `sitewatch/prepare.py`仍依赖原来的`vision/.venv`与外部Torch路径，只恢复基线PPE；需要在新机器重建匹配环境，不能直接复制旧venv当成可迁移安装。资源与环境完整后，才能在实际克隆目录运行：

```bash
python3 scripts/manage_ppe.py start --wait
python3 vision/scripts/manage.py start --wait
```

页面8767，区域模型8766，均绑定127.0.0.1。服务当前因资源安排暂停，代码上传不等于后台启动。

## 需要单独接收的资源

| 清单 | 资源 |
| --- | --- |
| `sitewatch/SOURCE.json` | SiteWatch源码版本、基线PPE权重与SHA |
| `sitewatch/model-candidates.json`、`sitewatch/person-model.json` | 对照PPE与远景人员模型 |
| `vision/config/qwen4b-files.json`、`vision/README.md` | Qwen4B来源/量化说明；原机实际权重在`downloads/qwen3-vl-4b-nf4` |
| `sitewatch/demo-media.json`、`sitewatch/media-sources.json`、`vision/config/samples.json` | 高清/1080p/旧540p及其他公开视频原件、署名、许可、SHA |
| `sitewatch/branding/SOURCE.json` | 已随代码保存的官网品牌原图与SHA |

Git不包含downloads、.runtime、虚拟环境、视频或训练数据。历史本地演示账号在config/demo.json，是公开固定演示值，不能复用于正式系统。

## 修改与验证

先读AGENTS.md、README.md、docs/PROGRESS.md。页面主要在`sitewatch/app/app.py`，样式在`sitewatch/branding/`，检测证据在`review_evidence.py`，区域第二意见在`region_review.py`，模型问答辅助在`vision/`。不改预测分数，不把配置优化说成已训练。

修改app下Python后同步上游patch，并执行：

```bash
python3 sitewatch/verify_provenance.py --output .runtime/developer-source-check.json
git diff --check
```

浏览器与推理测试需恢复相应环境/资源后运行，结果如实记录。精简库忽略大evidence输出；可提交必要小份验证摘要，视频、截图和ZIP留本地。模型/源码/素材许可证仍按NOTICE与各来源文件执行。

每个功能使用独立分支，推送后通过Pull Request审查；main更新用`git pull --ff-only`，不强推覆盖别人的修改。字节保留规则见.gitattributes，指定Windows启动器使用CRLF，其余避免自动改换行损坏源哈希。

Git官方：[bundle](https://git-scm.com/docs/git-bundle)、[换行属性](https://git-scm.com/docs/gitattributes)；GitHub官方：[邀请协作者](https://docs.github.com/en/repositories/managing-your-repositorys-settings-and-features/repository-access-and-collaboration/inviting-collaborators-to-a-personal-repository)。
