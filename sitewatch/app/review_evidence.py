"""Thin offline evidence adapter around SiteWatch's detector and drawing code."""
from __future__ import annotations

from dataclasses import asdict
from datetime import datetime, timezone
import hashlib
import json
import math
from pathlib import Path
import time
import uuid
import zipfile

import cv2

from cv_pipeline.enhancement import enhance
from utils.drawing import draw_overlay

NOTICE = "NO-* 为模型待人工复核类别，不等于法规违规；未检出不等于缺少或安全。仅分析已列出时间点，不推断视频全程。"
PPE_LABELS = {"Gloves", "Hardhat", "Mask", "NO-Hardhat", "NO-Mask", "NO-Safety Vest", "Safety Vest",
              "hardhat", "no-hardhat", "safety vest", "no-safety vest", "no-mask", "gloves",
              "safety shoes", "goggles", "no-goggles", "no-gloves"}
REVIEW_LABELS = PPE_LABELS | {'Person', 'person', 'human'}


def source_provenance(digest):
    """Match attribution by original bytes; never pass this metadata to YOLO."""
    registry = Path(__file__).resolve().parents[1] / "media-sources.json"
    for entry in json.loads(registry.read_text()):
        if entry.get("sha256") == digest:
            return {"registered": True, "matching_method": "exact source SHA256", **entry}
    return {"registered": False, "sha256": digest,
            "notice": "用户上传素材来源与许可未登记；不套用公开示例的作者或许可。"}


def resize_long_edge(frame, max_long=1280):
    h, w = frame.shape[:2]
    scale = min(1.0, max_long / max(h, w))
    return cv2.resize(frame, (round(w * scale), round(h * scale))) if scale < 1 else frame


