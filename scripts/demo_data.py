"""Repeatable Chinese synthetic scenarios over native OpenConstructionERP APIs.

Examples (from the repository root):
  .venv/bin/python scripts/demo_data.py prepare --scenario ground
  .venv/bin/python scripts/demo_data.py complete --scenario ground
  .venv/bin/python scripts/demo_data.py verify --scenario ground
  .venv/bin/python scripts/demo_data.py reset --scenario ground

Reset archives the one explicitly owned active scenario through the upstream API;
its historical ledger remains retained. Run prepare afterwards to start a new one.
Sequential CLI replay is idempotent. Browser/CLI use is single-operator: the upstream
API has no server-side idempotency keys. Never run two writers for the same scenario.
"""
from __future__ import annotations

import argparse
from decimal import Decimal
import json
from pathlib import Path
import re
import sys
import uuid

from demo_api import DemoAPI, ROOT, utc_now, write_json

FIXTURE = json.loads((ROOT / "fixtures/material_scenarios.json").read_text(encoding="utf-8"))
NOTICE = FIXTURE["synthetic_notice"]
MANAGED_BY = "scripts/demo_data.py"


class ScenarioError(RuntimeError):
    pass


class MaterialScenario:
    def __init__(self, api, scenario="ground", namespace="SD1-DEMO", state_path=None):
        if scenario not in {"ground", "underground"}:
            raise ScenarioError("场景仅支持 ground / underground")
        if namespace != "SD1-DEMO" and not re.fullmatch(r"SD1-TEST-T02(?:-[A-Z0-9]+)*", namespace):
            raise ScenarioError("命名空间仅允许 SD1-DEMO 或 SD1-TEST-T02-*，不能触碰其他任务")
        self.api = api
        self.scenario = scenario
        self.namespace = f"{namespace}-{scenario.upper()}"
        self.definition = FIXTURE[scenario]
        self.name = f"{self.namespace}｜{self.definition['title']}"
        self.state_path = Path(state_path) if state_path else ROOT / ".runtime/demo-state.json"
        self.metadata = {"sd1_namespace": self.namespace, "sd1_scenario": scenario,
                         "sd1_synthetic": True, "sd1_managed_by": MANAGED_BY,
                         "sd1_fixture_version": FIXTURE["fixture_version"]}
        self.ticket_path = ROOT / '.runtime/create-tickets' / (self.namespace + '.json')

    def assert_owned(self, project):
        if not self.api.user_id or project.get('owner_id') != self.api.user_id:
            raise ScenarioError('项目不属于当前演示账户，拒绝操作')
        if (project.get("name") != self.name
                or NOTICE not in project.get("description", "")
                or any(project.get("metadata", {}).get(key) != value for key, value in self.metadata.items())):
            raise ScenarioError(f"项目 {project.get('id')} 名称、描述或 metadata 不匹配，拒绝操作")
        if project.get("currency") != "CNY":
            raise ScenarioError("项目币种不是 CNY")

    def find_project(self, repair_creation=False):
        candidates = [p for p in self.api.projects() if p["name"] == self.name]
        if len(candidates) > 1:
            raise ScenarioError("存在多个同名活动项目，拒绝猜测目标")
        if not candidates:
            return None
        project = candidates[0]
        try:
            self.assert_owned(project)
        except ScenarioError:
            if not repair_creation:
                raise
            project = self.finish_creation(project)
        return project

    def finish_creation(self, project):
        if not self.ticket_path.is_file():
            raise ScenarioError('项目身份不匹配且无本地创建凭据，拒绝接管')
        ticket = json.loads(self.ticket_path.read_text())
        if (ticket.get('owner_id') != self.api.user_id or project.get('owner_id') != self.api.user_id
                or ticket.get('namespace') != self.namespace or project.get('name') != self.name
                or project.get('currency') != 'CNY' or NOTICE not in (project.get('description') or '')
                or f"[sd1_creation={ticket.get('nonce')}]" not in (project.get('description') or '')
                or (ticket.get('project_id') and ticket['project_id'] != project.get('id'))
                or any(key.startswith('sd1_') for key in project.get('metadata', {}))):
            raise ScenarioError('创建凭据或项目归属不匹配，拒绝修补未知项目')
        ticket['project_id'] = project['id']
        write_json(self.ticket_path, ticket)
        project = self.api.request('PATCH', f"/api/v1/projects/{project['id']}", {'metadata': self.metadata})
        self.assert_owned(project)
        return project

    def ensure_project(self):
        project = self.find_project(repair_creation=True)
        if project is None:
            ticket = {'namespace': self.namespace, 'owner_id': self.api.user_id, 'nonce': uuid.uuid4().hex}
            # Persist the creation marker BEFORE POST, so a lost response or a
            # failed metadata PATCH can be recovered without adopting a namesake.
            write_json(self.ticket_path, ticket)
            project = self.api.request("POST", "/api/v1/projects/", {
                "name": self.name, "description": f"{NOTICE}；{self.definition['workpoint']}；假设单价400元/吨，非市场报价。[sd1_creation={ticket['nonce']}]",
                "currency": "CNY", "locale": "zh", "country_code": "CN"})
            # v19 ProjectCreate omits metadata; ProjectUpdate supports it.
            project = self.finish_creation(project)
        self.assert_owned(project)
        return project

    def context(self, create=False):
        project = self.ensure_project() if create else self.find_project()
        if project is None:
            raise ScenarioError("场景尚未准备；请先运行 prepare")
        pid = project["id"]
        locations = self.api.inventory_list(pid, "locations")
        result = {}
        for code, name in self.definition["locations"].items():
            matches = [loc for loc in locations if loc.get("code") == code]
            if not matches and create:
                matches = [self.api.request("POST", self.api.inventory_path(pid, "locations"),
                                            {"name": name, "code": code, "metadata": self.metadata})]
            if len(matches) != 1 or matches[0]["name"] != name or not matches[0]["is_active"]:
                raise ScenarioError(f"库位 {code} 缺失、重复或被修改")
            result[code] = matches[0]["id"]
        items = self.api.inventory_list(pid, "items")
        matches = [item for item in items if item.get("sku") == FIXTURE["material"]["sku"]]
        if not matches and create:
            matches = [self.api.request("POST", self.api.inventory_path(pid, "items"),
                                        {**FIXTURE["material"], "metadata": self.metadata})]
        if len(matches) != 1:
            raise ScenarioError("样例材料缺失或重复")
        item = matches[0]
        for key in ("name", "unit", "currency"):
            if item.get(key) != FIXTURE["material"][key]:
                raise ScenarioError(f"材料 {key} 与合成样例不一致")
        if Decimal(item.get("standard_unit_cost") or "0") != Decimal("400") or not item["is_active"]:
            raise ScenarioError("材料单价或启用状态被修改")
        return {"project_id": pid, "item_id": item["id"], "locations": result,
                "scenario": self.scenario, "namespace": self.namespace}

    def payload(self, context, step):
        note = (f"[sd1_step={step['key']}] [sd1_namespace={self.namespace}] {NOTICE}｜"
                f"{self.definition['workpoint']}｜{step['label']} {step['quantity']} 吨｜"
                f"单据 {step['document']}｜假设单价400元/吨（CNY/t）")
        return {"item_id": context["item_id"], "movement_type": step["movement_type"],
                "quantity": step["quantity"], "unit_cost": "400", "currency": "CNY",
                "location_id": context["locations"]["A"],
                "to_location_id": context["locations"]["B"] if step["key"] == "transfer" else None,
                "note": note,
                "metadata": {**self.metadata, "sd1_step": step["key"], "unit": "t",
                             "workpoint": self.definition["workpoint"], "document": step["document"]}}

    def validate_movements(self, context):
        rows = self.api.movements(context["project_id"], context["item_id"])
        seen = {}
        for row in rows:
            note = row.get("note") or ""
            matches = [step for step in FIXTURE["steps"] if f"[sd1_step={step['key']}]" in note]
            if len(matches) != 1 or f"[sd1_namespace={self.namespace}]" not in note or NOTICE not in note:
                raise ScenarioError("样例材料出现未知流水，拒绝重复补账或宣称成本完整")
            step = matches[0]
            if step["key"] in seen:
                raise ScenarioError(f"样例步骤 {step['key']} 有重复流水")
            expected = self.payload(context, step)
            for field in ("item_id", "movement_type", "currency", "location_id", "to_location_id"):
                if row.get(field) != expected[field]:
                    raise ScenarioError(f"步骤 {step['key']} 的 {field} 不符合样例")
            for field in ("quantity", "unit_cost"):
                if Decimal(row[field]) != Decimal(expected[field]):
                    raise ScenarioError(f"步骤 {step['key']} 的 {field} 不符合样例")
            seen[step["key"]] = row
        return seen

    def save_state(self, context, steps):
        stage = "complete" if len(steps) == 4 else "ready" if not steps else "prepared" if set(steps) == {"inbound"} else "partial"
        state = {**context, "stage": stage, "steps": {key: row["id"] for key, row in steps.items()},
                 "synthetic_notice": NOTICE, "updated_at": utc_now()}
        write_json(self.state_path, state)
        return state

    def apply_steps(self, keys):
        context = self.context(create=True)
        seen = self.validate_movements(context)
        for step in FIXTURE["steps"]:
            if step["key"] in keys and step["key"] not in seen:
                self.api.request("POST", self.api.inventory_path(context["project_id"], "movements"),
                                 self.payload(context, step))
                seen = self.validate_movements(context)
                self.save_state(context, seen)
        return self.save_state(context, seen)

    def prepare(self):
        return self.apply_steps({"inbound"})

    def ready(self):
        """Create only project/material/locations, leaving all four UI actions available."""
        context = self.context(create=True)
        return self.save_state(context, self.validate_movements(context))

    def complete(self):
        return self.apply_steps({step["key"] for step in FIXTURE["steps"]})

    def verify(self):
        context = self.context()
        seen = self.validate_movements(context)
        if set(seen) != {step["key"] for step in FIXTURE["steps"]}:
            raise ScenarioError("完整验收需要入库、领用、损耗、调拨四步，请先运行 complete")
        pid, item = context["project_id"], context["item_id"]
        balances = {"total": self.api.stock(pid, item),
                    **{key: self.api.stock(pid, item, location) for key, location in context["locations"].items()}}
        for key, expected in {"total": "68", "A": "58", "B": "10"}.items():
            if Decimal(balances[key]) != Decimal(expected):
                raise ScenarioError(f"{key} 库存为 {balances[key]}，期望 {expected} 吨")
        # Presentation amount only; inventory balances always come from upstream.
        cost = sum((Decimal(row["quantity"]) * Decimal(row["unit_cost"])
                    for row in seen.values() if row["movement_type"] == "CONSUMPTION"), Decimal("0"))
        if cost != Decimal("12000"):
            raise ScenarioError(f"领用金额 {cost} 不等于 12000 CNY")
        return {**self.save_state(context, seen), "verified": True, "balances_t": balances,
                "consumption_cost_cny": str(cost), "cost_basis": "假设400 CNY/t × 实际领用30 t，非财务入账",
                "movement_count": len(seen)}

    def reset(self):
        project = self.find_project()
        if project is not None:
            # Read fresh details immediately before the upstream archive operation.
            detail = self.api.request("GET", f"/api/v1/projects/{project['id']}")
            self.assert_owned(detail)
            self.api.request("DELETE", f"/api/v1/projects/{project['id']}/", expected=(204,))
            archived = [p for p in self.api.projects(include_archived=True) if p["id"] == project["id"]]
            if len(archived) != 1 or archived[0]["status"] != "archived" or self.find_project() is not None:
                raise ScenarioError("上游未确认场景归档")
        state = {"project_id": None, "item_id": None, "locations": {}, "namespace": self.namespace,
                 "scenario": self.scenario, "stage": "reset", "archived": [project["id"]] if project else [],
                 "synthetic_notice": NOTICE, "updated_at": utc_now()}
        write_json(self.state_path, state)
        return state


def main():
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("command", choices=("ready", "prepare", "complete", "verify", "reset"))
    parser.add_argument("--scenario", choices=("ground", "underground"), default="ground")
    parser.add_argument("--namespace", default="SD1-DEMO", help="默认正式样例；自动化测试使用 SD1-TEST-T02-* 隔离")
    parser.add_argument("--state-file", type=Path, default=ROOT / ".runtime/demo-state.json")
    parser.add_argument("--evidence", type=Path, help="保存脱敏 HTTP 证据（不含凭证）")
    args = parser.parse_args()
    api = DemoAPI()
    started = utc_now()
    exit_code = 0
    result = None
    try:
        scenario = MaterialScenario(api, args.scenario, args.namespace, args.state_file)
        api.login()
        result = getattr(scenario, args.command)()
        print(json.dumps(result, ensure_ascii=False, indent=2))
    except Exception as exc:
        exit_code = 1
        result = {"error": str(exc)}
        print(json.dumps(result, ensure_ascii=False), file=sys.stderr)
    finally:
        if args.evidence:
            write_json(args.evidence, {"command": sys.argv, "started_at": started, "finished_at": utc_now(),
                                      "exit_code": exit_code, "result": result, "http": api.records})
        api.close()
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
