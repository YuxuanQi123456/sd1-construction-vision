"""Bootstrap planning and lightweight venv lifecycle fixtures, without Torch installs."""
import importlib.util
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

REPO = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("bootstrap_runtime", REPO / "scripts/bootstrap_runtime.py")
bootstrap = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(bootstrap)


class BootstrapRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "new-project"
        (self.root / "config").mkdir(parents=True)
        (self.root / "vision").mkdir()
        for profile in ("ppe", "full"):
            shutil.copyfile(REPO / f"config/bootstrap-{profile}.txt", self.root / f"config/bootstrap-{profile}.txt")

    def test_plan_has_only_repo_owned_environment_and_exact_manager_paths(self):
        for profile in ("ppe", "full"):
            plan = bootstrap.make_plan(self.root, profile)
            self.assertIn(".runtime/sitewatch-env", plan["managed_links"])
            self.assertEqual("vision/.venv" in plan["managed_links"], profile == "full")
            encoded = json.dumps(plan)
            self.assertNotIn("/home/meg", encoded)
            self.assertNotIn("existing_runtime_readonly", encoded)
            self.assertIn(f"https://download.pytorch.org/whl/{bootstrap.TORCH[profile]}", encoded)
            self.assertEqual(plan["packages"]["transformers"], "4.57.6") if profile == "full" else None
        self.assertFalse((self.root / ".runtime").exists())

    def test_unmanaged_existing_environment_is_never_overwritten(self):
        for relative in (bootstrap.ENV_PATH, ".runtime/sitewatch-env", "vision/.venv"):
            with self.subTest(path=relative):
                path = self.root / relative
                path.mkdir(parents=True)
                (path / "precious").write_text("keep")
                with self.assertRaisesRegex(bootstrap.BootstrapError, "unmanaged"):
                    bootstrap.make_plan(self.root, "full")
                self.assertEqual((path / "precious").read_text(), "keep")
                shutil.rmtree(path)

    def test_pip_cache_can_be_disabled_for_small_disks(self):
        plan = bootstrap.make_plan(self.root, "ppe", no_cache_dir=True)
        self.assertIsNone(plan["pip_cache"])
        for command in plan["install_commands"][1:]:
            self.assertIn("--no-cache-dir", command)
            self.assertNotIn("--cache-dir", command)

    def test_external_link_is_refused(self):
        (self.root / "vision/.venv").symlink_to("/some/other/venv")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "unmanaged"):
            bootstrap.make_plan(self.root, "full")

    def test_runtime_parent_symlink_is_refused(self):
        external = Path(self.temporary.name) / "external"
        external.mkdir()
        (self.root / ".runtime").symlink_to(external, target_is_directory=True)
        with self.assertRaisesRegex(bootstrap.BootstrapError, "Symlink"):
            bootstrap.make_plan(self.root, "ppe")
        self.assertEqual(list(external.iterdir()), [])

    def test_owned_marker_does_not_authorize_external_site_or_report_links(self):
        env = self.root / bootstrap.ENV_PATH
        for relative in ("lib/python3.12/site-packages", "torch-install-report.json", "runtime"):
            with self.subTest(path=relative):
                bootstrap.write_state(self.root, {"schema": bootstrap.SCHEMA, "profile": "ppe", "status": "failed"})
                path = env / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.symlink_to("/external/other-venv/site-packages")
                with self.assertRaisesRegex(bootstrap.BootstrapError, "symlink"):
                    bootstrap.make_plan(self.root, "ppe")
                path.unlink()

    def test_external_pth_refused_before_any_install(self):
        bootstrap.write_state(self.root, {"schema": bootstrap.SCHEMA, "profile": "ppe", "status": "failed"})
        site = self.root / bootstrap.ENV_PATH / "lib/python3.12/site-packages"
        site.mkdir(parents=True)
        (site / "external.pth").write_text("/outside/other-env/site-packages\n")
        with mock.patch.object(bootstrap, "run") as run:
            with self.assertRaisesRegex(bootstrap.BootstrapError, "External package path"):
                bootstrap.bootstrap(self.root, "ppe")
        run.assert_not_called()

    def test_executable_external_pth_refused_before_any_install(self):
        bootstrap.write_state(self.root, {"schema": bootstrap.SCHEMA, "profile": "ppe", "status": "failed"})
        site = self.root / bootstrap.ENV_PATH / "lib/python3.12/site-packages"
        site.mkdir(parents=True)
        (site / "external.pth").write_text("import sys; sys.path.append('/outside/packages')\n")
        with mock.patch.object(bootstrap, "run") as run:
            with self.assertRaisesRegex(bootstrap.BootstrapError, "executable .pth"):
                bootstrap.bootstrap(self.root, "ppe")
        run.assert_not_called()

    def fixture_runner(self, commands):
        """Create a real tiny venv; model dependencies and operator checks are mocked."""
        def run(command, root):
            commands.append(command)
            if command[1:4] == ["-I", "-m", "venv"]:
                subprocess.run(command[:4] + ["--without-pip", command[-1]], check=True, env=bootstrap.clean_environment())
            if command[1:3] == ["-I", "-c"]:
                code = "import site,sys; from pathlib import Path; assert not site.ENABLE_USER_SITE; assert Path(sys.prefix).resolve()==Path(" + repr(str(root / bootstrap.ENV_PATH)) + ").resolve(); print('lightweight venv isolation fixture passed')"
                subprocess.run([command[0], "-I", "-c", code], check=True, env=bootstrap.clean_environment())
        return run

    def test_lightweight_venv_links_idempotence_and_upgrade(self):
        commands = []
        with mock.patch.object(bootstrap, "run", side_effect=self.fixture_runner(commands)), mock.patch.object(bootstrap, "check_platform"):
            bootstrap.bootstrap(self.root, "ppe")
            self.assertEqual(len(commands), 5)
            python = self.root / ".runtime/sitewatch-env/bin/python"
            subprocess.run([str(python), "-I", "-c", "import sys; assert sys.prefix.endswith('/.runtime/sitewatch-env')"], check=True)
            self.assertTrue((self.root / ".runtime/sitewatch-env/runtime").is_dir())
            bootstrap.bootstrap(self.root, "ppe")
            self.assertEqual(len(commands), 7)
            bootstrap.bootstrap(self.root, "full")
            self.assertEqual(len(commands), 12)
            self.assertTrue((self.root / "vision/.venv/bin/python").is_file())
            self.assertEqual(os.readlink(self.root / "vision/.venv"), "../.runtime/portable-env")
            plan = bootstrap.make_plan(self.root, "ppe")
            self.assertEqual(plan["profile"], "full")
            self.assertEqual(plan["install_commands"], [])

    def test_failed_install_can_retry_without_adopting_an_unmanaged_env(self):
        commands = []
        runner = self.fixture_runner(commands)
        def failing(command, root):
            runner(command, root)
            if "install" in command:
                raise subprocess.CalledProcessError(1, command)
        with mock.patch.object(bootstrap, "run", side_effect=failing), mock.patch.object(bootstrap, "check_platform"):
            with self.assertRaises(subprocess.CalledProcessError):
                bootstrap.bootstrap(self.root, "ppe")
        self.assertEqual(bootstrap.read_state(self.root)["status"], "failed")
        self.assertFalse((self.root / ".runtime/sitewatch-env").exists())
        with mock.patch.object(bootstrap, "run", side_effect=runner), mock.patch.object(bootstrap, "check_platform"):
            bootstrap.bootstrap(self.root, "ppe")
        self.assertEqual(bootstrap.read_state(self.root)["status"], "ready")

    def test_missing_gpu_fails_before_creating_environment(self):
        with mock.patch.object(bootstrap.subprocess, "run", side_effect=FileNotFoundError("fixture no NVIDIA")):
            with self.assertRaisesRegex(bootstrap.BootstrapError, "nvidia-smi"):
                bootstrap.bootstrap(self.root, "full")
        self.assertFalse((self.root / bootstrap.ENV_PATH).exists())

    def test_system_python_alias_in_another_directory_remains_idempotent(self):
        alias = Path(self.temporary.name) / "alternate-bin/python3.12"
        alias.parent.mkdir()
        alias.symlink_to(Path(sys._base_executable).resolve())
        commands = []
        with mock.patch.object(sys, "_base_executable", str(alias)), mock.patch.object(bootstrap, "run", side_effect=self.fixture_runner(commands)), mock.patch.object(bootstrap, "check_platform"):
            bootstrap.bootstrap(self.root, "ppe")
            bootstrap.bootstrap(self.root, "ppe")
        self.assertEqual(len(commands), 7)

    def test_python_environment_injection_is_removed(self):
        with mock.patch.dict(os.environ, {"PYTHONPATH": "/external/packages", "PYTHONHOME": "/external/python", "VIRTUAL_ENV": "/external/env"}):
            clean = bootstrap.clean_environment()
        for key in ("PYTHONPATH", "PYTHONHOME", "VIRTUAL_ENV"):
            self.assertNotIn(key, clean)
        self.assertEqual(clean["PYTHONNOUSERSITE"], "1")


if __name__ == "__main__":
    unittest.main()
