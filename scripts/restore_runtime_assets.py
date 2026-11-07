#!/usr/bin/env python3
"""Restore the pinned runtime assets with Python's standard library only."""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import stat
import sys
import tempfile
from urllib.parse import urlparse
from urllib.request import Request, urlopen
import zipfile

SCHEMA = "sd1-runtime-assets-v1"
BLOCK = 1024 * 1024


class AssetError(ValueError):
    """A manifest, input, or destination failed validation."""


def relative_path(value):
    if not isinstance(value, str) or not value or "\\" in value or ":" in value:
        raise AssetError(f"Unsafe relative path: {value!r}")
    path = PurePosixPath(value)
    if path.is_absolute() or any(p in ("", ".", "..") for p in value.split("/")):
        raise AssetError(f"Unsafe relative path: {value!r}")
    return path


def safe_path(root, relative):
    """Reject every symlink component, including dangling symlinks."""
    relative = relative_path(str(relative))
    current = root
    for part in relative.parts:
        current = current / part
        if current.is_symlink():
            raise AssetError(f"Symlink path refused: {current}")
    return current


def digest_file(path):
    digest = hashlib.sha256()
    count = 0
    with path.open("rb") as source:
        while block := source.read(BLOCK):
            count += len(block)
            digest.update(block)
    return count, digest.hexdigest()


def matches(path, row):
    if not path.is_file():
        return False
    if path.stat().st_size != row["bytes"]:
        return False
    return digest_file(path) == (row["bytes"], row["sha256"])


def validate_blob(row, key):
    if not isinstance(row, dict):
        raise AssetError("File/asset entries must be objects")
    relative_path(row.get(key))
    if key == "name" and len(PurePosixPath(row[key]).parts) != 1:
        raise AssetError("Asset names must be basenames")
    if type(row.get("bytes")) is not int or row["bytes"] < 0:
        raise AssetError(f"Invalid byte count: {row.get(key)}")
    if not isinstance(row.get("sha256"), str) or not re.fullmatch(r"[0-9a-f]{64}", row["sha256"]):
        raise AssetError(f"Invalid lowercase SHA256: {row.get(key)}")


def validate_url(row):
    parsed = urlparse(row.get("url", ""))
    if parsed.scheme not in ("http", "https") or not parsed.netloc:
        raise AssetError("Asset URLs must use HTTP(S); use --assets-dir for local input")
    headers = row.get("headers", {})
    if not isinstance(headers, dict) or any(
        not isinstance(k, str) or not isinstance(v, str) or "\r" in k + v or "\n" in k + v
        for k, v in headers.items()
    ):
        raise AssetError("Invalid HTTP headers")


def validate_profiles(row):
    profiles = row.get("profiles")
    if not isinstance(profiles, list) or not profiles or any(
        p not in ("ppe", "training") for p in profiles
    ):
        raise AssetError("Profiles must be a nonempty list of ppe/training; full is no longer supported")


def load_manifest(path):
    manifest = json.loads(path.read_text(encoding="utf-8"))
    if manifest.get("schema") != SCHEMA:
        raise AssetError(f"Expected schema {SCHEMA}")
    if not all(isinstance(manifest.get(k), str) and manifest[k] for k in ("repository", "release_tag")):
        raise AssetError("Manifest repository/release_tag must be nonempty strings")
    for key in ("bundles", "external_files"):
        if not isinstance(manifest.get(key), list):
            raise AssetError(f"Manifest {key} must be a list")
    destinations, ids, asset_names = set(), set(), {}
    for bundle in manifest["bundles"]:
        if not isinstance(bundle, dict) or not isinstance(bundle.get("id"), str) or not bundle["id"]:
            raise AssetError("Bundle id must be a nonempty string")
        if bundle["id"] in ids:
            raise AssetError(f"Duplicate bundle: {bundle['id']}")
        ids.add(bundle["id"])
        validate_profiles(bundle)
        if not isinstance(bundle.get("assets"), list) or not bundle["assets"]:
            raise AssetError("Bundle assets must be a nonempty list")
        if not isinstance(bundle.get("files"), list) or not bundle["files"]:
            raise AssetError("Bundle files must be a nonempty list")
        if bundle.get("format") == "zip":
            if len(bundle["assets"]) != 1:
                raise AssetError("A zip bundle must contain one archive asset")
        elif bundle.get("format") == "raw-parts":
            if len(bundle["files"]) != 1:
                raise AssetError("raw-parts requires exactly one output file")
            if sum(a.get("bytes", -1) for a in bundle["assets"]) != bundle["files"][0].get("bytes"):
                raise AssetError("raw-parts byte counts do not add up to output size")
        else:
            raise AssetError("Bundle format must be zip or raw-parts")
        for asset in bundle["assets"]:
            validate_blob(asset, "name")
            validate_url(asset)
            if asset["bytes"] >= 2 * 1024**3:
                raise AssetError("Release assets must be smaller than 2 GiB")
            signature = (asset["bytes"], asset["sha256"])
            if asset["name"] in asset_names and asset_names[asset["name"]] != signature:
                raise AssetError(f"Conflicting asset basename: {asset['name']}")
            asset_names[asset["name"]] = signature
        for row in bundle["files"]:
            validate_blob(row, "path")
            if row["path"] in destinations:
                raise AssetError(f"Duplicate destination: {row['path']}")
            destinations.add(row["path"])
    for row in manifest["external_files"]:
        validate_blob(row, "path")
        validate_profiles(row)
        validate_url(row)
        if row["path"] in destinations:
            raise AssetError(f"Duplicate destination: {row['path']}")
        destinations.add(row["path"])
    for dest in destinations:
        if any(str(parent) in destinations for parent in PurePosixPath(dest).parents):
            raise AssetError(f"A file destination is another file's parent: {dest}")
        if dest == ".runtime/asset-downloads" or dest.startswith(".runtime/asset-downloads/"):
            raise AssetError("Output destinations cannot overlap the download cache")
    return manifest


