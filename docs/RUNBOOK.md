# 启动、演示与恢复

## 当前使用方式

在本机浏览器打开：**http://127.0.0.1:8765/sd1-demo/index.html**。地上与地下场景可切换，均为自制合成数据。

导览使用本机专用演示账户连接上游。打开“原生业务页”时，如出现登录页，使用 `demo@shuidian.example.com` / `ShuidianDemo2026!`。这是公开本机测试口令，不是生产账户。首次向导可正常点“稍后”。

## WSL 启动和停止

在项目目录运行：

```bash
cd '/mnt/e/workspace/云枢/水电一局演示Demo'
python3 scripts/manage.py start
python3 scripts/manage.py status
```

首次及重启约需1—2分钟，上游会加载全部模块。`start`等待版本、工作区身份、数据库与前端均通过健康检查后返回；日志在`.runtime/server.log`。默认只监听127.0.0.1:8765。

```bash
python3 scripts/manage.py stop
```

若由本智能体运行上述命令，沙箱可能禁止本机端口/数据库，需要使用已经批准的具体脚本执行规则；用户正常WSL终端不受该工具沙箱限制。

## 准备与复位

首次准备两个空库存场景，让四个按钮均能实际执行：

```bash
.venv/bin/python scripts/demo_data.py ready --scenario ground
.venv/bin/python scripts/demo_data.py ready --scenario underground
```

`ready`只补缺失的项目、材料和库位，不抹掉已有流水。重复演示前先归档对应旧样例，再准备新样例：

```bash
.venv/bin/python scripts/demo_data.py reset --scenario ground
.venv/bin/python scripts/demo_data.py ready --scenario ground
```

地下场景改成`--scenario underground`。reset核验当前账户所有权、名称、描述及metadata，只调用上游归档接口，历史台账保留。页面刷新后选择新的活动场景。

预先填好四步供讲解回看可用`complete`；机器核验可用`verify`。`prepare`与`ready`不同：前者会预先登记100吨入库。

## 四分钟讲解顺序

1. 选择“地上施工·厂区基础”，指出合成数据、工点和400元/吨的假设单价。
2. 点击材料入库100吨，查看总库存与A库变为100，展开原始备注。
3. 点击工点领用30吨，余额70，领用金额12000元。
4. 登记损耗2吨，余额68；调拨10吨到B，总量仍68，A58、B10。
5. 查看四笔台账、单价与工点，刷新结果仍在；打开原生业务页查看同一项目的库存与出入库记录。
6. 切换地下支护，说明相同业务也适用于地下工点；后续采购、效期、质检、计量按里程碑增加。

仅限单人本机样例。前端可防同页/同源标签重复，但没有承诺跨客户端业务幂等；不要同时让CLI和多个浏览器写同一场景。库存不足保护位于上游服务，真实并发出库已另验。金额为领用量×演示单价，不代表财务入账。

## 备份与恢复

当前E盘DrvFS无法保留PostgreSQL要求的目录权限，活动数据位于`/tmp/shuidian-oce-ff3b0902b477`。**/tmp不能当永久存储。** 数据归档放E盘项目`.runtime/backups/`。

完成演示或关机前：

```bash
python3 scripts/manage.py stop
python3 scripts/manage.py backup
python3 scripts/manage.py start
```

只在应用与数据库均停止时归档，包含数据库、附件、用户及本机密钥；文件不进Git。`.runtime/latest-backup.json`记录校验和、版本和workspace身份。

需要恢复最近归档时：

```bash
python3 scripts/manage.py stop
python3 scripts/manage.py restore
python3 scripts/manage.py start
```

restore校验归档哈希/版本/工作区，解包到Linux目录，修复PG目录权限；旧运行目录改名保留以便回退。不要把`.runtime/backups/`当普通缓存清理。恢复后执行相应场景`verify`或实际点击查看；恢复的是最近一次备份时状态。

长期使用可把运行目录迁至持久Linux文件系统或外部PostgreSQL；此阶段未部署生产环境。

## 复现和验收命令

当前已安装；检查安装与补丁完整性：

```bash
python3 scripts/install.py --verify-only
python3 tests/test_lifecycle.py
.venv/bin/python tests/test_material_flow.py --evidence evidence/T04/material-flow-rerun.json
.venv/bin/python scripts/acceptance.py repeat
```

首次安装或重建环境用`python3 scripts/install.py`，从固定官方wheel和依赖锁安装、校验并应用补丁，安装阶段需要网络。当前验证环境为WSL/Linux、Python3.12.3；核心演示运行不需公网。

浏览器验收：

```bash
.venv/bin/python tests/browser_demo.py \
  --library-path /tmp/hydro-browser-libs/root/usr/lib/x86_64-linux-gnu \
  --font-dir /mnt/c/Windows/Fonts
```

自动验收使用Playwright1.58和`/tmp/shuidian-demo-browsers`中的Chromium。当前WSL另需上述已有系统库缓存；中文截图引用本机Windows字体，没有复制或分发字体。换机器需准备相应浏览器系统库及中文字体；普通Windows浏览器访问本演示不依赖这套自动测试缓存。

原生应用包含更多模块菜单，本轮仅验收材料链；没有配置外部大模型或Agent。公网被阻断时，本机服务和数据库仍须在线。
