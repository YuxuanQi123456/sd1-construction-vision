"""Real HTTP acceptance tests. Only SD1-TEST-T02-* synthetic projects are written.

Run with the application's Python interpreter while its one shared service runs:
  .venv/bin/python tests/test_material_flow.py --evidence evidence/T02/material-flow.json
No mocking, database writes, service lifecycle changes, or global cleanup.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor
from decimal import Decimal
import json
from pathlib import Path
import sys
import threading
import time
import unittest
from unittest.mock import patch
import uuid

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))
from demo_api import DemoAPI, utc_now, write_json
from demo_data import MaterialScenario, NOTICE, ScenarioError


class MaterialFlowHTTP(unittest.TestCase):
    api = None
    run_id = None
    findings = []

    def setUp(self):
        case = self.id().rsplit(".", 1)[-1].removeprefix("test_").upper().replace("_", "-")
        self.base_namespace = f"SD1-TEST-T02-{self.run_id}-{case}"
        self.scenario = MaterialScenario(self.api, namespace=self.base_namespace,
                                         state_path=ROOT / "evidence/T02/test-state.json")
        self.context = self.scenario.prepare()
        self.addCleanup(self.scenario.reset)

    def record(self, **data):
        self.findings.append({"test": self.id().rsplit(".", 1)[-1], "at": utc_now(), **data})

    def new_item(self, suffix):
        return self.api.request("POST", self.api.inventory_path(self.context["project_id"], "items"), {
            "name": f"T02 {suffix}验证水泥（自制合成数据）", "sku": f"T02-{suffix}",
            "unit": "t", "standard_unit_cost": "400", "currency": "CNY",
            "metadata": {**self.scenario.metadata, "test_case": suffix}})["id"]

    def movement(self, item, kind, quantity, *, source="A", target=None, expected=(201,)):
        body = {"item_id": item, "movement_type": kind, "quantity": str(quantity),
                "unit_cost": "400", "currency": "CNY", "location_id": self.context["locations"][source],
                "note": f"{NOTICE}｜{self.scenario.namespace}｜独立边界验证 {kind} {quantity} 吨",
                "metadata": {**self.scenario.metadata, "unit": "t", "test_case": self.id()}}
        if target:
            body["to_location_id"] = self.context["locations"][target]
        return self.api.request("POST", self.api.inventory_path(self.context["project_id"], "movements"),
                                body, expected=expected)

    def item_rows(self, item):
        return self.api.movements(self.context["project_id"], item)

    def item_stock(self, item, location=None):
        return Decimal(self.api.stock(self.context["project_id"], item,
                                      self.context["locations"][location] if location else None))

    def test_complete_and_sequential_idempotency(self):
        first = self.context
        second = self.scenario.prepare()
        self.assertEqual(first["project_id"], second["project_id"])
        self.assertEqual(first["item_id"], second["item_id"])
        self.assertEqual(first["locations"], second["locations"])
        self.assertEqual(first["steps"], second["steps"])
        self.assertEqual(len(self.item_rows(first["item_id"])), 1)
        complete = self.scenario.complete()
        replay = self.scenario.complete()
        prepare_after_complete = self.scenario.prepare()
        self.assertEqual(complete["steps"], replay["steps"])
        self.assertEqual(complete["steps"], prepare_after_complete["steps"])
        verified = self.scenario.verify()
        self.assertEqual(verified["movement_count"], 4)
        self.assertEqual(Decimal(verified["consumption_cost_cny"]), Decimal("12000"))
        self.assertEqual({k: Decimal(v) for k, v in verified["balances_t"].items()},
                         {"total": Decimal(68), "A": Decimal(58), "B": Decimal(10)})
        self.record(project_id=first["project_id"], verified=verified,
                    sequential_replay="prepare twice, complete twice, prepare after complete: stable IDs and four rows")

    def test_underground(self):
        scenario = MaterialScenario(self.api, "underground", self.base_namespace,
                                    ROOT / "evidence/T02/test-state.json")
        self.addCleanup(scenario.reset)
        scenario.prepare()
        scenario.complete()
        verified = scenario.verify()
        rows = self.api.movements(verified["project_id"], verified["item_id"])
        self.assertTrue(all("地下洞室 K0+120" in row["note"] for row in rows))
        self.assertEqual(len(rows), 4)
        self.record(verified=verified)

    def test_insufficient_stock_409_no_ledger_growth(self):
        item = self.new_item("INSUFFICIENT")
        self.movement(item, "INBOUND", 10)
        before = self.item_rows(item)
        for kind in ("CONSUMPTION", "WASTE", "TRANSFER"):
            self.movement(item, kind, 11, target="B" if kind == "TRANSFER" else None, expected=(409,))
            self.assertEqual([r["id"] for r in before], [r["id"] for r in self.item_rows(item)])
            self.assertEqual(self.item_stock(item, "A"), Decimal(10))
            self.assertEqual(self.item_stock(item, "B"), Decimal(0))
        self.record(project_id=self.context["project_id"], item_id=item,
                    result="CONSUMPTION/WASTE/TRANSFER each returned 409; rows remain 1; A=10, B=0")

    def test_concurrent_consumption_only_one_succeeds(self):
        item = self.new_item("CONCURRENT")
        self.movement(item, "INBOUND", 10)
        barrier = threading.Barrier(2)

        def consume():
            barrier.wait(timeout=15)
            return self.movement(item, "CONSUMPTION", 7, expected=(201, 409))

        with ThreadPoolExecutor(max_workers=2) as pool:
            requests = [pool.submit(consume) for _ in range(2)]
            responses = [request.result(timeout=60) for request in requests]
        statuses = sorted(201 if isinstance(response, dict) and "id" in response else 409 for response in responses)
        self.assertEqual(statuses, [201, 409])
        rows = self.item_rows(item)
        self.assertEqual(len(rows), 2)
        self.assertEqual(sum(r["movement_type"] == "CONSUMPTION" for r in rows), 1)
        self.assertEqual(self.item_stock(item), Decimal(3))
        self.assertEqual(self.item_stock(item, "A"), Decimal(3))
        self.record(project_id=self.context["project_id"], item_id=item, statuses=statuses,
                    movement_ids=[r["id"] for r in rows], remaining_t="3")

    def test_same_source_destination_422(self):
        item = self.new_item("SAME-LOCATION")
        self.movement(item, "INBOUND", 10)
        before = self.item_rows(item)
        self.movement(item, "TRANSFER", 1, target="A", expected=(422,))
        self.assertEqual([r["id"] for r in before], [r["id"] for r in self.item_rows(item)])
        self.assertEqual(self.item_stock(item), Decimal(10))
        self.record(project_id=self.context["project_id"], item_id=item, result="HTTP 422; unchanged one-row ledger")

    def test_empty_source_cannot_borrow_other_location(self):
        item = self.new_item("EMPTY-SOURCE")
        self.movement(item, "INBOUND", 10, source="B")
        before = self.item_rows(item)
        for kind in ("CONSUMPTION", "WASTE", "TRANSFER"):
            self.movement(item, kind, 1, source="A", target="B" if kind == "TRANSFER" else None, expected=(409,))
        self.assertEqual([r["id"] for r in before], [r["id"] for r in self.item_rows(item)])
        self.assertEqual(self.item_stock(item), Decimal(10))
        self.assertEqual(self.item_stock(item, "A"), Decimal(0))
        self.assertEqual(self.item_stock(item, "B"), Decimal(10))
        self.record(project_id=self.context["project_id"], item_id=item,
                    result="A empty, B=10; three A outflows refused 409, unchanged ledger")

    def test_reset_checks_identity_and_preserves_history(self):
        pid = self.context["project_id"]
        path = f"/api/v1/projects/{pid}"
        original = self.api.request("GET", path)
        for field, wrong in (("description", "T02 临时核验：缺少规定合成声明"),
                             ("metadata", {**original["metadata"], "sd1_namespace": "SD1-TEST-T02-WRONG"})):
            self.api.request("PATCH", path, {field: wrong})
            try:
                with self.assertRaises(ScenarioError):
                    self.scenario.reset()
                self.assertEqual(self.api.request("GET", path)["status"], "active")
            finally:
                self.api.request("PATCH", path, {field: original[field]})
        before = self.item_rows(self.context["item_id"])
        reset = self.scenario.reset()
        self.assertEqual(reset["archived"], [pid])
        archived = next(p for p in self.api.projects(include_archived=True) if p["id"] == pid)
        self.assertEqual(archived["status"], "archived")
        # Native detail/inventory endpoints hide archived projects. Restore the
        # exact owned test project to prove ledger retention, then archive again.
        self.api.request("POST", path + "/restore/")
        self.assertEqual([r["id"] for r in before], [r["id"] for r in self.item_rows(self.context["item_id"])])
        self.scenario.reset()
        self.assertEqual(self.scenario.reset()["archived"], [])
        restarted = self.scenario.prepare()
        self.assertNotEqual(restarted["project_id"], pid)
        self.assertEqual(len(restarted["steps"]), 1)
        self.record(archived_project_id=pid, fresh_project_id=restarted["project_id"],
                    result="description and metadata mismatch refused; reset retains old ledger; prepare creates one fresh inbound")

    def test_other_owner_is_rejected_without_writes(self):
        original = self.api.request('GET', f"/api/v1/projects/{self.context['project_id']}")
        foreign = {**original, 'owner_id': str(uuid.uuid4())}
        with patch.object(self.api, 'projects', return_value=[foreign]), patch.object(self.api, 'request') as request:
            with self.assertRaises(ScenarioError):
                self.scenario.reset()
            request.assert_not_called()
        self.record(result='Real project response with simulated foreign owner rejected; zero API writes')

    def test_interrupted_metadata_patch_recovers_exact_creation(self):
        scenario = MaterialScenario(self.api, namespace=self.base_namespace + '-RECOVERY')
        original_request = self.api.request
        created = []
        def interrupted(method, path, body=None, **kwargs):
            if method == 'PATCH' and body and body.get('metadata') == scenario.metadata:
                raise RuntimeError('Injected connection interruption before metadata PATCH')
            result = original_request(method, path, body, **kwargs)
            if method == 'POST' and path == '/api/v1/projects/':
                created.append(result['id'])
            return result
        with patch.object(self.api, 'request', side_effect=interrupted):
            with self.assertRaises(RuntimeError):
                scenario.prepare()
        self.assertEqual(len(created), 1)
        recovered = scenario.prepare()
        self.addCleanup(scenario.reset)
        self.assertEqual(recovered['project_id'], created[0])
        replay = scenario.prepare()
        self.assertEqual(recovered['steps'], replay['steps'])
        self.record(project_id=created[0], result='Actual created project recovered after injected pre-PATCH interruption; same ID and one inbound')

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--evidence", type=Path, default=ROOT / "evidence/T02/material-flow.json")
    args = parser.parse_args()
    api = DemoAPI()
    started = utc_now()
    run_id = time.strftime("%Y%m%dT%H%M%S", time.gmtime()) + "-" + uuid.uuid4().hex[:6].upper()
    MaterialFlowHTTP.api = api
    MaterialFlowHTTP.run_id = run_id
    result = None
    error = None
    try:
        api.login()
        suite = unittest.defaultTestLoader.loadTestsFromTestCase(MaterialFlowHTTP)
        result = unittest.TextTestRunner(verbosity=2).run(suite)
        exit_code = 0 if result.wasSuccessful() else 1
    except Exception as exc:
        error = str(exc)
        exit_code = 1
        print(error, file=sys.stderr)
    finally:
        write_json(args.evidence, {"command": sys.argv, "run_id": run_id, "started_at": started,
                   "finished_at": utc_now(), "exit_code": exit_code, "error": error,
                   "tests_run": result.testsRun if result else 0,
                   "failures": [(str(t), trace) for t, trace in result.failures] if result else [],
                   "errors": [(str(t), trace) for t, trace in result.errors] if result else [],
                   "findings": MaterialFlowHTTP.findings, "http": api.records})
        api.close()
    print(json.dumps({"evidence": str(args.evidence), "exit_code": exit_code,
                      "tests_run": result.testsRun if result else 0}, ensure_ascii=False))
    return exit_code


if __name__ == "__main__":
    raise SystemExit(main())
