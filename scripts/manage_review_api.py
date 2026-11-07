"""Initialize private GPT API settings and report their configuration status."""
from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
LOCAL = "config/review-api.local.json"


def initialize(root):
    destination = root / LOCAL
    if destination.parent.is_symlink() or not destination.parent.resolve().is_relative_to(root.resolve()):
        raise ValueError("Private configuration directory must stay inside this project")
    if destination.is_symlink():
        raise ValueError("Private API configuration must be a regular local file")
    if destination.exists():
        return False
    template = root / "config/review-api.example.json"
    content = template.read_bytes()
    if json.loads(content).get("api_key"):
        raise ValueError("Example configuration must contain an empty API key")
    destination.parent.mkdir(parents=True, exist_ok=True)
    try:
        fd = os.open(destination, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    except FileExistsError:
        return False
    with os.fdopen(fd, "wb") as output:
        output.write(content)
    return True


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("init", "status", "start"))
    parser.add_argument("--project-root", type=Path, default=ROOT)
    parser.add_argument("--wait", action="store_true", help="Accepted for launcher compatibility; API configuration has no startup wait")
    args = parser.parse_args(argv)
    root = args.project_root.resolve()
    if args.action in ("init", "start"):
        initialize(root)
    if args.action == "init":
        print(json.dumps({"config_path": str(root / LOCAL), "existing_values_preserved": True}, ensure_ascii=False))
        return 0
    sys.path.insert(0, str(ROOT / "sitewatch/app"))
    from region_review import backend_status
    # Reading status never contacts the remote API or spends model credits.
    status = backend_status(root)
    print(json.dumps(status, ensure_ascii=False, indent=2))
    # A missing API key does not prevent the independent PPE page from starting.
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError):
        print("Review configuration is invalid; check config/review-api.local.json. Existing settings were preserved.", file=sys.stderr)
        raise SystemExit(1)
