"""Open-source ByteTrack evidence and candidate zone events.

This module consumes the detector's saved JSON. It never changes the original
detections or the source media. Ultralytics' bundled ByteTrack implementation
is used as the runtime adapter; the detector and tracker remain separate so a
missing optional tracking dependency cannot silently change PPE results.
"""
from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import importlib.metadata
import json
from pathlib import Path
from typing import Any

import cv2


TRACKING_SCHEMA = "sitewatch-tracking-v1"
ZONES_SCHEMA = "sitewatch-zones-v1"
EVENTS_SCHEMA = "sitewatch-events-v1"
TRACKER_REPOSITORY = "https://github.com/FoundationVision/ByteTrack"


class TrackingError(ValueError):
    """Controlled tracking diagnostic safe for the Streamlit page."""


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _read_json(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, UnicodeError) as exc:
        raise TrackingError(f"无法读取轨迹证据：{path.name}") from exc
    if not isinstance(value, dict):
        raise TrackingError(f"轨迹证据格式无效：{path.name}")
    return value


def _atomic_json(path: Path, value: Any) -> None:
    temporary = path.with_name(path.name + ".tmp")
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def _group(detection: dict[str, Any]) -> str | None:
    category = detection.get("category")
    if category == "worker":
        return "person"
    if category == "hazard":
        return "equipment"
    # Some registered PPE weights use a specific equipment label but no hazard
    # category. Keep this explicit list small and evidence-based.
    if str(detection.get("class_name", "")).lower() in {
        "excavator", "machinery", "wheel loader", "dump truck", "truck", "vehicle", "bus"
    }:
        return "equipment"
    return None


def _args(track_buffer: int = 15):
    try:
        from ultralytics.utils import IterableSimpleNamespace
    except ImportError as exc:  # pragma: no cover - exercised by environment check
        raise TrackingError("轨迹功能需要项目环境中的 Ultralytics 跟踪依赖") from exc
    return IterableSimpleNamespace(
        tracker_type="bytetrack",
        track_high_thresh=0.25,
        track_low_thresh=0.1,
        new_track_thresh=0.25,
        track_buffer=track_buffer,
        match_thresh=0.8,
        fuse_score=True,
    )


class ByteTrackEvidence:
    """Class-aware adapter around Ultralytics' open-source ByteTrack."""

    def __init__(self, sample_seconds: float = 1.0) -> None:
        if sample_seconds <= 0:
            raise TrackingError("轨迹采样间隔必须为正数")
        try:
            from ultralytics.trackers.byte_tracker import BYTETracker
            import torch
            from ultralytics.engine.results import Boxes
        except ImportError as exc:
            raise TrackingError("轨迹功能需要 lap、Torch 和 Ultralytics 跟踪依赖") from exc
        self._BYTETracker = BYTETracker
        self._Boxes = Boxes
        self._torch = torch
        # Frame rate is the evidence sampling rate, not a claim about source FPS.
        self._frame_rate = max(1, round(1.0 / sample_seconds))
        self._trackers = {group: BYTETracker(_args(), frame_rate=self._frame_rate)
                          for group in ("person", "equipment")}
        try:
            version = importlib.metadata.version("ultralytics")
        except importlib.metadata.PackageNotFoundError:
            version = "unknown"
        self.provenance = {
            "algorithm": "ByteTrack",
            "runtime_adapter": "ultralytics.trackers.byte_tracker.BYTETracker",
            "repository": TRACKER_REPOSITORY,
            "license": "MIT (upstream ByteTrack); Ultralytics runtime remains separately licensed",
            "ultralytics_version": version,
            "sample_seconds": sample_seconds,
            "frame_rate_basis": "saved evidence sample interval",
            "track_buffer_samples": 15,
        }

    def update(self, detections: list[dict[str, Any]], dimensions_wh: list[int]) -> list[dict[str, Any]]:
        width, height = dimensions_wh
        grouped: dict[str, list[tuple[int, dict[str, Any]]]] = {"person": [], "equipment": []}
        for index, detection in enumerate(detections):
            group = _group(detection)
            if group is not None:
                grouped[group].append((index, detection))
        tracks: list[dict[str, Any]] = []
        for group, values in grouped.items():
            rows = []
            for _, detection in values:
                bbox = detection.get("bbox_xyxy", detection.get("bbox"))
                confidence = detection.get("confidence")
                class_id = detection.get("class_id", -1)
                if (not isinstance(bbox, (list, tuple)) or len(bbox) != 4
                        or not isinstance(confidence, (int, float))):
                    continue
                rows.append([float(v) for v in bbox] + [float(confidence), float(class_id)])
            tensor = self._torch.tensor(rows, dtype=self._torch.float32).reshape((-1, 6))
            boxes = self._Boxes(tensor, (int(height), int(width)))
            output = self._trackers[group].update(boxes)
            for row in output.tolist():
                if len(row) < 8:
                    continue
                x1, y1, x2, y2, track_id, confidence, class_id, source_index = row[:8]
                source_index = int(source_index)
                if source_index < 0 or source_index >= len(values):
                    continue
                original_index, detection = values[source_index]
                tracks.append({
                    "track_id": f"{group}-{int(track_id)}",
                    "track_number": int(track_id),
                    "group": group,
                    "class_name": detection.get("class_name", ""),
                    "category": detection.get("category", "other"),
                    "bbox_xyxy": [round(float(v), 3) for v in (x1, y1, x2, y2)],
                    "confidence": round(float(confidence), 6),
                    "detection_index": original_index,
                    "class_id": int(class_id),
                })
        tracks.sort(key=lambda item: item["track_id"])
        return tracks


