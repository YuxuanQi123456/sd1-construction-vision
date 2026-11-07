"""Thin class-remapping adapter; all matching and AP come from Ultralytics YOLO.val."""
import argparse
from collections import Counter
from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import time

CORE = ["helmet", "no_helmet", "person", "vest"]
FULL = CORE + ["no_vest"]


def sha(path):
    with Path(path).open("rb") as source:
        return hashlib.file_digest(source, "sha256").hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--models", type=Path, required=True)
    parser.add_argument("--project-root", type=Path)
    parser.add_argument("--dataset-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--imgsz", type=int, default=640)
    args = parser.parse_args()
    if args.output.exists():
        parser.error("Output directory exists; preserve old evidence and use a new directory")
    args.output.mkdir(parents=True)
    runtime = args.output.resolve() / "runtime"
    runtime.mkdir()
    os.environ.update(CUDA_VISIBLE_DEVICES="", YOLO_CONFIG_DIR=str(runtime / "ultralytics"),
                      MPLCONFIGDIR=str(runtime / "matplotlib"), XDG_CACHE_HOME=str(runtime / "cache"),
                      YOLO_AUTOINSTALL="false", YOLO_OFFLINE="true", HF_HUB_OFFLINE="1")
    # Font alias affects plot text only, never input pixels or metric matching.
    # Keep the actual local font source explicit and avoid a hidden font download.
    font_source = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    font_cache = runtime / "ultralytics/Ultralytics"
    font_cache.mkdir(parents=True)
    assert font_source.is_file(), "Local plotting font unavailable; no download attempted"
    shutil.copyfile(font_source, font_cache / "Arial.ttf")
    import yaml
    import torch
    from ultralytics import YOLO
    from native_validator import ClassRestrictedValidator
    torch.set_num_threads(2)
    project = (args.project_root or args.models.resolve().parents[1]).resolve()
    dataset = args.dataset_root.resolve()
    manifest = json.loads(args.models.read_text())
    lock = json.loads((dataset / "dataset-lock.json").read_text())
    assert lock["test_only"] and lock["image_count"] == 90
    for entry in lock["files"]:
        assert sha(dataset / entry["path"]) == entry["sha256"], entry["path"]
    spec = yaml.safe_load((dataset / "data.yaml").read_text())
    source_names = spec["names"]
    source_names = dict(enumerate(source_names)) if isinstance(source_names, list) else source_names
    source_names = {int(k): v.replace("-", "_").lower() for k, v in source_names.items()}
    assert set(source_names.values()) == set(FULL), source_names
    image_paths = sorted((dataset / "test/images").glob("*"))
    assert len(image_paths) == 90
    gt = {}
    counts = Counter()
    duplicate_bytes = {}
    for image in image_paths:
        label = dataset / "test/labels" / (image.stem + ".txt")
        rows = []
        for line in label.read_text().splitlines():
            values = line.split()
            if not values:
                continue
            assert len(values) == 5, str(label)
            cls = int(values[0]); coords = [float(v) for v in values[1:]]
            assert cls in source_names and all(0 <= v <= 1 for v in coords), str(label)
            assert coords[2] > 0 and coords[3] > 0, str(label)
            rows.append((source_names[cls], values[1:]))
            counts[source_names[cls]] += 1
        gt[image.name] = rows
        duplicate_bytes.setdefault(sha(image), []).append(image.name)
    report = {"schema": "ppe-native-val-v1", "at": datetime.now(timezone.utc).isoformat(),
              "models_manifest_sha256": sha(args.models), "dataset_lock_sha256": sha(dataset / "dataset-lock.json"),
              "dataset_revision": lock["revision"], "images": 90, "gt_instances": dict(counts),
              "empty_images": sum(not rows for rows in gt.values()),
              "exact_duplicate_image_groups": [names for names in duplicate_bytes.values() if len(names) > 1],
              "versions": {n: importlib.metadata.version(n) for n in ["ultralytics", "torch", "torchvision"]},
              "settings": {"imgsz": args.imgsz, "conf": 0.001, "iou": 0.7, "batch": 1, "workers": 0,
                           "device": "cpu", "cpu_threads": 2, "max_det": 300},
              "local_plot_font": {"actual_source": str(font_source), "sha256": sha(font_source),
                                  "upstream_requested_name": "Arial.ttf", "affects_model_input": False},
              "precision_recall_notice": "Official Ultralytics P/R use its confidence sweep/best-F1 operating point, not deployment confidence 0.40.",
              "validator": {"base": "Ultralytics DetectionValidator", "adapter": "ClassRestrictedValidator",
                            "change": "Pass existing args.classes to native NMS; matching/metrics inherited unchanged.",
                            "source_sha256": sha(Path(__file__).with_name("native_validator.py"))},
              "scope_notice": "Full fixed public test split; possible candidate training overlap. Does not establish onsite generalization or legal violations.",
              "results": [], "passed": False}
    target = args.output / "report.json"
    try:
        for model_spec in manifest["models"]:
            weight = project / model_spec["weights"]
            assert sha(weight) == model_spec["sha256"], str(weight)
            model = YOLO(str(weight))
            actual_names = [model.names[i] for i in range(len(model.names))]
            assert actual_names == model_spec["expected_names"], {"model": model_spec["id"], "actual_names": actual_names}
            for task, classes in [("core4", CORE), ("full5", FULL)]:
                absent = [name for name in classes if name not in model_spec["classes"]]
                result = {"model_id": model_spec["id"], "task": task, "canonical_classes": classes,
                          "mapping": model_spec["classes"], "model_sha256": model_spec["sha256"]}
                report["results"].append(result)
                if absent:
                    result.update(status="unsupported", unsupported_classes=absent)
                    continue
                remapped = project / "downloads/ppe-v07/benchmark" / lock["revision"] / args.output.name / model_spec["id"] / task
                if remapped.exists():
                    raise RuntimeError(f"Derived cache exists; use a distinct output run name: {remapped}")
                image_dir, label_dir = remapped / "images/test", remapped / "labels/test"
                image_dir.mkdir(parents=True); label_dir.mkdir(parents=True)
                for image in image_paths:
                    shutil.copyfile(image, image_dir / image.name)
                    lines = [" ".join([str(model_spec["classes"][name]), *coords]) for name, coords in gt[image.name] if name in classes]
                    (label_dir / (image.stem + ".txt")).write_text("\n".join(lines) + ("\n" if lines else ""))
                local_yaml = remapped / "data.yaml"
                local_yaml.write_text(yaml.safe_dump({"path": str(remapped), "train": None,
                    "val": "images/test", "test": "images/test", "names": actual_names}, sort_keys=False))
                mapping = {"dataset_revision": lock["revision"], "model_id": model_spec["id"], "task": task,
                    "canonical_to_model_id": {name: model_spec["classes"][name] for name in classes},
                    "model_names": actual_names, "data_yaml_sha256": sha(local_yaml), "derived_cache": str(remapped),
                    "evaluation_only": True, "training_performed": False,
                    "files": [{"image": image.name, "image_sha256": sha(image_dir / image.name),
                               "remapped_label_sha256": sha(label_dir / (image.stem + ".txt"))} for image in image_paths]}
                mapping_file = args.output / model_spec["id"] / task / "mapping.json"
                mapping_file.parent.mkdir(parents=True, exist_ok=True)
                mapping_file.write_text(json.dumps(mapping, ensure_ascii=False, indent=2) + "\n")
                result["mapping_sha256"] = sha(mapping_file)
                result["derived_cache"] = str(remapped)
                selected = [model_spec["classes"][name] for name in classes]
                started = time.perf_counter()
                metrics = model.val(validator=ClassRestrictedValidator, data=str(local_yaml), split="test", classes=selected, device="cpu",
                    imgsz=args.imgsz, conf=0.001, iou=0.7, batch=1, workers=0, max_det=300,
                    plots=True, save_json=True, project=str(args.output.resolve() / model_spec["id"] / task),
                    name="validation", exist_ok=False, verbose=True)
                native_prediction_file = Path(metrics.save_dir) / "predictions.json"
                native_predictions = json.loads(native_prediction_file.read_text())
                allowed_json_ids = {raw_id + 1 for raw_id in selected}
                assert all(p["category_id"] in allowed_json_ids for p in native_predictions), "Native predictions contain out-of-task classes"
                per_class = []
                reverse = {raw: name for name, raw in model_spec["classes"].items() if name in classes}
                for i, raw_id in enumerate(metrics.ap_class_index):
                    raw_id = int(raw_id)
                    assert raw_id in reverse, raw_id
                    p, r, ap50, ap = metrics.class_result(i)
                    per_class.append({"canonical": reverse[raw_id], "raw_id": raw_id,
                                      "instances": counts[reverse[raw_id]], "precision": float(p), "recall": float(r),
                                      "mAP50": float(ap50), "mAP50_95": float(ap)})
                result.update(status="complete", elapsed_seconds=time.perf_counter()-started,
                    denominator_instances=sum(counts[c] for c in classes), per_class=per_class,
                    metrics={k: float(v) for k, v in metrics.results_dict.items()},
                    speed=metrics.speed, output=str(Path(metrics.save_dir).relative_to(args.output.resolve())),
                    native_predictions_sha256=sha(native_prediction_file),
                    native_prediction_classes_verified=True,
                    prediction_json_class_id_notice="Native validator stores category_id=raw_model_id+1 for non-COCO datasets.")
                target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
                print(json.dumps({"model": model_spec["id"], "task": task, "metrics": result["metrics"]}), flush=True)
            del model
        report["passed"] = True
    except Exception as exc:
        report["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        target.write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")


if __name__ == "__main__":
    main()
