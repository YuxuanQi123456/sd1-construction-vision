#!/usr/bin/env python3
"""Create a repository-owned Linux/Python 3.12 runtime for the existing launchers."""
from __future__ import annotations

import argparse
import fcntl
import hashlib
import json
import os
from pathlib import Path
import platform
import subprocess
import sys

SCHEMA = "sd1-portable-env-v1"
ENV_PATH = ".runtime/portable-env"
MARKER = ".sd1-bootstrap.json"
LINKS = {".runtime/sitewatch-env": "portable-env"}
TORCH = {"ppe": "cpu"}
SETUPTOOLS_PTH = "import os; var = 'SETUPTOOLS_USE_DISTUTILS'; enabled = os.environ.get(var, 'local') == 'local'; enabled and __import__('_distutils_hack').add_shim();"


class BootstrapError(ValueError):
    pass


def local_path(root, relative):
    current = root
    for part in Path(relative).parts:
        current /= part
        if current.is_symlink():
            raise BootstrapError(f"Symlink refused in managed path: {current}")
    return current


def clean_environment(root=None):
    env = dict(os.environ)
    for key in ("PYTHONPATH", "PYTHONHOME", "PYTHONUSERBASE", "VIRTUAL_ENV", "__PYVENV_LAUNCHER__"):
        env.pop(key, None)
    env.update(PYTHONNOUSERSITE="1", PIP_CONFIG_FILE=os.devnull,
               PIP_DISABLE_PIP_VERSION_CHECK="1")
    if root is not None:
        runtime = root / ENV_PATH / "runtime"
        env.update(YOLO_CONFIG_DIR=str(runtime / "ultralytics"),
                   MPLCONFIGDIR=str(runtime / "matplotlib"), XDG_CACHE_HOME=str(runtime / "cache"),
                   TORCH_HOME=str(runtime / "torch"))
    return env


def run(command, root):
    subprocess.run([str(v) for v in command], cwd=root, env=clean_environment(root), check=True)


def read_state(root):
    env = local_path(root, ENV_PATH)
    if not env.exists():
        return None
    marker = local_path(root, ENV_PATH + "/" + MARKER)
    if not env.is_dir() or not marker.is_file():
        raise BootstrapError(f"Existing environment is unmanaged; refusing modification: {env}")
    state = json.loads(marker.read_text())
    if state.get("schema") != SCHEMA:
        raise BootstrapError("Existing environment marker is not recognized")
    if state.get("profile") == "full":
        raise BootstrapError("Existing full runtime is no longer supported; preserve it and explicitly move it before creating a CPU PPE environment")
    if state.get("profile") not in TORCH:
        raise BootstrapError("Existing environment marker is not recognized")
    # An owned marker never authorizes external package trees or a different Python binary.
    cfg = env / "pyvenv.cfg"
    if cfg.is_symlink():
        raise BootstrapError("Symlink pyvenv.cfg refused")
    if cfg.exists():
        fields = {key.strip(): value.strip() for key, value in
                  (line.lower().split("=", 1) for line in cfg.read_text().splitlines() if "=" in line)}
        if fields.get("include-system-site-packages") != "false":
            raise BootstrapError("Managed venv must disable system site packages")
    base_python = Path(sys._base_executable).resolve()
    for path in env.rglob("*"):
        if not path.is_symlink():
            continue
        immediate = Path(os.readlink(path))
        if not immediate.is_absolute():
            immediate = path.parent / immediate
        if immediate.absolute().is_relative_to(env) and path.resolve().is_relative_to(env):
            continue
        if path.parent == env / "bin" and path.name in ("python", "python3", "python3.12"):
            # Allow system interpreter aliases across directories; only the final
            # OS binary matters. pyvenv.cfg still makes this repository the prefix.
            if path.resolve() == base_python:
                continue
        raise BootstrapError(f"External symlink refused in managed environment: {path}")
    for name in ("bin", "lib", "runtime", "torch-install-report.json", "packages-install-report.json"):
        local_path(root, ENV_PATH + "/" + name)
    for pth in env.glob("lib/python*/site-packages/*.pth"):
        for line in pth.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#"):
                continue
            if line.startswith(("import ", "import\t")):
                if pth.name != "distutils-precedence.pth" or line != SETUPTOOLS_PTH:
                    raise BootstrapError(f"Unrecognized executable .pth hook refused: {pth}")
            elif not (pth.parent / line).resolve().is_relative_to(env):
                raise BootstrapError(f"External package path refused in {pth}")
    return state


