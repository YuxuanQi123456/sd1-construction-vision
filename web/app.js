"use strict";

// Presentation only: the upstream API owns authentication, ledger and stock calculations.
const STEPS = [
  {key: "inbound", type: "INBOUND", quantity: 100, title: "材料入库", action: "入库 100 吨"},
  {key: "consume", type: "CONSUMPTION", quantity: 30, title: "工点领用", action: "领用 30 吨"},
  {key: "waste", type: "WASTE", quantity: 2, title: "损耗登记", action: "登记损耗 2 吨"},
  {key: "transfer", type: "TRANSFER", quantity: 10, title: "库位调拨", action: "调拨 10 吨"},
];
const MARKER = "水电一局演示｜自制合成数据";
const state = {token: null, project: null, user: null, item: null, locations: {}, movements: [], done: new Map(), busy: false, valid: false};
const el = id => document.getElementById(id);
const number = value => Number(value).toLocaleString("zh-CN", {maximumFractionDigits: 4});
const apiPrefix = () => `/api/v1/site-inventory/projects/${state.project.id}`;
const namespace = () => state.project.metadata.sd1_namespace;
const workpoint = () => state.project.metadata.sd1_scenario === "underground" ? "地下洞室 K0+120 支护工点（合成）" : "地上厂区 1 号基础工点（合成）";
const explicitId = new URLSearchParams(location.search).get("project_id");

function message(text, kind = "") { el("message").textContent = text; el("message").className = `message ${kind}`; }
function invalidate() {
  state.valid = false;
  document.body.classList.add("stale");
  for (const id of ["stock-total", "stock-a", "stock-b", "consume-cost"]) el(id).textContent = "—";
  el("progress").textContent = "等待读取 / 核对";
  el("completeness").textContent = "当前数据尚未核对；不展示完整金额结论";
  renderButtons();
}

async function request(path, options = {}) {
  const headers = {Accept: "application/json", ...options.headers};
  if (state.token) headers.Authorization = `Bearer ${state.token}`;
  if (options.body) headers["Content-Type"] = "application/json";
  const response = await fetch(path, {...options, headers, cache: "no-store", signal: AbortSignal.timeout(30000)});
  const data = await response.json().catch(() => null);
  if (!response.ok) {
    const detail = typeof data?.detail === "string" ? data.detail : "请核对本机应用状态与权限";
    throw new Error(`应用返回 ${response.status}：${detail}`);
  }
  return data;
}

function eligible(project, allowTest = false) {
  const meta = project.metadata || {};
  const formal = /^SD1-DEMO-(GROUND|UNDERGROUND)$/.test(meta.sd1_namespace || "");
  const ownTest = allowTest && /^SD1-TEST-T03-(GROUND|UNDERGROUND)(?:-[A-Za-z0-9]+)*$/.test(meta.sd1_namespace || "");
  return (formal || ownTest) && meta.sd1_synthetic === true &&
    ["ground", "underground"].includes(meta.sd1_scenario) &&
    meta.sd1_namespace.includes(meta.sd1_scenario.toUpperCase()) &&
    (project.name === meta.sd1_namespace || project.name.startsWith(meta.sd1_namespace + "｜")) &&
    project.description?.includes(MARKER) && project.currency === "CNY";
}

async function verifyAccess() {
  const [project, user] = await Promise.all([
    request(`/api/v1/projects/${state.project.id}`), request("/api/v1/users/me/"),
  ]);
  if (!eligible(project, Boolean(explicitId && project.id === explicitId))) throw new Error("项目缺少本演示的名称、描述或合成标识，已停止操作。");
  if (project.owner_id !== user.id) throw new Error("当前账户不是该合成项目的所有者，已停止操作。");
  if (!user.permissions?.includes("site_inventory.write")) throw new Error("当前账户没有原生材料台账写入权限，已停止操作。");
  state.project = project;
  state.user = user;
}

function validateLedger(rows) {
  if (!Array.isArray(rows)) throw new Error("原生流水返回结构异常。");
  if (rows.length >= 201) throw new Error("流水达到本次读取上限，无法确认完整记录；已停止四步操作与金额汇总，请打开原生业务页核对。");
  if (rows.length > 4) throw new Error("项目已有四步样例以外的流水，已停止四步操作与金额汇总，请在原生业务页核对。");
  const done = new Map();
  for (const row of rows) {
    const step = STEPS.find(s => row.note?.includes(`[sd1_step=${s.key}]`));
    if (!step || done.has(step.key) || !row.note.includes(MARKER) || !row.note.includes(`[sd1_namespace=${namespace()}]`) ||
        row.item_id !== state.item.id || row.movement_type !== step.type ||
        Number(row.quantity) !== step.quantity || Number(row.unit_cost) !== 400 || row.currency !== "CNY" ||
        row.location_id !== state.locations.A.id ||
        (step.key === "transfer" ? row.to_location_id !== state.locations.B.id : Boolean(row.to_location_id))) {
      throw new Error("实际台账与四步合成样例不一致，已停止重复入账；请打开原生业务页核对原始记录。");
    }
    done.set(step.key, row);
  }
  // A later step without its predecessors is not a valid state for this guided sample.
  if (STEPS.some((s, index) => done.has(s.key) && STEPS.slice(0, index).some(p => !done.has(p.key)))) {
    throw new Error("流水步骤不连续，请在原生业务页核对；导览不会补写不明确的历史。");
  }
  return done;
}

