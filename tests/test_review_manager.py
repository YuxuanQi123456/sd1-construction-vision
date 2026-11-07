"""Private configuration initialization and backend startup routing."""
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

    def route(self, provider, ready=False):
        modules = {
            "review_api": types.SimpleNamespace(load_review_config=lambda root: {"provider": provider}),
            "region_review": types.SimpleNamespace(backend_status=lambda root: {
                "provider": provider, "ready": ready, "model": "gpt-6.1-sol", "reasoning_effort": "max"})}
        with patch.dict(sys.modules, modules), patch.object(manager.subprocess, "call", return_value=0) as child:
            with patch("builtins.print"):
                result = manager.main(["start", "--project-root", str(self.root), "--wait"])
        return result, child

    def test_api_without_key_still_allows_ppe_start_without_local_qwen(self):
        result, child = self.route("openai", ready=False)
        self.assertEqual(result, 0)
        child.assert_not_called()

    def test_only_explicit_qwen_option_starts_original_local_manager(self):
        result, child = self.route("qwen_local")
        self.assertEqual(result, 0)
        self.assertEqual(child.call_args.args[0], [sys.executable,
                         str(self.root / "vision/scripts/manage.py"), "start", "--wait"])


if __name__ == "__main__":
    unittest.main()