def _color(track_id: str) -> tuple[int, int, int]:
    digest = hashlib.sha256(track_id.encode("utf-8")).digest()
    return int(digest[0]), int(digest[1]), int(digest[2])


def _draw_overlay(input_path: Path, output_path: Path, tracks: list[dict[str, Any]], history: dict[str, list[tuple[int, int]]]) -> None:
    image = cv2.imread(str(input_path))
    if image is None:
        raise TrackingError(f"无法读取轨迹关键帧：{input_path.name}")
    for track in tracks:
        x1, y1, x2, y2 = [int(round(v)) for v in track["bbox_xyxy"]]
        color = _color(track["track_id"])
        points = history.get(track["track_id"], [])
        for before, after in zip(points, points[1:]):
            cv2.line(image, before, after, color, 2, cv2.LINE_AA)
        cv2.rectangle(image, (x1, y1), (x2, y2), color, 2)
        label = f"{track['track_id']} {track['class_name']}"
        cv2.putText(image, label, (max(0, x1), max(18, y1 - 6)),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.55, color, 2, cv2.LINE_AA)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    if not cv2.imwrite(str(output_path), image):
        raise TrackingError(f"无法保存轨迹证据：{output_path.name}")


def augment_tracking(review_dir: str | Path, result: dict[str, Any], sample_seconds: float = 1.0) -> dict[str, Any]:
    """Build tracks and derived overlays from completed detector evidence."""
    review_dir = Path(review_dir).resolve()
    if not review_dir.is_dir() or not (review_dir / "detections.json").is_file():
        raise TrackingError("本次检测证据目录无效")
    if result.get("status") != "complete":
        raise TrackingError("仅允许为已完成检测生成轨迹")
    frames = result.get("frames")
    if not isinstance(frames, list) or not frames:
        raise TrackingError("本次检测没有可跟踪的采样画面")
    engine = ByteTrackEvidence(sample_seconds=sample_seconds)
    history: dict[str, list[tuple[int, int]]] = {}
    tracking_frames = []
    for frame_position, frame in enumerate(frames):
        dimensions = frame.get("detection_dimensions_wh")
        if not isinstance(dimensions, list) or len(dimensions) != 2:
            raise TrackingError("检测画面尺寸缺失，无法生成轨迹")
        tracks = engine.update(frame.get("detections", []), dimensions)
        for track in tracks:
            x1, y1, x2, y2 = track["bbox_xyxy"]
            history.setdefault(track["track_id"], []).append((round((x1 + x2) / 2), round((y1 + y2) / 2)))
        original = Path(frame["input_file"])
        overlay = review_dir / f"{original.stem}-tracks{original.suffix}"
        _draw_overlay(review_dir / original.name, overlay, tracks, history)
        tracking_frames.append({
            "frame_position": frame_position,
            "frame_index": frame["frame_index"],
            "timestamp_seconds": frame["timestamp_seconds"],
            "input_file": frame["input_file"],
            "frame_dimensions_wh": [int(dimensions[0]), int(dimensions[1])],
            "track_overlay_file": overlay.name,
            "tracks": tracks,
        })
    record = {
        "schema": TRACKING_SCHEMA,
        "created_at": _utc_now(),
        "source_detections_sha256": hashlib.sha256((review_dir / "detections.json").read_bytes()).hexdigest(),
        "media_type": result.get("media_type"),
        "provenance": engine.provenance,
        "frames": tracking_frames,
        "track_ids": sorted({track["track_id"] for frame in tracking_frames for track in frame["tracks"]}),
        "zones": [],
        "events": [],
        "notice": "轨迹 ID 只代表本次影像中的算法对象，不代表真实人员身份；事件为候选，需人工确认。",
    }
    _atomic_json(review_dir / "tracks.json", record)
    _atomic_json(review_dir / "zones.json", {"schema": ZONES_SCHEMA, "zones": [], "updated_at": _utc_now()})
    _atomic_json(review_dir / "events.json", {"schema": EVENTS_SCHEMA, "events": [], "updated_at": _utc_now(),
                                                "notice": record["notice"]})
    return {"track_count": len(record["track_ids"]), "frame_count": len(tracking_frames),
            "backend": engine.provenance, "events": 0}


def load_tracking(review_dir: str | Path) -> dict[str, Any] | None:
    path = Path(review_dir) / "tracks.json"
    return _read_json(path) if path.is_file() else None


