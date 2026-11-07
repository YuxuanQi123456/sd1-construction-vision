"""Verify pristine source hashes and rebuild the adapted app from its patch."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil
import subprocess
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    base = Path(__file__).resolve().parent
    manifest = json.loads((base / "SOURCE.json").read_text())
    for name, expected in manifest["files"].items():
        assert hashlib.sha256((base / "upstream" / name).read_bytes()).hexdigest() == expected, name
    with tempfile.TemporaryDirectory(prefix="sitewatch-provenance-") as temporary:
        staged = Path(temporary)
        for name in ["app.py", "cv_pipeline", "utils"]:
            source = base / "upstream" / name
            target = staged / name
            if source.is_dir():
                shutil.copytree(source, target)
            else:
                shutil.copy2(source, target)
        result = subprocess.run(["patch", "--batch", "--forward", "-p1", "-i", str(base / manifest["patch"])],
                                cwd=staged, text=True, capture_output=True, check=True)
        checked = []
        for path in (base / "app").rglob("*.py"):
            relative = path.relative_to(base / "app")
            assert path.read_bytes() == (staged / relative).read_bytes(), str(relative)
            checked.append(str(relative))
    report = {"at": datetime.now(timezone.utc).isoformat(), "source_commit": manifest["commit"],
              "pristine_source_files_checked": len(manifest["files"]), "adapted_files_checked": checked,
              "patch_output": result.stdout, "exit_code": result.returncode, "passed": True}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
