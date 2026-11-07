"""Remove only enumerated, reproducible raw model weights and verified wheel parts."""
import argparse
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import shutil

ROOT = Path(__file__).resolve().parents[1]


def digest(path):
    with path.open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def size(path):
    if path.is_file():
        return path.stat().st_size
    return sum(p.stat().st_size for p in path.rglob("*") if p.is_file())


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Use a new evidence file; existing cleanup records are never overwritten")
    args.output.parent.mkdir(parents=True, exist_ok=True)
    lock = json.loads((ROOT / "vision/config/upstream-lock.json").read_text())["model"]
    candidates = [(ROOT / "downloads/qwen3-vl-2b/model.safetensors", lock["bytes"], lock["sha256"])]
    for item in json.loads((ROOT / "vision/config/qwen4b-files.json").read_text()):
        if item["filename"] in {"model-00001-of-00002.safetensors", "model-00002-of-00002.safetensors"}:
            candidates.append((ROOT / "downloads/qwen3-vl-4b-source" / item["filename"], item["size"], item["sha256"]))
    protected = {
        "downloads/qwen3-vl-4b-nf4/model.safetensors": "69d2f15d01e20744dcdb78ed044d06c11592264ae20337aacd0073b3590768d2",
        "downloads/qwen3-vl-2b-nf4/model.safetensors": "0642a26c955b463c5be84a80dad1e52d53b224b1bff086ccef9ac931fc79fff6",
        "downloads/sitewatch/repository/models/sitewatch_best.pt": "c2db52b9be8ccd5bcc09d6e0f9498a6e442e47eb6f6b62850db11530b77651ab",
    }
    # A stale checkpoint record must never let this utility remove a live raw model.
    state = ROOT / ".runtime/vision-process.json"
    if state.exists():
        active = Path(json.loads(state.read_text())["model"]).resolve()
        assert all(not path.is_relative_to(active) for path, _, _ in candidates), "Raw model still selected by the service"
    report = {"at": datetime.now(timezone.utc).isoformat(), "applied": args.apply,
              "disk_before": shutil.disk_usage(ROOT)._asdict(), "removed": [],
              "preserved": list(protected), "scope": "Only this project's download cache; source, evidence, environments and media remain."}
    try:
        for path, expected_size, known_sha in candidates:
            if not path.exists():
                continue
            assert path.is_file() and not path.is_symlink() and path.stat().st_size == expected_size, str(path)
            entry = {"path": str(path.relative_to(ROOT)), "bytes": expected_size,
                     "previously_verified_sha256": known_sha,
                     "reason": "Official raw weight already quantized; can be downloaded again from locked source."}
            if args.apply:
                path.unlink()
            report["removed"].append(entry)
        for item in json.loads((ROOT / "vision/config/wheels.json").read_text()):
            wheel = ROOT / "downloads/vision-wheels" / item["filename"]
            parts = wheel.with_name(wheel.name + ".parts")
            if not parts.is_dir():
                continue
            assert not parts.is_symlink() and wheel.is_file() and digest(wheel) == item["sha256"], str(wheel)
            entry = {"path": str(parts.relative_to(ROOT)), "bytes": size(parts),
                     "reason": "Complete wheel matches pinned official SHA256; range-download pieces are redundant."}
            if args.apply:
                shutil.rmtree(parts)
            report["removed"].append(entry)
        report["protected_sha256_checks"] = []
        for name, expected in protected.items():
            actual = digest(ROOT / name)
            assert actual == expected, f"Protected model changed: {name}"
            report["protected_sha256_checks"].append({"path": name, "sha256": actual, "passed": True})
        report["passed"] = True
    except Exception as exc:
        report["passed"] = False
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        report["disk_after"] = shutil.disk_usage(ROOT)._asdict()
        report["removed_bytes"] = sum(v["bytes"] for v in report["removed"]) if args.apply else 0
        report["observed_free_space_change"] = report["disk_after"]["free"] - report["disk_before"]["free"]
        args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
        print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