def review_file(input_path, detector, output_dir, *, do_enhance=False,
                sample_seconds=1.0, max_seconds=8.0, callback=None,
                preserve_resolution=False):
    """Save original upload, all sampled frames, raw boxes, and true overlays.

    The input filename or attribution is never used as an inference prompt.
    All 25 original model labels remain available as observations. Only direct
    NO-* model classes appear in the manual PPE review count; no missing-item,
    proximity, motion or shape rule is evaluated.
    """
    input_path, output_dir = Path(input_path), Path(output_dir)
    if preserve_resolution and do_enhance:
        raise ValueError('保留原片画质时请关闭图像增强')
    if sample_seconds < 0.2 or max_seconds <= 0 or max_seconds > 30:
        raise ValueError("Sampling must be >= 0.2 s and review duration in (0, 30] s")
    output_dir.mkdir(parents=True, exist_ok=False)
    data = input_path.read_bytes()
    suffix = input_path.suffix.lower()
    source = output_dir / ("original" + suffix)
    source.write_bytes(data)
    attribution = source_provenance(hashlib.sha256(data).hexdigest())
    (output_dir / "source-provenance.json").write_text(json.dumps(attribution, ensure_ascii=False, indent=2) + "\n")
    record = {
        "schema": "sitewatch-offline-review-v1", "status": "processing",
        "created_at": datetime.now(timezone.utc).isoformat(),
        "source_name": input_path.name, "source_sha256": hashlib.sha256(data).hexdigest(),
        "source_bytes": len(data), "source_file": source.name,
        "source_provenance": attribution,
        "model": dict(detector.provenance),
        "settings": {"confidence": detector.conf_threshold, "image_enhancement": do_enhance,
                     "inference_imgsz": detector.inference_imgsz,
                     "max_long_edge": None if preserve_resolution else 1280,
                     "preserve_resolution": preserve_resolution,
                     "saved_frame_format": 'png' if preserve_resolution else 'jpeg',
                     "profile": detector.profile,
                     "person_companion": detector.person is not None,
                     "motion_rules": False, "proximity_rules": False, "shape_rules": False,
                     "sample_seconds": sample_seconds, "max_seconds": max_seconds},
        "notice": NOTICE, "frames": [],
    }
    start = time.perf_counter()

    def process(frame, idx, timestamp):
        image = frame if preserve_resolution else resize_long_edge(frame)
        image = enhance(image) if do_enhance else image
        dets, branches, inference_ms = detector.detect_frame(image)
        label_scale = max(1., max(image.shape[:2]) / 1280) if preserve_resolution else 1.
        # Reuse the upstream overlay, without rule-generated announcements.
        overlay = draw_overlay(image, dets, [], [], [], label_scale=label_scale)
        ppe_overlay = draw_overlay(image, [d for d in dets if d.class_name in PPE_LABELS], [], [], [], label_scale=label_scale)
        review_dets = [d for d in dets if d.class_name in REVIEW_LABELS]
        review_dets.sort(key=lambda d: (d.bbox[2]-d.bbox[0]) * (d.bbox[3]-d.bbox[1]), reverse=True)
        review_overlay = draw_overlay(image, review_dets, [], [], [], label_scale=label_scale)
        stem = f"frame-{idx:06d}"
        extension = '.png' if preserve_resolution else '.jpg'
        saved = []
        def save(suffix, pixels):
            # Lossless, identical variants share one file to avoid duplicating
            # large native frames. Every JSON field still names its exact pixels.
            if preserve_resolution:
                for filename, previous in saved:
                    if pixels.shape == previous.shape and cv2.norm(pixels, previous, cv2.NORM_INF) == 0:
                        return filename
            filename = stem + suffix + extension
            options = [cv2.IMWRITE_PNG_COMPRESSION, 3] if preserve_resolution else []
            if not cv2.imwrite(str(output_dir / filename), pixels, options):
                raise OSError('Could not save evidence frame')
            saved.append((filename, pixels))
            return filename
        raw_file = save('-input', image)
        overlay_file = save('-overlay', overlay)
        ppe_file = save('-ppe-overlay', ppe_overlay)
        review_file = save('-review-overlay', review_overlay)
        result = {"frame_index": idx, "timestamp_seconds": timestamp,
                  "source_dimensions_wh": [frame.shape[1], frame.shape[0]],
                  "detection_dimensions_wh": [image.shape[1], image.shape[0]],
                  "preserved_native_pixels": preserve_resolution,
                  "annotation_scale": label_scale,
                  "input_file": raw_file, "overlay_file": overlay_file,
                  "ppe_overlay_file": ppe_file,
                  "review_overlay_file": review_file,
                  "inference_ms": inference_ms,
                  "detections": [asdict(d) for d in dets],
                  "model_branches": {key: [asdict(d) for d in values] for key, values in branches.items()}}
        record["frames"].append(result)
        # Preserve completed frames even if a later frame fails.
        (output_dir / "detections.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
        if callback:
            callback(overlay, result)

    cap = None
    try:
        if suffix in {".jpg", ".jpeg", ".png"}:
            image = cv2.imread(str(source))
            if image is None:
                raise ValueError("Could not decode uploaded image")
            record["media_type"] = "image"
            process(image, 0, 0.0)
        else:
            record["media_type"] = "video"
            cap = cv2.VideoCapture(str(source))
            if not cap.isOpened():
                raise ValueError("Could not open uploaded video")
            fps = float(cap.get(cv2.CAP_PROP_FPS))
            if fps <= 0:
                raise ValueError("Video has no reliable FPS; cannot assign evidence timestamps")
            count = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)
            record["video"] = {"fps": fps, "frame_count": count,
                               "duration_seconds": count / fps if count else None,
                               "timestamp_basis": "decoded frame index / container FPS",
                               "decoded_frames": 0, "stop_reason": None}
            index, next_sample = 0, 0.0
            while True:
                if index / fps >= max_seconds:
                    record["video"]["stop_reason"] = "requested_duration_limit"
                    break
                ok, frame = cap.read()
                if not ok:
                    expected = min(count, math.ceil(max_seconds * fps)) if count else None
                    if expected and index < expected:
                        record["video"]["stop_reason"] = "premature_decode_failure"
                        raise ValueError(f"Video decode ended early at frame {index}; expected {expected} frames in requested range. Completed frame evidence is retained.")
                    record["video"]["stop_reason"] = "end_of_video" if count else "decoder_eof_unverified_frame_count"
                    break
                record["video"]["decoded_frames"] = index + 1
                timestamp = index / fps
                if timestamp + 1e-9 >= next_sample:
                    process(frame, index, timestamp)
                    next_sample += sample_seconds
                index += 1
            if not record["frames"]:
                raise ValueError("Video decoded no reviewable frames")
        record["status"] = "complete"
    except Exception as exc:
        record["status"] = "failed"
        record["error"] = f"{type(exc).__name__}: {exc}"
        raise
    finally:
        if cap is not None:
            cap.release()
        record["elapsed_seconds"] = time.perf_counter() - start
        record["manual_review_detection_count"] = sum(
            d["category"] == "ppe_violation" for f in record["frames"] for d in f["detections"])
        (output_dir / "detections.json").write_text(json.dumps(record, ensure_ascii=False, indent=2) + "\n")
    return record


def new_review_dir(runtime_root):
    return Path(runtime_root) / "reviews" / (datetime.now().strftime("%Y%m%d-%H%M%S-") + uuid.uuid4().hex[:8])


def evidence_zip(review_dir):
    """One local download contains original bytes, all boxes, and all frames."""
    review_dir = Path(review_dir)
    target = review_dir / "evidence.zip"
    with zipfile.ZipFile(target, "w", zipfile.ZIP_DEFLATED) as archive:
        for path in sorted(review_dir.rglob('*')):
            if path.is_file() and not path.is_symlink() and path != target:
                archive.write(path, str(path.relative_to(review_dir)))
    return target
