# 中文材料演示导览

这是 OpenConstructionERP 19 的静态中文导览。项目、身份、库位、物料、台账和库存均由已安装的上游应用提供。本目录没有后端、数据库或库存计算器，也不调用公网资源。

部署（目标必须显式给出）：

```bash
/mnt/e/workspace/云枢/水电一局演示Demo/.venv/bin/python scripts/install_demo_page.py \
  --site-packages /mnt/e/workspace/云枢/水电一局演示Demo/.venv/lib/python3.12/site-packages
```

也可传 `--target /明确路径/app/_frontend_dist/sd1-demo`。脚本只部署本页文件和 `config/demo.json` 中的公开本机测试账户；不修改上游服务代码。主工程必须已应用 `/sd1-demo/index.html` 的限定静态路由补丁（原版会返回 SPA 首页）。访问 `http://127.0.0.1:8765/sd1-demo/index.html`。

默认发现当前账户拥有、名称及描述和 metadata 都匹配的 `SD1-DEMO-GROUND` / `SD1-DEMO-UNDERGROUND` 项目。不自动创建业务数据。明确传入 `?project_id=<UUID>` 时，还允许本任务的 `SD1-TEST-T03-GROUND-*` / `SD1-TEST-T03-UNDERGROUND-*` 项目；同样验证所有者、合成标识和上游权限。

样例要求唯一 `sku=SD1-CEMENT`、`unit=t`、`currency=CNY`、`standard_unit_cost=400` 的物料，以及唯一 `code=A/B` 的有效库位。空流水从入库开始；现有一至四笔流水按实际备注标记恢复状态。按钮每次先重新读取实际记录，同页禁用重复点击，同源标签页通过 Web Locks 串行操作。此机制仅供单人本机演示，不能保证不同客户端的服务端幂等。

四笔数量为 100 / 30 / 2 / 10，动作标记为 inbound / consume / waste / transfer。写入 `metadata.sd1_step`，同时把 `[sd1_step=...] [sd1_namespace=...]`、工点与合成声明写入原生可见备注。上游流水响应不返回 metadata，读取状态使用备注。查询全项目流水 `limit=201`，超过四笔、达到读取上限、重复标记或数量/单价/库位不匹配时停止四步写入并清空金额结论。只有核对到四笔才显示“已取到完整四笔流水”。

库存指标直接使用上游 `stock-on-hand`。表中金额为各笔数量乘单价；工点领用金额只取 CONSUMPTION 一笔，调拨不计入消耗。400 CNY/吨为合成假设，金额不代表财务入账。

原生业务页保留独立入口。导览的 access token 只保存在当前页面内存；原生页面需要使用同一个公开测试账户正常登录。本页不修改原生浏览器认证存储。

浏览器验收：

```bash
/mnt/e/workspace/云枢/水电一局演示Demo/.venv/bin/python tests/browser_demo.py \
  --browser-path /tmp/shuidian-demo-browsers \
  --library-path /tmp/hydro-browser-libs/root/usr/lib/x86_64-linux-gnu \
  --font-dir /mnt/c/Windows/Fonts
```

后两个参数是当前 WSL 验收环境所需：复用已存在的 Chromium 动态库和本机系统中文字体，不安装系统包、不复制或分发字体。有正常系统依赖和中文字体的环境可省略它们。实际使用系统字体，无在线字体依赖。脚本只创建自己的 T03 合成项目；证据保存到 `evidence/T03/browser/`，不保存 token。
