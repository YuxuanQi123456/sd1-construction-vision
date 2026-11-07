"""Restore SiteWatch through the repository-owned CPU environment and PPE assets."""
import argparse
from pathlib import Path
import subprocess
import sys


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--assets-dir", type=Path, help="Use existing offline asset inputs")
    parser.add_argument("--plan", action="store_true", help="Show restore plans without installing or downloading")
    parser.add_argument("--no-cache-dir", action="store_true", help="Disable the environment's pip cache")
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    scripts = Path(__file__).resolve().parents[1] / "scripts"
    bootstrap = [sys.executable, str(scripts / "bootstrap_runtime.py"),
                 "--project-root", str(root), "--profile", "ppe"]
    assets = [sys.executable, str(scripts / "restore_runtime_assets.py"),
              "--project-root", str(root), "--profile", "ppe"]
    if args.plan:
        bootstrap.append("--plan")
        assets.append("--plan")
    if args.no_cache_dir:
        bootstrap.append("--no-cache-dir")
    if args.assets_dir:
        assets += ["--assets-dir", str(args.assets_dir.absolute())]
    for command in (bootstrap, assets):
        subprocess.run(command, cwd=root, check=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