def selected(row, profile, training):
    return profile in row["profiles"] or (training and "training" in row["profiles"])


def check_destination(root, row):
    path = safe_path(root, row["path"])
    if path.exists():
        if not matches(path, row):
            raise AssetError(f"Existing destination differs; refusing overwrite: {path}")
        return True
    for parent in path.parents:
        if parent == root:
            break
        if parent.exists() and not parent.is_dir():
            raise AssetError(f"Destination parent is not a directory: {parent}")
    return False


def cached_name(row):
    return f"{row['sha256']}-{row.get('name', PurePosixPath(row.get('path', '')).name)}"


def local_source(assets_dir, row):
    names = [cached_name(row), row.get("name", PurePosixPath(row.get("path", "")).name)]
    for name in names:
        path = safe_path(assets_dir, name)
        if path.exists():
            if not matches(path, row):
                raise AssetError(f"Offline asset SHA256/size mismatch: {path}")
            return path
    raise AssetError(f"Missing offline asset: {names[-1]} (in {assets_dir})")


def copy_checked(source, output, row, digest=None):
    own_digest = hashlib.sha256()
    count = 0
    while block := source.read(BLOCK):
        count += len(block)
        if count > row["bytes"]:
            raise AssetError("Input exceeds pinned byte count")
        own_digest.update(block)
        if digest is not None:
            digest.update(block)
        output.write(block)
    if (count, own_digest.hexdigest()) != (row["bytes"], row["sha256"]):
        raise AssetError(f"SHA256/size mismatch: {row.get('path', row.get('name'))}")


def fetch(root, row, assets_dir):
    if assets_dir:
        return local_source(assets_dir, row)
    cache = safe_path(root, ".runtime/asset-downloads")
    target = safe_path(root, ".runtime/asset-downloads/" + cached_name(row))
    if target.exists():
        if not matches(target, row):
            raise AssetError(f"Cached asset differs; remove only this damaged cache file and retry: {target}")
        return target
    cache.mkdir(parents=True, exist_ok=True)
    print(f"Downloading {row.get('name', row.get('path'))}: {row['bytes']} bytes", file=sys.stderr, flush=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=cache, prefix=".download-", delete=False) as output:
            temporary = Path(output.name)
            request = Request(row["url"], headers=row.get("headers", {}))
            with urlopen(request, timeout=60) as response:
                copy_checked(response, output, row)
        publish(root, temporary, target, row)
        return target
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def publish(root, temporary, target, row):
    # An exclusive hard link avoids replacing a file created since the first check.
    safe_path(root, target.relative_to(root).as_posix())
    try:
        os.link(temporary, target)
    except FileExistsError:
        safe_path(root, target.relative_to(root).as_posix())
        if not matches(target, row):
            raise AssetError(f"Destination appeared with different content: {target}")


