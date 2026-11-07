"""Real stdlib HTTP/offline restoration and security contract checks (no model loads)."""
import contextlib
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import importlib.util
import io
import json
from pathlib import Path
import stat
import tempfile
import threading
import unittest
import zipfile

SPEC = importlib.util.spec_from_file_location("restore_runtime_assets", Path(__file__).resolve().parents[1] / "scripts/restore_runtime_assets.py")
restore = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(restore)


def blob(content, **kwargs):
    return {"bytes": len(content), "sha256": hashlib.sha256(content).hexdigest(), **kwargs}


def archive(files):
    output = io.BytesIO()
    with zipfile.ZipFile(output, "w") as z:
        for name, content in files.items():
            z.writestr(name, content)
    return output.getvalue()


class RuntimeAssetsTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.base = Path(self.temporary.name)
        self.root = self.base / "new-project"
        self.root.mkdir()
        self.offline = self.base / "offline"
        self.offline.mkdir()
        self.payload = b"original bytes\x00\xff"
        self.zip_bytes = archive({"downloads/ppe/model.pt": self.payload})
        self.zip_row = blob(self.zip_bytes, name="ppe.zip", url="https://example.invalid/ppe.zip")
        self.output_row = blob(self.payload, path="downloads/ppe/model.pt")
        self.manifest = {"schema": restore.SCHEMA, "repository": "fixture/repo", "release_tag": "fixture-v1",
                         "bundles": [{"id": "ppe", "profiles": ["ppe", "full"], "format": "zip",
                                      "assets": [self.zip_row], "files": [self.output_row]}], "external_files": []}
        (self.offline / "ppe.zip").write_bytes(self.zip_bytes)

    def load(self):
        path = self.base / "manifest.json"
        path.write_text(json.dumps(self.manifest))
        return restore.load_manifest(path)

    def execute(self, **kwargs):
        return restore.restore(self.root, self.load(), assets_dir=self.offline, **kwargs)

    def test_offline_zip_exact_bytes_verify_and_skip_without_source(self):
        result = self.execute(profile="ppe")
        self.assertEqual(result["restored"], 1)
        self.assertEqual((self.root / self.output_row["path"]).read_bytes(), self.payload)
        (self.offline / "ppe.zip").unlink()
        self.assertEqual(self.execute(profile="ppe")["restored"], 0)
        self.assertEqual(self.execute(verify_only=True)["mode"], "verified")
        self.assertFalse((self.root / ".runtime").exists())

    def add_parts(self):
        data = b"part one" + b"second part"
        assets = []
        for number, content in enumerate([b"part one", b"second part"]):
            name = f"weight.part{number}"
            (self.offline / name).write_bytes(content)
            assets.append(blob(content, name=name, url=f"https://example.invalid/{name}"))
        self.manifest["bundles"].append({"id": "full", "profiles": ["full"], "format": "raw-parts",
                                          "assets": assets, "files": [blob(data, path="downloads/qwen/model.safetensors")]})
        return data

    def test_raw_parts_order_and_full_hash(self):
        expected = self.add_parts()
        self.execute()
        self.assertEqual((self.root / "downloads/qwen/model.safetensors").read_bytes(), expected)

    def test_raw_parts_wrong_total_sha_never_publishes_output(self):
        self.add_parts()
        self.manifest["bundles"][-1]["files"][0]["sha256"] = "0" * 64
        with self.assertRaisesRegex(restore.AssetError, "Assembled"):
            self.execute()
        self.assertFalse((self.root / "downloads/qwen/model.safetensors").exists())
        self.assertFalse(list(self.root.rglob(".restore-*")))

    def test_wrong_part_sha_refused(self):
        self.add_parts()
        (self.offline / "weight.part1").write_bytes(b"BROKEN")
        with self.assertRaisesRegex(restore.AssetError, "Offline asset"):
            self.execute()
        self.assertFalse((self.root / "downloads/qwen/model.safetensors").exists())

    def test_profiles_training_and_read_only_plan(self):
        self.add_parts()
        training = self.manifest["bundles"][1].copy()
        training.update(id="training", profiles=["training"], files=[blob(b"part onesecond part", path="downloads/training/slice.bin")])
        self.manifest["bundles"].append(training)
        plan = self.execute(profile="ppe", plan=True)
        self.assertEqual(plan["files"], 1)
        self.assertEqual(self.execute(profile="ppe", training=True, plan=True)["files"], 2)
        self.assertEqual(self.execute(plan=True)["files"], 2)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_missing_verify_only_never_downloads(self):
        with self.assertRaisesRegex(restore.AssetError, "Missing restored"):
            self.execute(verify_only=True)
        self.assertEqual(list(self.root.iterdir()), [])

    def test_existing_different_content_is_preserved(self):
        path = self.root / self.output_row["path"]
        path.parent.mkdir(parents=True)
        path.write_bytes(b"precious local change")
        with self.assertRaisesRegex(restore.AssetError, "refusing overwrite"):
            self.execute()
        self.assertEqual(path.read_bytes(), b"precious local change")

    def test_destination_symlink_and_parent_symlink_refused(self):
        outside = self.base / "outside"
        outside.mkdir()
        (self.root / "downloads").symlink_to(outside, target_is_directory=True)
        with self.assertRaisesRegex(restore.AssetError, "Symlink"):
            self.execute()
        self.assertEqual(list(outside.iterdir()), [])

    def test_manifest_path_attacks(self):
        for bad in ("../outside", "/tmp/outside", "C:/outside", "downloads/../outside", "x\\outside", "x//y", "./x"):
            with self.subTest(path=bad):
                self.output_row["path"] = bad
                with self.assertRaisesRegex(restore.AssetError, "Unsafe"):
                    self.load()

    def replace_zip(self, data):
        self.zip_row.update(blob(data))
        (self.offline / "ppe.zip").write_bytes(data)

    def test_archive_path_attack_and_extra_member(self):
        for name in ("../outside", "/tmp/outside", "downloads/extra.pt"):
            with self.subTest(member=name):
                self.replace_zip(archive({self.output_row["path"]: self.payload, name: b"attack"}))
                with self.assertRaises(restore.AssetError):
                    self.execute()
                self.assertFalse((self.base / "outside").exists())
                self.assertFalse((self.root / self.output_row["path"]).exists())

    def test_archive_symlink_refused(self):
        buffer = io.BytesIO()
        with zipfile.ZipFile(buffer, "w") as z:
            info = zipfile.ZipInfo(self.output_row["path"])
            info.create_system = 3
            info.external_attr = (stat.S_IFLNK | 0o777) << 16
            z.writestr(info, b"/tmp/outside")
        self.replace_zip(buffer.getvalue())
        with self.assertRaisesRegex(restore.AssetError, "symlink/special"):
            self.execute()

    def test_bad_zip_member_sha_is_not_published(self):
        self.replace_zip(archive({self.output_row["path"]: b"X" * len(self.payload)}))
        with self.assertRaisesRegex(restore.AssetError, "SHA256"):
            self.execute()
        self.assertFalse((self.root / self.output_row["path"]).exists())

    def test_offline_symlink_asset_refused(self):
        (self.offline / "ppe.zip").unlink()
        outside = self.base / "out.zip"
        outside.write_bytes(self.zip_bytes)
        (self.offline / "ppe.zip").symlink_to(outside)
        with self.assertRaisesRegex(restore.AssetError, "Symlink"):
            self.execute()

    def test_http_zip_parts_and_external_headers(self):
        self.add_parts()
        external_content = b"official-video-original"
        requests = []
        sources = {"/ppe.zip": self.zip_bytes, "/weight.part0": b"part one", "/weight.part1": b"second part", "/original.mp4": external_content}
        class Handler(BaseHTTPRequestHandler):
            def do_GET(handler):
                requests.append((handler.path, dict(handler.headers)))
                handler.send_response(200)
                handler.end_headers()
                handler.wfile.write(sources[handler.path])
            def log_message(self, *args):
                pass
        server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        self.addCleanup(server.server_close)
        self.addCleanup(server.shutdown)
        base = f"http://127.0.0.1:{server.server_port}"
        for bundle in self.manifest["bundles"]:
            for row in bundle["assets"]:
                row["url"] = base + "/" + row["name"]
        self.manifest["external_files"] = [blob(external_content, path="downloads/media/original.mp4", profiles=["full"],
                                                     url=base + "/original.mp4", headers={"User-Agent": "Mozilla fixture", "Referer": "https://www.pexels.com/"})]
        result = restore.restore(self.root, self.load())
        self.assertEqual(result["restored"], 3)
        self.assertEqual(len(requests), 4)
        headers = next(headers for path, headers in requests if path == "/original.mp4")
        self.assertEqual(headers["User-Agent"], "Mozilla fixture")
        self.assertEqual(headers["Referer"], "https://www.pexels.com/")
        restore.restore(self.root, self.load())
        self.assertEqual(len(requests), 4)

    def test_cli_offline(self):
        self.load()
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = restore.main(["--project-root", str(self.root), "--manifest", str(self.base / "manifest.json"), "--assets-dir", str(self.offline), "--profile", "ppe"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["restored"], 1)


if __name__ == "__main__":
    unittest.main()