def check_links(root, profile):
    for name, target in LINKS.items():
        path = root / name
        local_path(root, str(Path(name).parent))
        if path.is_symlink():
            if os.readlink(path) != target:
                raise BootstrapError(f"Existing launcher link is unmanaged: {path}")
        elif path.exists():
            raise BootstrapError(f"Existing launcher environment is unmanaged; move it explicitly before retrying: {path}")


def pins(root, profile):
    result = {"torch": "2.8.0+" + TORCH[profile], "torchvision": "0.23.0+" + TORCH[profile]}
    path = local_path(root, "config/bootstrap-ppe.txt")
    for line in path.read_text().splitlines():
        line = line.split("#", 1)[0].strip()
        if not line:
            continue
        package, version = line.split("==")
        result[package] = version
    return result


def verification_code(env, profile, expected):
    # Runs in -I mode: no user site, PYTHONPATH, or current-directory imports.
    code = f"""
import importlib.metadata as metadata
import json
from pathlib import Path
import site
import sys
root = Path({str(env)!r}).resolve()
assert Path(sys.prefix).resolve() == root, (sys.prefix, root)
assert not site.ENABLE_USER_SITE, 'User site must be disabled'
for entry in sys.path:
    path = Path(entry).resolve()
    if 'site-packages' in path.parts or 'dist-packages' in path.parts:
        assert path.is_relative_to(root), 'External package path: ' + str(path)
expected = {expected!r}
for package, version in expected.items():
    assert metadata.version(package) == version, (package, metadata.version(package), version)
import torch
import torchvision
import streamlit
import ultralytics
import cv2
for module in (torch, torchvision, streamlit, ultralytics, cv2):
    assert Path(module.__file__).resolve().is_relative_to(root), module.__file__
assert (torch.ones(2) + 1).tolist() == [2, 2]
boxes = torch.tensor([[0., 0., 10., 10.], [0., 0., 10., 10.]])
assert torchvision.ops.nms(boxes, torch.tensor([0.9, 0.8]), 0.5).tolist() == [0]
result = {{'profile': {profile!r}, 'cpu_tensor_and_nms': 'passed', 'versions': expected}}
"""
    return code + "\nprint(json.dumps(result, sort_keys=True))\n"


def make_plan(root, profile, no_cache_dir=False):
    if profile != "ppe":
        raise BootstrapError("Only the CPU ppe profile is supported; full runtime support has been removed")
    state = read_state(root)
    if not no_cache_dir:
        local_path(root, ".runtime/pip-cache")
    effective = profile
    check_links(root, effective)
    expected = pins(root, effective)
    fingerprint = hashlib.sha256(json.dumps(expected, sort_keys=True).encode()).hexdigest()
    env = root / ENV_PATH
    python = env / "bin/python"
    index = "https://download.pytorch.org/whl/" + TORCH[effective]
    pip_flags = ["--only-binary=:all:"] + (["--no-cache-dir"] if no_cache_dir else
                 ["--cache-dir", str(root / ".runtime/pip-cache")])
    commands = [[str(Path(sys._base_executable)), "-I", "-m", "venv", str(env)],
                [str(python), "-I", "-m", "pip", "--isolated", "install", "--index-url", index,
                 "--report", str(env / "torch-install-report.json"),
                 "torch==" + expected["torch"], "torchvision==" + expected["torchvision"], *pip_flags],
                [str(python), "-I", "-m", "pip", "--isolated", "install", "--index-url", "https://pypi.org/simple",
                 "--report", str(env / "packages-install-report.json"),
                 "-r", str(root / "config/bootstrap-ppe.txt"), *pip_flags]]
    verify = [[str(python), "-I", "-m", "pip", "--isolated", "check"],
              [str(python), "-I", "-c", verification_code(env, effective, expected)]]
    ready = bool(state and state.get("status") == "ready" and state.get("fingerprint") == fingerprint)
    return {"schema": SCHEMA, "requested_profile": profile, "profile": effective,
            "environment": str(env), "managed_links": dict(LINKS),
            "platform": "Linux x86_64, Python 3.12, glibc >= 2.28",
            "gpu_requirement": None,
            "packages": expected, "fingerprint": fingerprint,
            "install_commands": [] if ready else commands, "verification_commands": verify,
            "existing_state": state.get("status") if state else None,
            "pip_cache": None if no_cache_dir else str(root / ".runtime/pip-cache"),
            "note": "Direct versions are pinned; pip reports preserve resolved transitive versions. No model is loaded by bootstrap."}


