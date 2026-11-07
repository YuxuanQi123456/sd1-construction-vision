"""Private API configuration initialization and status-only startup."""
import importlib.util
import json
from pathlib import Path
import sys
import tempfile
import types
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("review_manager", ROOT / "scripts/manage_review_api.py")
manager = importlib.util.module_from_spec(spec)
spec.loader.exec_module(manager)


class ReviewManagerTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        (self.root / "config").mkdir()
        (self.root / "config/review-api.example.json").write_text(json.dumps({
            "provider": "openai", "model": "gpt-6.1-sol", "reasoning_effort": "max", "api_key": ""}))

    def test_initialization_creates_blank_key_and_preserves_existing_values(self):
        self.assertTrue(manager.initialize(self.root))
        local = self.root / manager.LOCAL
        first = json.loads(local.read_text())
        self.assertEqual(first["api_key"], "")
        first["api_key"] = "fake-test-key"
        local.write_text(json.dumps(first))
        before = local.read_bytes()
        self.assertFalse(manager.initialize(self.root))
        self.assertEqual(local.read_bytes(), before)

    def test_symlink_configuration_is_refused(self):
        target = self.root / "outside.json"
        target.write_text("{}")
        (self.root / manager.LOCAL).symlink_to(target)
        with self.assertRaises(ValueError):
            manager.initialize(self.root)
        self.assertEqual(target.read_text(), "{}")

    def test_nonempty_example_key_is_not_copied(self):
        (self.root / "config/review-api.example.json").write_text('{"api_key":"fake-example-secret"}')
        with self.assertRaises(ValueError):
            manager.initialize(self.root)
        self.assertFalse((self.root / manager.LOCAL).exists())

    def test_symlink_parent_is_refused_before_writing_outside_project(self):
        (self.root / "config").rename(self.root / "original-config")
        with tempfile.TemporaryDirectory() as outside:
            (self.root / "config").symlink_to(outside, target_is_directory=True)
            with self.assertRaises(ValueError):
                manager.initialize(self.root)
            self.assertEqual(list(Path(outside).iterdir()), [])

    def route(self, ready=False, error=None):
        modules = {
            "region_review": types.SimpleNamespace(backend_status=lambda root: {
                "provider": "openai", "ready": ready, "model": "gpt-6.1-sol", "reasoning_effort": "max",
                **({"error": error} if error else {})})}
        with patch.dict(sys.modules, modules), patch("subprocess.Popen", side_effect=AssertionError("No model process may start")):
            with patch("builtins.print") as printed:
                result = manager.main(["start", "--project-root", str(self.root), "--wait"])
        return result, json.loads(printed.call_args.args[0])

    def test_api_without_key_still_allows_ppe_start(self):
        result, status = self.route(ready=False)
        self.assertEqual(result, 0)
        self.assertFalse(status["ready"])

    def test_configured_api_only_reports_status_without_starting_process(self):
        result, status = self.route(ready=True)
        self.assertEqual(result, 0)
        self.assertTrue(status["ready"])

    def test_invalid_settings_are_reported_without_rewriting_them(self):
        local = self.root / manager.LOCAL
        local.write_text('{"provider":"qwen_local","api_key":"fake-test-key"}')
        before = local.read_bytes()
        result, status = self.route(error="Only openai is supported")
        self.assertEqual(result, 0)
        self.assertFalse(status["ready"])
        self.assertIn("openai", status["error"])
        self.assertEqual(local.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
