# OpenConstructionERP 19.0.0 最小接口契约

冻结日期2026-11-05；官方tag提交7be066347abb3fc1d4f3cdafb78e8910f97a7dd0；实际官方wheel和哈希见config/upstream-lock.json。已用真实HTTP验证登录、项目、库位、材料、流水和库存，原始记录见evidence/T01/upstream-probe.json。

服务http://127.0.0.1:8765；凭证config/demo.json仅用于本机合成实例。所有客户端对localhost禁用代理；业务请求Authorization: Bearer access_token。不可把token写入证据。

| 用途 | 路径与约定 |
|---|---|
| 登录 | POST /api/v1/users/auth/login/；JSON email/password，返回access_token |
| 用户 | POST /api/v1/users/auth/register/；email/password/full_name/locale，首个账户管理员 |
| 项目 | POST /api/v1/projects/；name,currency=CNY,locale=zh,country_code=CN,description；返回id |
| 项目列表 | GET /api/v1/projects/；实际返回裸数组，limit/offset分页；status=all可见归档；只操作约定命名空间 |
| 库位 | /api/v1/site-inventory/projects/{pid}/locations；POST name/code，GET列表 |
| 材料 | 同前缀/items；POST name,unit=t,standard_unit_cost="400",currency=CNY；返回id |
| 流水 | 同前缀/movements；POST item_id,movement_type,quantity字符串,unit_cost字符串,currency,location_id,note；TRANSFER加to_location_id；返回201和id |
| 流水列表 | GET 同前缀/movements，支持item_id/location_id/movement_type/limit |
| 库存 | GET 同前缀/stock-on-hand，可加location_id；对象含rows[]：item_id,name,unit,on_hand字符串 |
| 原生页面 | /projects/{pid}/site-inventory；登录/login；项目列表/projects |

动作INBOUND/CONSUMPTION/WASTE/TRANSFER。每笔明确单位、单价和币种；标准价不会由API自动带入。源/目标库位均属同一项目。metadata可保存自有demo namespace/workpoint/单据号；原生界面用note保证可见。

## 业务调整与边界

原版实测可超领至负数。patches/site-inventory-stock-guard.patch在原入账服务增加事务锁，并调用原ledger按物料/库位核算，库存不足返回409。引用错误404、格式错误422沿用上游。补丁必须实测并发与失败不入账；不得直接改账绕过。

原生流水只显示最近200条；四笔Demo可用，摘要必须检查分页/limit并避免截断后仍宣称完整成本。库存余额直接取上游汇总API，禁止另造库存引擎。领用金额是演示单价×领用量，需显示人民币/吨口径，不等于财务入账。

## 并行任务交接

- T02负责scripts/demo_data.py、scripts/demo_api.py、fixtures/、tests/test_material_flow.py、evidence/T02/。CLI约定ready（只建项目/材料/库位，无流水）、prepare（幂等建立初始100吨）、complete（四笔完整状态）、verify、reset（仅自有合成项目）和--scenario ground/underground。状态写 .runtime/demo-state.json，结构包含project_id、item_id、locations:{A,B}、scenario、namespace、stage，不保存token。
- T03负责web/、scripts/install_demo_page.py、tests/browser_demo.py、evidence/T03/。提供纯静态中文演示导览/摘要，可直接调用既有API，不增加业务后端；独立页面固定 /sd1-demo/index.html，安装到上游app/_frontend_dist/sd1-demo/。使用原生项目列表按命名空间发现演示，不依赖T02私有文件；原生业务页面仍可直接打开。
- T03页面可以用明确按钮调用原生入库/领用/损耗/调拨API，但不能重做库存计算或存储。界面需防重复点击、操作前读实际流水识别相同步骤；无法确保服务端幂等时明确单人本机演示限制。余额读官方stock-on-hand接口。
- 主智能体独占manage.py、apply_patches.py、install.py、contracts/、docs/、config/、patches/和集成证据。两任务不得修改这些路径；接口不一致先报告。

正式样例项目名称前缀：SD1-DEMO-GROUND 与 SD1-DEMO-UNDERGROUND；描述含“水电一局演示｜自制合成数据”。流水metadata.sd1_step分别为inbound/consume/waste/transfer，note含相同唯一标记和工点名称。步骤数量固定100/30/2/10，默认400 CNY/t。页面读取实际流水决定步骤状态，且仅选择匹配本项目标记的演示数据。

实跑补充：名称完整格式namespace＋“｜”＋中文标题。POST项目不支持metadata，须PATCH /api/v1/projects/{id}（无末尾斜杠）；创建前保存nonce凭据可恢复中断。写入前须同时核验owner_id为当前账户。流水GET不返回metadata，note必须包含完整“水电一局演示｜自制合成数据”及[sd1_step=…]、[sd1_namespace=…]，前端与CLI统一使用。reset原生DELETE为归档，归档项目GET详情404，需列表status=all确认。

并行测试数据也必须隔离：T02只写SD1-TEST-T02-*，T03只写SD1-TEST-T03-*；正式SD1-DEMO-*由主智能体集成时准备。T03允许显式?project_id=...指定自己的测试项目，但不能依靠任意项目名猜测后直接写入。并发API测试的库存保护已进入补丁；服务重启期间先等待健康，不擅自启动第二个服务。
