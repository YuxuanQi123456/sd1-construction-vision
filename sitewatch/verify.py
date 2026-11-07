"""Run real CPU inference and strict-failure controls on licensed local media."""
import argparse
from datetime import datetime, timezone
import importlib.metadata
import json
import os
from pathlib import Path
import sys
import tempfile


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--project-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--video-seconds", type=float, default=3)
    parser.add_argument("--model-id", choices=['sitewatch', 'constructelligence-v03'], default='sitewatch')
    args = parser.parse_args()
    args.output.mkdir(parents=True, exist_ok=True)
    runtime = args.project_root / ".runtime/sitewatch-env/runtime"
    for path in [runtime, runtime / "ultralytics", runtime / "matplotlib"]:
        path.mkdir(parents=True, exist_ok=True)
    os.environ["CUDA_VISIBLE_DEVICES"] = ""
    os.environ["YOLO_CONFIG_DIR"] = str(runtime / "ultralytics")
    os.environ["MPLCONFIGDIR"] = str(runtime / "matplotlib")
    sys.path.insert(0, str(Path(__file__).resolve().parent / "app"))
    from cv_pipeline.detection import Detector
    from review_evidence import review_file
    import torch
    specs = json.loads((Path(__file__).resolve().parent / 'model-candidates.json').read_text())['models']
    model_spec = next(item for item in specs if item['id'] == args.model_id)
    model = args.project_root / model_spec['weights']
    detector = Detector(custom_path=str(model), model_id=args.model_id)
    report = {"at": datetime.now(timezone.utc).isoformat(), "device": "cpu",
              "cuda_visible_devices": os.environ["CUDA_VISIBLE_DEVICES"],
              "versions": {name: importlib.metadata.version(name) for name in
                           ["streamlit", "ultralytics", "torch", "torchvision", "numpy", "opencv-python", "scipy"]},
              "model_id": args.model_id, "actual_model_names": detector.names, "model_sha256": detector.model_sha256,
              "reviews": [], "failure_controls": []}
    assert next(detector.custom.model.parameters()).device.type == "cpu"
    for filename in ["niosh-runway-worker.jpg", "working-the-grinder.jpg"]:
        path = args.project_root / "downloads/vision-samples" / filename
        result = review_file(path, detector, args.output / path.stem)
        report["reviews"].append({"file": filename, "report": str(Path(path.stem) / "detections.json"),
                                  "elapsed_seconds": result["elapsed_seconds"],
                                  "detections": result["frames"][0]["detections"]})
        print(json.dumps(report["reviews"][-1], ensure_ascii=False), flush=True)
    video = args.project_root / ".runtime/vision-media/window-florenc-0-8.0.mp4"
    if not video.is_file():
        video = args.project_root / "downloads/vision-samples/florenc.webm"
    result = review_file(video, detector, args.output / "florenc-video", max_seconds=args.video_seconds)
    report["reviews"].append({"file": str(video), "report": "florenc-video/detections.json",
                              "elapsed_seconds": result["elapsed_seconds"],
                              "frames": len(result["frames"]), "timestamps": [f["timestamp_seconds"] for f in result["frames"]]})
    assert len(result["frames"]) == int(args.video_seconds)
    for name, path, expected in [
        ("missing_model", runtime / "never-existing-sitewatch.pt", FileNotFoundError),
        ("wrong_sha", args.output / "wrong-weights.pt", ValueError),
    ]:
        if name == "wrong_sha":
            path.write_bytes(b"not a PPE model")
        try:
            Detector(custom_path=str(path), model_id=args.model_id)
        except expected as exc:
            report["failure_controls"].append({"name": name, "passed": True, "error": str(exc)})
        else:
            raise AssertionError(f"{name} must fail, never fall back to COCO")
        finally:
            if name == "wrong_sha":
                path.unlink()
    bad = args.output / "invalid.jpg"
    bad.write_bytes(b"invalid image")
    try:
        review_file(bad, detector, args.output / "invalid-upload")
    except ValueError as exc:
        report["failure_controls"].append({"name": "invalid_image", "passed": True, "error": str(exc)})
    else:
        raise AssertionError("Invalid image must be a visible failure")
    finally:
        bad.unlink()
    # Corrupt the tail of MP4 media data while retaining its original metadata.
    # A decoder that stops after early valid frames must not report completion.
    video_bytes = bytearray(video.read_bytes())
    moov = video_bytes.find(b"moov")
    if video.suffix == ".mp4" and moov > len(video_bytes) // 2:
        broken = args.output / "broken-video.mp4"
        corruption_start = len(video_bytes) // 3
        video_bytes[corruption_start:moov-4] = b"\x00" * (moov - 4 - corruption_start)
        broken.write_bytes(video_bytes)
        try:
            review_file(broken, detector, args.output / "broken-video-control", max_seconds=8)
        except ValueError as exc:
            failed = json.loads((args.output / "broken-video-control/detections.json").read_text())
            assert failed["status"] == "failed"
            assert failed["video"]["stop_reason"] == "premature_decode_failure"
            assert failed["frames"], "Control must decode some real frames before failing"
            report["failure_controls"].append({"name": "premature_video_decode", "passed": True,
                                                "error": str(exc), "retained_frames": len(failed["frames"]),
                                                "decoded_frames": failed["video"]["decoded_frames"]})
        else:
            raise AssertionError("Midstream corrupted video must not be marked complete")
        finally:
            broken.unlink()
    report["technical_passed"] = True
    report["business_accuracy"] = "Requires human comparison with source media; inference success is not an accuracy result."
    report["torch_model_device"] = str(next(detector.custom.model.parameters()).device)
    (args.output / "verification.json").write_text(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