def stage_output(root, row, producer):
    path = safe_path(root, row["path"])
    print(f"Restoring {row['path']}", file=sys.stderr, flush=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = None
    try:
        with tempfile.NamedTemporaryFile(dir=path.parent, prefix=".restore-", delete=False) as output:
            temporary = Path(output.name)
            producer(output)
        publish(root, temporary, path, row)
    finally:
        if temporary:
            temporary.unlink(missing_ok=True)


def restore_zip(root, bundle, archive):
    rows = {row["path"]: row for row in bundle["files"]}
    ancestors = {str(p) for name in rows for p in PurePosixPath(name).parents if str(p) != "."}
    with zipfile.ZipFile(archive) as source:
        members = {}
        for info in source.infolist():
            name = info.filename.rstrip("/") if info.is_dir() else info.filename
            relative_path(name)
            mode = stat.S_IFMT(info.external_attr >> 16)
            if mode not in (0, stat.S_IFREG, stat.S_IFDIR) or (mode == stat.S_IFDIR and not info.is_dir()):
                raise AssetError(f"Archive symlink/special file refused: {info.filename}")
            if name in members:
                raise AssetError(f"Duplicate archive member: {name}")
            members[name] = info
            if info.is_dir():
                if name not in ancestors:
                    raise AssetError(f"Archive directory outside whitelist: {name}")
            elif name not in rows or info.file_size != rows[name]["bytes"]:
                raise AssetError(f"Archive file/size outside whitelist: {name}")
        if any(name not in members or members[name].is_dir() for name in rows):
            raise AssetError("Archive is missing a whitelisted file")
        for name, row in rows.items():
            if check_destination(root, row):
                continue
            def produce(output, member=members[name], item=row):
                with source.open(member) as content:
                    copy_checked(content, output, item)
            stage_output(root, row, produce)


def restore(root, manifest, profile="ppe", training=False, assets_dir=None, verify_only=False, plan=False):
    if profile != "ppe":
        raise AssetError("Only the ppe profile is supported; full runtime assets have been removed")
    bundles = [b for b in manifest["bundles"] if selected(b, profile, training)]
    external = [r for r in manifest["external_files"] if selected(r, profile, training)]
    rows = [r for b in bundles for r in b["files"]] + external
    ready = {r["path"]: check_destination(root, r) for r in rows}
    missing = [r["path"] for r in rows if not ready[r["path"]]]
    needed = [a for b in bundles if any(not ready[r["path"]] for r in b["files"]) for a in b["assets"]]
    needed += [r for r in external if not ready[r["path"]]]
    result = {"profile": profile, "include_training": training, "files": len(rows),
              "verified_existing": sum(ready.values()), "missing": missing,
              "download_bytes_upper_bound": sum(a["bytes"] for a in needed) if not assets_dir else 0,
              "output_bytes_missing": sum(r["bytes"] for r in rows if not ready[r["path"]]),
              "assets_needed": [a.get("name", PurePosixPath(a.get("path", "")).name) for a in needed],
              "cache": str(root / ".runtime/asset-downloads"),
              "space_note": "Network assets remain cached; allow missing output + asset bytes + largest output temp. Offline inputs are read in place."}
    if plan:
        result["mode"] = "plan"
        return result
    if verify_only:
        if missing:
            raise AssetError("Missing restored files: " + ", ".join(missing))
        result["mode"] = "verified"
        return result
    for bundle in bundles:
        if all(ready[r["path"]] for r in bundle["files"]):
            continue
        inputs = [fetch(root, a, assets_dir) for a in bundle["assets"]]
        if bundle["format"] == "zip":
            restore_zip(root, bundle, inputs[0])
        else:
            row = bundle["files"][0]
            def concatenate(output):
                total = hashlib.sha256()
                for source, asset in zip(inputs, bundle["assets"]):
                    with source.open("rb") as stream:
                        copy_checked(stream, output, asset, total)
                if total.hexdigest() != row["sha256"]:
                    raise AssetError(f"Assembled output SHA256 mismatch: {row['path']}")
            stage_output(root, row, concatenate)
    for row in external:
        if not ready[row["path"]]:
            source = fetch(root, row, assets_dir)
            def produce(output, item=row, path=source):
                with path.open("rb") as stream:
                    copy_checked(stream, output, item)
            stage_output(root, row, produce)
    for row in rows:
        if not check_destination(root, row):
            raise AssetError(f"Restoration did not produce {row['path']}")
    result.update(mode="restored", restored=len(missing), missing=[])
    return result


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--profile", choices=("ppe",), default="ppe")
    parser.add_argument("--include-training", action="store_true")
    parser.add_argument("--manifest", type=Path)
    parser.add_argument("--project-root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--assets-dir", type=Path, help="Read asset basenames or SHA256-basename from this directory; no network")
    modes = parser.add_mutually_exclusive_group()
    modes.add_argument("--verify-only", action="store_true")
    modes.add_argument("--plan", action="store_true")
    args = parser.parse_args(argv)
    try:
        root = args.project_root.resolve()
        if not root.is_dir():
            raise AssetError("Project root must already be a directory")
        manifest = load_manifest(args.manifest or root / "config/runtime-assets.json")
        assets = args.assets_dir.absolute() if args.assets_dir else None
        if assets and (assets.is_symlink() or not assets.is_dir()):
            raise AssetError("Offline assets directory must be a real directory")
        print(json.dumps(restore(root, manifest, args.profile, args.include_training,
                                 assets, args.verify_only, args.plan), ensure_ascii=False, indent=2))
        return 0
    except (AssetError, OSError, ValueError, KeyError, TypeError, zipfile.BadZipFile) as exc:
        print(f"Asset restore failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