def _inside(center: tuple[float, float], polygon: list[list[float]]) -> bool:
    # Rectangle is the first supported UI primitive; use a general ray cast so
    # stored zones can grow to polygons without changing event records.
    x, y = center
    inside = False
    j = len(polygon) - 1
    for i, point in enumerate(polygon):
        xi, yi = point
        xj, yj = polygon[j]
        intersects = ((yi > y) != (yj > y)) and (x < (xj - xi) * (y - yi) / ((yj - yi) or 1e-12) + xi)
        if intersects:
            inside = not inside
        j = i
    return inside


def save_zone_events(review_dir: str | Path, polygon: list[list[float]], name: str = "候选区域",
                     stay_seconds: float = 2.0) -> dict[str, Any]:
    """Persist one candidate zone and derive enter/stay/leave events."""
    review_dir = Path(review_dir).resolve()
    tracking = load_tracking(review_dir)
    if not tracking:
        raise TrackingError("尚无轨迹证据，请先完成视频识别")
    if (not isinstance(polygon, list) or len(polygon) < 4
            or any(not isinstance(point, list) or len(point) != 2 for point in polygon)):
        raise TrackingError("候选区域至少需要四个坐标点")
    dimensions = next((frame.get("frame_dimensions_wh") for frame in tracking["frames"]
                       if isinstance(frame.get("frame_dimensions_wh"), list)), None)
    if any(float(x) < 0 or float(y) < 0 for x, y in polygon):
        raise TrackingError("候选区域坐标不能为负数")
    if dimensions and any(float(x) > dimensions[0] or float(y) > dimensions[1] for x, y in polygon):
        raise TrackingError("候选区域坐标超出本次检测画面范围")
    zone = {"id": "zone-01", "name": str(name)[:80] or "候选区域",
            "polygon_xy": [[round(float(x), 3), round(float(y), 3)] for x, y in polygon],
            "created_at": _utc_now(), "coordinate_basis": "detection_frame_pixels",
            "status": "candidate", "stay_seconds": float(stay_seconds)}
    by_track: dict[str, list[tuple[int, dict[str, Any], bool]]] = {}
    for frame in tracking["frames"]:
        timestamp = float(frame["timestamp_seconds"])
        for track in frame.get("tracks", []):
            x1, y1, x2, y2 = track["bbox_xyxy"]
            center = ((x1 + x2) / 2, (y1 + y2) / 2)
            by_track.setdefault(track["track_id"], []).append((frame["frame_position"], {
                "frame_position": frame["frame_position"], "frame_index": frame["frame_index"],
                "timestamp_seconds": timestamp, "input_file": frame["input_file"],
                "track_id": track["track_id"], "bbox_xyxy": track["bbox_xyxy"]}, _inside(center, zone["polygon_xy"])))
    events = []
    for track_id, observations in by_track.items():
        observations.sort(key=lambda item: item[0])
        run: list[dict[str, Any]] = []
        for _, evidence, inside in observations + [(None, None, False)]:
            if inside:
                run.append(evidence)
                continue
            if not run:
                continue
            first, last = run[0], run[-1]
            duration = max(0.0, float(last["timestamp_seconds"]) - float(first["timestamp_seconds"]))
            keyframes = [run[0], run[len(run) // 2], run[-1]]
            unique = []
            seen = set()
            for item in keyframes:
                if item["frame_position"] not in seen:
                    unique.append(item)
                    seen.add(item["frame_position"])
            base = {"zone_id": zone["id"], "track_id": track_id,
                    "start_seconds": first["timestamp_seconds"], "end_seconds": last["timestamp_seconds"],
                    "duration_seconds": round(duration, 3), "evidence": unique,
                    "status": "pending", "review_note": "",
                    "notice": "候选区域事件，不等于违规或真实距离判断。"}
            events.append({"id": f"event-{len(events) + 1:02d}-enter", "type": "zone_enter", **base})
            if duration >= stay_seconds:
                events.append({"id": f"event-{len(events) + 1:02d}-stay", "type": "zone_stay", **base})
            # The first outside observation is the leave evidence if present.
            outside = next((item for _, item, value in observations if item["frame_position"] > last["frame_position"] and not value), None)
            if outside:
                leave = {**base, "end_seconds": outside["timestamp_seconds"],
                         "evidence": unique + [outside]}
                events.append({"id": f"event-{len(events) + 1:02d}-leave", "type": "zone_leave", **leave})
            run = []
    payload = {"schema": ZONES_SCHEMA, "updated_at": _utc_now(), "zones": [zone]}
    _atomic_json(review_dir / "zones.json", payload)
    event_payload = {"schema": EVENTS_SCHEMA, "updated_at": _utc_now(), "zone_id": zone["id"],
                     "events": events, "notice": "事件仅为算法候选，需人工确认。"}
    _atomic_json(review_dir / "events.json", event_payload)
    tracking["zones"] = [zone]
    tracking["events"] = events
    _atomic_json(review_dir / "tracks.json", tracking)
    return {"zone": zone, "events": events}


def tracking_status(review_dir: str | Path) -> dict[str, Any]:
    tracking = load_tracking(review_dir)
    if not tracking:
        return {"ready": False, "track_count": 0, "event_count": 0}
    return {"ready": True, "track_count": len(tracking.get("track_ids", [])),
            "event_count": len(tracking.get("events", [])),
            "backend": tracking.get("provenance", {})}
