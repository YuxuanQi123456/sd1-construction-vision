"""Bootstrap planning and lightweight venv lifecycle fixtures, without Torch installs."""
import importlib.util
import contextlib
import io
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
PREPARE_SPEC = importlib.util.spec_from_file_location("prepare_sitewatch", REPO / "sitewatch/prepare.py")
prepare = importlib.util.module_from_spec(PREPARE_SPEC)
PREPARE_SPEC.loader.exec_module(prepare)


class BootstrapRuntimeTest(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.addCleanup(self.temporary.cleanup)
        self.root = Path(self.temporary.name) / "new-project"
        (self.root / "config").mkdir(parents=True)
        shutil.copyfile(REPO / "config/bootstrap-ppe.txt", self.root / "config/bootstrap-ppe.txt")

    def test_plan_has_only_repo_owned_environment_and_exact_manager_paths(self):
        plan = bootstrap.make_plan(self.root, "ppe")
        self.assertEqual(plan["managed_links"], {".runtime/sitewatch-env": "portable-env"})
        encoded = json.dumps(plan)
        self.assertNotIn("/home/meg", encoded)
        self.assertNotIn("existing_runtime_readonly", encoded)
        self.assertIn("https://download.pytorch.org/whl/cpu", encoded)
        self.assertNotIn("transformers", plan["packages"])
        self.assertIsNone(plan["gpu_requirement"])
        self.assertFalse((self.root / ".runtime").exists())

    def test_cli_defaults_to_cpu_ppe_without_creating_paths_for_plan(self):
        with contextlib.redirect_stdout(io.StringIO()) as output:
            code = bootstrap.main(["--project-root", str(self.root), "--plan"])
        self.assertEqual(code, 0)
        self.assertEqual(json.loads(output.getvalue())["profile"], "ppe")
        self.assertFalse((self.root / ".runtime").exists())

    def test_legacy_prepare_forwards_only_repo_owned_cpu_and_ppe_restore(self):
        offline = Path(self.temporary.name) / "offline"
        offline.mkdir()
        with mock.patch.object(prepare.subprocess, "run") as run:
            code = prepare.main(["--project-root", str(self.root), "--assets-dir", str(offline),
                                 "--plan", "--no-cache-dir"])
        self.assertEqual(code, 0)
        self.assertEqual(run.call_count, 2)
        bootstrap_cmd, assets_cmd = [call.args[0] for call in run.call_args_list]
        for call in run.call_args_list:
            self.assertEqual(call.kwargs, {"cwd": self.root, "check": True})
            command = call.args[0]
            self.assertIn("--plan", command)
            self.assertEqual(command[command.index("--profile") + 1], "ppe")
            self.assertEqual(command[command.index("--project-root") + 1], str(self.root))
        self.assertEqual(Path(bootstrap_cmd[1]), REPO / "scripts/bootstrap_runtime.py")
        self.assertEqual(Path(assets_cmd[1]), REPO / "scripts/restore_runtime_assets.py")
        self.assertIn("--no-cache-dir", bootstrap_cmd)
        self.assertEqual(assets_cmd[assets_cmd.index("--assets-dir") + 1], str(offline))
        self.assertFalse((self.root / ".runtime").exists())

    def test_prepare_keeps_offline_symlink_visible_to_restore_validation(self):
        offline = Path(self.temporary.name) / "offline"
        offline.mkdir()
        link = Path(self.temporary.name) / "offline-link"
        link.symlink_to(offline, target_is_directory=True)
        with mock.patch.object(prepare.subprocess, "run") as run:
            prepare.main(["--project-root", str(self.root), "--assets-dir", str(link), "--plan"])
        command = run.call_args.args[0]
        self.assertEqual(command[command.index("--assets-dir") + 1], str(link))

    def test_unmanaged_existing_environment_is_never_overwritten(self):
        for relative in (bootstrap.ENV_PATH, ".runtime/sitewatch-env"):
            with self.subTest(path=relative):
                path = self.root / relative
                path.mkdir(parents=True)
                (path / "precious").write_text("keep")
                with self.assertRaisesRegex(bootstrap.BootstrapError, "unmanaged"):
                    bootstrap.make_plan(self.root, "ppe")
                self.assertEqual((path / "precious").read_text(), "keep")
                shutil.rmtree(path)

    def test_pip_cache_can_be_disabled_for_small_disks(self):
        plan = bootstrap.make_plan(self.root, "ppe", no_cache_dir=True)
        self.assertIsNone(plan["pip_cache"])
        for command in plan["install_commands"][1:]:
            self.assertIn("--no-cache-dir", command)
            self.assertNotIn("--cache-dir", command)

    def test_external_link_is_refused(self):
        (self.root / ".runtime").mkdir()
        (self.root / ".runtime/sitewatch-env").symlink_to("/some/other/venv")
        with self.assertRaisesRegex(bootstrap.BootstrapError, "unmanaged"):
            bootstrap.make_plan(self.root, "ppe")

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

    def test_lightweight_venv_links_and_idempotence(self):
        commands = []
        with mock.patch.object(bootstrap, "run", side_effect=self.fixture_runner(commands)), mock.patch.object(bootstrap, "check_platform"):
            bootstrap.bootstrap(self.root, "ppe")
            self.assertEqual(len(commands), 5)
            python = self.root / ".runtime/sitewatch-env/bin/python"
            subprocess.run([str(python), "-I", "-c", "import sys; assert sys.prefix.endswith('/.runtime/sitewatch-env')"], check=True)
            self.assertTrue((self.root / ".runtime/sitewatch-env/runtime").is_dir())
            bootstrap.bootstrap(self.root, "ppe")
            self.assertEqual(len(commands), 7)
            plan = bootstrap.make_plan(self.root, "ppe")
            self.assertEqual(plan["profile"], "ppe")
            self.assertEqual(plan["install_commands"], [])
            self.assertFalse((self.root / "vision").exists())

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

    def test_removed_full_profile_fails_before_creating_environment(self):
        with mock.patch.object(bootstrap, "run") as run:
            with self.assertRaisesRegex(bootstrap.BootstrapError, "Only the CPU ppe"):
                bootstrap.bootstrap(self.root, "full")
        run.assert_not_called()
        self.assertFalse((self.root / bootstrap.ENV_PATH).exists())

    def test_old_full_environment_is_preserved_and_not_downgraded(self):
        for status in ("ready", "failed", "installing"):
            with self.subTest(status=status):
                bootstrap.write_state(self.root, {"schema": bootstrap.SCHEMA, "profile": "full", "status": status})
                marker = self.root / bootstrap.ENV_PATH / bootstrap.MARKER
                before = marker.read_bytes()
                valuable = marker.parent / "keep-package"
                valuable.write_text("existing full runtime")
                with mock.patch.object(bootstrap, "run") as run:
                    with self.assertRaisesRegex(bootstrap.BootstrapError, "full runtime is no longer supported"):
                        bootstrap.bootstrap(self.root, "ppe")
                run.assert_not_called()
                self.assertEqual(marker.read_bytes(), before)
                self.assertEqual(valuable.read_text(), "existing full runtime")

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