function stockAmount(response) {
  if (!Array.isArray(response?.rows)) throw new Error("原生库存汇总结构异常。");
  const row = response.rows.find(r => r.item_id === state.item.id);
  if (row && !Number.isFinite(Number(row.on_hand))) throw new Error("原生库存数量格式异常。");
  return row ? row.on_hand : "0";
}

function renderButtons() {
  const next = STEPS.find(s => !state.done.has(s.key));
  for (const step of STEPS) {
    const card = document.querySelector(`[data-step="${step.key}"]`);
    const button = el(`step-${step.key}`);
    const complete = state.valid && state.done.has(step.key);
    const current = state.valid && next?.key === step.key;
    card.classList.toggle("complete", complete);
    card.classList.toggle("current", current);
    card.querySelector(".step-status").textContent = complete ? "✓ 已入账" : current ? "当前步骤" : "等待前序步骤";
    button.disabled = state.busy || !current;
    button.textContent = complete ? "已完成 · 查看下方台账" : step.action;
  }
  el("project-select").disabled = state.busy || Boolean(explicitId) || !state.project;
  el("refresh").disabled = state.busy || !state.project;
}

function renderLedger() {
  const tbody = el("ledger");
  tbody.replaceChildren();
  if (!state.movements.length) {
    const row = tbody.insertRow(); const cell = row.insertCell(); cell.colSpan = 6; cell.className = "empty";
    cell.textContent = "尚无流水。点击「入库 100 吨」开始本次演示。";
  }
  for (const step of STEPS) {
    const movement = state.done.get(step.key);
    if (!movement) continue;
    const row = tbody.insertRow();
    const action = row.insertCell(); action.append(document.createTextNode(step.title));
    const id = document.createElement("code"); id.textContent = movement.id; action.append(id);
    const fields = [number(movement.quantity) + " 吨", step.key === "transfer" ? "A 库 → B 库" : step.key === "inbound" ? "进场 → A 库" : step.key === "consume" ? "A 库 → 施工工点" : "A 库 → 损耗", number(movement.unit_cost), number(Number(movement.quantity) * Number(movement.unit_cost))];
    for (const text of fields) row.insertCell().textContent = text;
    const note = row.insertCell();
    const details = document.createElement("details");
    const summary = document.createElement("summary");
    summary.textContent = workpoint() + " · 原始备注";
    const original = document.createElement("p"); original.textContent = movement.note;
    details.append(summary, original); note.append(details);
  }
}

async function refresh() {
  invalidate();
  await verifyAccess();
  const [locations, items] = await Promise.all([request(apiPrefix() + "/locations"), request(apiPrefix() + "/items")]);
  const materials = items.filter(i => i.sku === "SD1-CEMENT" && i.is_active && i.unit === "t" && i.currency === "CNY" && Number(i.standard_unit_cost) === 400);
  const findLocation = code => locations.filter(l => l.code === code && l.is_active);
  if (materials.length !== 1 || findLocation("A").length !== 1 || findLocation("B").length !== 1) throw new Error("需要唯一的合成水泥材料（SD1-CEMENT）和 A、B 库位；请先完成本机样例准备。");
  state.item = materials[0]; state.locations = {A: findLocation("A")[0], B: findLocation("B")[0]};
  const [rows, total, a, b] = await Promise.all([
    request(apiPrefix() + "/movements?limit=201"), request(apiPrefix() + "/stock-on-hand"),
    request(apiPrefix() + `/stock-on-hand?location_id=${state.locations.A.id}`),
    request(apiPrefix() + `/stock-on-hand?location_id=${state.locations.B.id}`),
  ]);
  state.done = validateLedger(rows); state.movements = rows;
  el("stock-total").textContent = number(stockAmount(total));
  el("stock-a").textContent = number(stockAmount(a));
  el("stock-b").textContent = number(stockAmount(b));
  const consume = state.done.get("consume");
  el("consume-cost").textContent = consume ? number(Number(consume.quantity) * Number(consume.unit_cost)) : "0";
  el("location-a").textContent = state.locations.A.name;
  el("location-b").textContent = state.locations.B.name;
  el("workpoint").textContent = "工点：" + workpoint();
  el("progress").textContent = `${state.done.size} / 4 步已入账`;
  el("completeness").textContent = state.done.size === 4 ? "已取到完整四笔流水 · 数量、单价、库位与步骤已核对" : `已取到当前全部 ${state.done.size} 笔流水 · 本样例共四步`;
  el("updated-at").textContent = "最近读取 " + new Date().toLocaleTimeString("zh-CN", {hour12: false});
  el("native-link").href = `/projects/${state.project.id}/site-inventory`;
  el("project-caption").textContent = state.project.name;
  state.valid = true; document.body.classList.remove("stale");
  renderLedger(); renderButtons();
}