def check_platform(profile, root):
    if sys.version_info[:2] != (3, 12) or platform.system() != "Linux" or platform.machine() != "x86_64":
        raise BootstrapError("This portable baseline requires Python 3.12 on Linux x86_64 (WSL2 supported)")
    libc, version = platform.libc_ver()
    if libc != "glibc" or tuple(int(v) for v in version.split(".")[:2]) < (2, 28):
        raise BootstrapError("glibc >= 2.28 is required by the pinned Linux wheels")


def write_state(root, state):
    env = local_path(root, ENV_PATH)
    marker = local_path(root, ENV_PATH + "/" + MARKER)
    temporary = local_path(root, ENV_PATH + "/" + MARKER + ".tmp")
    env.mkdir(parents=True, exist_ok=True)
    temporary.write_text(json.dumps(state, indent=2) + "\n")
    temporary.replace(marker)


def bootstrap(root, profile, no_cache_dir=False):
    plan = make_plan(root, profile, no_cache_dir)
    check_platform(plan["profile"], root)
    state = {k: plan[k] for k in ("schema", "profile", "fingerprint")}
    try:
        if plan["install_commands"]:
            write_state(root, {**state, "status": "installing"})
            for name in ("ultralytics", "matplotlib", "cache", "torch"):
                local_path(root, ENV_PATH + "/runtime/" + name).mkdir(parents=True, exist_ok=True)
            for command in plan["install_commands"]:
                read_state(root)
                run(command, root)
        for command in plan["verification_commands"]:
            read_state(root)
            run(command, root)
        # Link only after all dependency and operator checks; failed installs remain resumable.
        check_links(root, plan["profile"])
        for name, target in plan["managed_links"].items():
            link = root / name
            link.parent.mkdir(parents=True, exist_ok=True)
            if not link.is_symlink():
                link.symlink_to(target, target_is_directory=True)
        # manage_ppe.py opens its runtime log before SiteWatch creates runtime folders.
        (root / ENV_PATH / "runtime").mkdir(exist_ok=True)
        write_state(root, {**state, "status": "ready"})
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        write_state(root, {**state, "status": "failed", "error": str(exc)[:500]})
        raise
    return {"profile": plan["profile"], "environment": plan["environment"], "status": "ready",
            "validation": "Installed packages, isolation and CPU operators checked"}


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("ppe",), default="ppe")
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--plan", action="store_true", help="Print commands/requirements without installing or creating paths")
    parser.add_argument("--no-cache-dir", action="store_true", help="Disable persistent pip wheel cache to reduce disk usage")
    args = parser.parse_args(argv)
    try:
        root = args.project_root.resolve()
        if not root.is_dir():
            raise BootstrapError("Project root must already be a directory")
        if args.plan:
            result = make_plan(root, args.profile, args.no_cache_dir)
        else:
            # A process lock protects ownership markers and partial-install retries.
            runtime = local_path(root, ".runtime")
            runtime.mkdir(exist_ok=True)
            lock_path = local_path(root, ".runtime/bootstrap.lock")
            with lock_path.open("a") as lock:
                fcntl.flock(lock, fcntl.LOCK_EX)
                result = bootstrap(root, args.profile, args.no_cache_dir)
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    except (OSError, ValueError, KeyError, subprocess.CalledProcessError) as exc:
        print(f"Runtime bootstrap failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
