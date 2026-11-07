"""Small local-only HTTP client for the pinned upstream application.

No database access, ledger implementation, credential persistence or registration.
"""
from __future__ import annotations

import json
import time
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlparse

import httpx

ROOT = Path(__file__).resolve().parents[1]
MOVEMENT_LIMIT = 5000


def utc_now():
    return datetime.now(timezone.utc).isoformat()


def redact(value):
    if isinstance(value, dict):
        return {key: redact(item) for key, item in value.items()
                if not any(secret in key.lower() for secret in ("token", "password", "authorization"))}
    if isinstance(value, list):
        return [redact(item) for item in value]
    return value


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(redact(value), ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


class APIError(RuntimeError):
    pass


class DemoAPI:
    def __init__(self, config=None, records=None):
        self.config = config or json.loads((ROOT / "config/demo.json").read_text(encoding="utf-8"))
        parsed = urlparse(self.config["base_url"])
        if parsed.scheme != "http" or parsed.hostname not in {"127.0.0.1", "localhost", "::1"}:
            raise ValueError("演示客户端仅允许本机 HTTP 服务")
        self.client = httpx.Client(base_url=self.config["base_url"], trust_env=False, timeout=60)
        self.records = records if records is not None else []
        self.user_id = None

    def close(self):
        self.client.close()

    def request(self, method, path, body=None, *, params=None, expected=(200, 201)):
        response = self.client.request(method, path, json=body, params=params)
        try:
            data = response.json() if response.content else None
        except ValueError:
            data = response.text[:300]
        self.records.append(redact({"at": utc_now(), "method": method, "path": path,
                                    "params": params, "request": body,
                                    "status": response.status_code, "response": data}))
        if response.status_code not in expected:
            raise APIError(f"{method} {path}: HTTP {response.status_code}: {redact(data)}")
        return data

    def login(self, wait_seconds=45):
        deadline = time.monotonic() + wait_seconds
        while True:
            try:
                self.request("GET", "/api/health")
                break
            except (httpx.ConnectError, httpx.ReadError, APIError):
                if time.monotonic() >= deadline:
                    raise
                time.sleep(1)
        result = self.request("POST", "/api/v1/users/auth/login/",
                              {key: self.config[key] for key in ("email", "password")})
        self.client.headers["Authorization"] = "Bearer " + result["access_token"]
        self.user_id = self.request("GET", "/api/v1/users/me/")["id"]

    @staticmethod
    def inventory_path(project_id, resource):
        return f"/api/v1/site-inventory/projects/{project_id}/{resource}"

    def projects(self, include_archived=False):
        """Native project endpoint returns a bare array, with offset pagination."""
        rows = []
        for offset in range(0, 100000, 500):
            params = {"offset": offset, "limit": 500}
            if include_archived:
                params["status"] = "all"
            page = self.request("GET", "/api/v1/projects/", params=params)
            if not isinstance(page, list):
                raise APIError("项目列表响应不是已验证的数组形态")
            rows.extend(page)
            if len(page) < 500:
                return rows
        raise APIError("项目列表超过安全分页上限；拒绝假定列表完整")

    def inventory_list(self, project_id, resource, **params):
        rows = self.request("GET", self.inventory_path(project_id, resource), params=params or None)
        if not isinstance(rows, list):
            raise APIError(f"{resource} 响应不是已验证的数组形态")
        return rows

    def movements(self, project_id, item_id=None):
        params = {"limit": MOVEMENT_LIMIT}
        if item_id:
            params["item_id"] = item_id
        rows = self.inventory_list(project_id, "movements", **params)
        if len(rows) >= MOVEMENT_LIMIT:
            raise APIError("流水达到 API 上限；无法证明完整，停止幂等判断和成本汇总")
        return rows

    def stock(self, project_id, item_id, location_id=None):
        params = {"location_id": location_id} if location_id else None
        data = self.request("GET", self.inventory_path(project_id, "stock-on-hand"), params=params)
        if not isinstance(data, dict) or not isinstance(data.get("rows"), list):
            raise APIError("库存响应缺少 rows 数组")
        rows = [row for row in data["rows"] if row["item_id"] == item_id]
        if len(rows) > 1:
            raise APIError("上游库存响应含重复物料")
        if rows and rows[0]["unit"] != "t":
            raise APIError("库存单位不是吨 t")
        return rows[0]["on_hand"] if rows else "0"