async function busyOperation(action) {
  if (state.busy) return;
  state.busy = true; renderButtons();
  try { await action(); }
  catch (error) { invalidate(); message(`${error.message} 请重新读取台账后再操作。`, "error"); }
  finally { state.busy = false; renderButtons(); }
}

async function recordStep(key) {
  await busyOperation(async () => {
    message("正在核对实际台账，请稍候…", "busy");
    const execute = async () => {
      await refresh();
      if (state.done.has(key)) { message("这一步已在原生台账中完成，没有重复入账。"); return; }
      const step = STEPS.find(s => s.key === key);
      if (STEPS.find(s => !state.done.has(s.key))?.key !== key) throw new Error("请按当前步骤依次操作。");
      const body = {item_id: state.item.id, movement_type: step.type, quantity: String(step.quantity), unit_cost: "400", currency: "CNY", location_id: state.locations.A.id,
        note: `[sd1_step=${key}] [sd1_namespace=${namespace()}] ${MARKER}｜${workpoint()}｜${step.title} ${step.quantity} 吨`,
        metadata: {sd1_step: key, sd1_namespace: namespace(), sd1_synthetic: true, workpoint: workpoint()}};
      if (key === "transfer") body.to_location_id = state.locations.B.id;
      message(`正在向原生应用提交「${step.title}」…`, "busy");
      await request(apiPrefix() + "/movements", {method: "POST", body: JSON.stringify(body)});
      await refresh();
      message(state.done.size === 4 ? "四步已完成。总库存与库位余额已从原生应用重新读取，下方保留完整四笔流水。" : `${step.title}已入账，库存与原始流水已重新读取。请继续下一步。`);
    };
    // Same-origin tabs cooperate; cross-device/server idempotency remains outside this static guide.
    if (navigator.locks) await navigator.locks.request(`sd1-demo-${state.project.id}`, execute);
    else await execute();
  });
}

async function discoverProjects() {
  if (explicitId) {
    if (!/^[0-9a-f-]{36}$/i.test(explicitId)) throw new Error("指定项目编号格式不正确。");
    const project = await request(`/api/v1/projects/${explicitId}`);
    if (!eligible(project, true)) throw new Error("指定项目不属于已标识的正式演示或 T03 独立测试项目。");
    return [project];
  }
  const found = [];
  for (let offset = 0; offset < 10000; offset += 500) {
    const page = await request(`/api/v1/projects/?limit=500&offset=${offset}`);
    if (!Array.isArray(page)) throw new Error("项目列表返回结构异常。");
    found.push(...page.filter(p => eligible(p) && p.owner_id === state.user.id));
    if (page.length < 500) return found.sort((a, b) => a.name.localeCompare(b.name));
  }
  throw new Error("项目列表过长，未完成发现；可显式指定已标识的演示项目编号。");
}

async function boot() {
  await busyOperation(async () => {
    if (!["127.0.0.1", "localhost", "[::1]"].includes(location.hostname)) throw new Error("本页仅供本机合成演示，请通过 127.0.0.1 打开。");
    const config = await request("./demo-config.json");
    el("account-notice").textContent = `公开本机测试账户：${config.email}；口令：${config.password}。${config.notice}`;
    const auth = await request("/api/v1/users/auth/login/", {method: "POST", body: JSON.stringify({email: config.email, password: config.password})});
    state.token = auth.access_token; // Memory only; never written to browser storage or evidence.
    state.user = await request("/api/v1/users/me/");
    const projects = await discoverProjects();
    const select = el("project-select"); select.replaceChildren();
    if (!projects.length) { select.add(new Option("尚未准备正式演示项目", "")); throw new Error("未发现带有本项目标记的地上或地下演示项目，请先准备合成样例。"); }
    for (const project of projects) {
      const scenario = project.metadata.sd1_scenario === "underground" ? "地下施工 · 洞室支护" : "地上施工 · 厂区基础";
      select.add(new Option(scenario + (project.name.startsWith("SD1-TEST-T03-") ? "（独立验收）" : ""), project.id));
    }
    state.project = projects[0];
    select.addEventListener("change", () => busyOperation(async () => {
      state.project = projects.find(p => p.id === select.value); state.done = new Map();
      message("正在读取所选场景…", "busy"); await refresh(); message("已读取所选场景的实际库存与台账。");
    }));
    await refresh(); message("已连接本机开源应用。按当前步骤操作，结果会写入原生台账。");
  });
}
document.querySelectorAll("[data-action]").forEach(button => button.addEventListener("click", () => recordStep(button.dataset.action)));
el("refresh").addEventListener("click", () => busyOperation(async () => { message("正在重新读取原生台账…", "busy"); await refresh(); message("已重新读取实际台账；本次读取没有新增流水。"); }));
boot();
