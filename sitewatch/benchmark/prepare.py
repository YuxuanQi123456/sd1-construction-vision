"""Fetch the complete, pinned RF100 test split; never download train or validation."""
import argparse
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
import hashlib
import json
from pathlib import Path
import time
import urllib.parse
import urllib.request

REPO = "LibreYOLO/construction-safety-gsnvb"
SOURCE = "https://universe.roboflow.com/roboflow-100/construction-safety-gsnvb"


def request(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "ppe-benchmark/1.0"}), timeout=45) as response:
                return response.read(), response.headers
        except OSError:
            if attempt == 2:
                raise
            time.sleep(attempt + 1)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--revision", required=True, help="Full immutable HF commit SHA")
    parser.add_argument("--evidence", type=Path, required=True)
    args = parser.parse_args()
    if len(args.revision) != 40 or any(c not in "0123456789abcdef" for c in args.revision):
        parser.error("Use a full 40-character HF commit, not main")
    root = args.dataset_root.resolve()
    root.mkdir(parents=True, exist_ok=True)
    api = f"https://huggingface.co/api/datasets/{REPO}/tree/{args.revision}/test?recursive=true&limit=1000"
    body, headers = request(api)
    if 'rel="next"' in headers.get("Link", ""):
        raise RuntimeError("Unexpected paginated test listing; do not silently truncate")
    entries = [item for item in json.loads(body) if item["type"] == "file"]
    assert entries and all(e["path"].startswith(("test/images/", "test/labels/")) for e in entries)
    assert sum(e["size"] for e in entries) < 150 * 1024 * 1024
    images = [e for e in entries if e["path"].startswith("test/images/")]
    labels = [e for e in entries if e["path"].startswith("test/labels/")]
    assert len(images) == len(labels) == 90, (len(images), len(labels))
    assert {Path(e["path"]).stem for e in images} == {Path(e["path"]).stem for e in labels}

    def fetch(entry):
        relative = Path(entry["path"])
        assert not relative.is_absolute() and ".." not in relative.parts
        path = root / relative
        url = f"https://huggingface.co/datasets/{REPO}/resolve/{args.revision}/{urllib.parse.quote(relative.as_posix())}"
        data = path.read_bytes() if path.is_file() else request(url)[0]
        assert len(data) == entry["size"], str(relative)
        sha = hashlib.sha256(data).hexdigest()
        if entry.get("lfs"):
            assert sha == entry["lfs"]["oid"], str(relative)
        else:
            git_blob = hashlib.sha1(b"blob " + str(len(data)).encode() + b"\0" + data).hexdigest()
            assert git_blob == entry["oid"], str(relative)
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(data)
        return {"path": relative.as_posix(), "bytes": len(data), "sha256": sha,
                "source_git_oid": entry["oid"], "url": url}

    with ThreadPoolExecutor(max_workers=4) as pool:
        files = list(pool.map(fetch, sorted(entries, key=lambda e: e["path"])))
    for name in ["data.yaml", "README.md", "README.dataset.txt", "README.roboflow.txt"]:
        url = f"https://huggingface.co/datasets/{REPO}/resolve/{args.revision}/{name}"
        data = request(url)[0]
        (root / name).write_bytes(data)
        files.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest(), "url": url})
    record = {"schema": "rf100-test-lock-v1", "at": datetime.now(timezone.utc).isoformat(),
              "repository": f"https://huggingface.co/datasets/{REPO}", "revision": args.revision,
              "source": SOURCE, "license": "CC BY 4.0", "split": "test", "image_count": 90,
              "test_only": True, "files": files,
              "overlap_notice": "Candidate training data may contain this public dataset; no independent-deployment generalization claim."}
    encoded = json.dumps(record, ensure_ascii=False, indent=2) + "\n"
    (root / "dataset-lock.json").write_text(encoded)
    args.evidence.parent.mkdir(parents=True, exist_ok=True)
    args.evidence.write_text(encoded)
    print(json.dumps({"revision": args.revision, "files": len(files), "test_images": 90,
                      "bytes": sum(e["bytes"] for e in files), "passed": True}, ensure_ascii=False))


if __name__ == "__main__":
    main()
