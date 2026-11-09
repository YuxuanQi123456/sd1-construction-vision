"""Streamlit view for track IDs and human-reviewed candidate zone events."""
from __future__ import annotations

from pathlib import Path

import streamlit as st

from tracking import TrackingError, load_tracking, save_zone_events, tracking_status


EVENT_LABELS = {"zone_enter": "进入候选区域", "zone_stay": "持续停留候选", "zone_leave": "离开候选区域"}


def _event_rows(events: list[dict]) -> list[dict]:
    return [{
        "事件": EVENT_LABELS.get(item.get("type"), item.get("type", "")),
        "对象": item.get("track_id", ""),
        "开始（秒）": item.get("start_seconds"),
        "结束（秒）": item.get("end_seconds"),
        "持续（秒）": item.get("duration_seconds"),
        "状态": "待人工确认" if item.get("status") == "pending" else item.get("status", ""),
    } for item in events]


def render_tracking_ui(review_dir, result: dict, selected: int, frame: dict, project_root: Path) -> None:
    """Render tracking evidence and one editable rectangular demo zone."""
    del project_root  # reserved for future optional profiles; no external call here
    review_dir = Path(review_dir)
    st.markdown("#### 对象轨迹与候选事件")
    st.caption("轨迹由开源 ByteTrack 适配器基于本次检测框生成；对象 ID 只在本次影像中有效，不代表人员身份。")
    status = tracking_status(review_dir)
    if not status["ready"]:
        st.warning("本次识别没有生成轨迹证据。可以重试识别；原检测结果仍可查看和导出。")
        return
    metrics = st.columns(3)
    metrics[0].metric("轨迹对象", status["track_count"])
    metrics[1].metric("候选事件", status["event_count"])
    metrics[2].metric("跟踪后端", "ByteTrack")
    tracking = load_tracking(review_dir) or {}
    tracking_frame = next((item for item in tracking.get("frames", [])
                           if item.get("frame_position") == selected), None)
    if tracking_frame:
        overlay = review_dir / tracking_frame["track_overlay_file"]
        if overlay.is_file():
            st.image(str(overlay), caption="当前采样画面 · track ID 与轨迹", use_container_width=True)
        rows = []
        for item in tracking_frame.get("tracks", []):
            rows.append({"对象": item["track_id"], "类别": item["class_name"],
                         "分数": item["confidence"], "检测框": item["bbox_xyxy"]})
        if rows:
            st.dataframe(rows, use_container_width=True, hide_index=True)
        else:
            st.info("当前采样画面没有形成可显示的对象轨迹。")

    width, height = frame.get("detection_dimensions_wh", [1, 1])
    with st.expander("生成演示区域进入/停留/离开事件", expanded=not bool(tracking.get("events"))):
        st.caption("区域坐标基于当前保存画面的像素；这是演示候选区域，不代表真实危险区或物理距离。")
        form_key = f"zone-form-{review_dir.name}"
        with st.form(form_key):
            st.write(f"当前画面尺寸：{width}×{height}")
            columns = st.columns(4)
            x1 = columns[0].number_input("左", min_value=0, max_value=max(1, int(width) - 1),
                                         value=max(0, int(width * 0.2)), key=f"zone-x1-{review_dir.name}")
            y1 = columns[1].number_input("上", min_value=0, max_value=max(1, int(height) - 1),
                                         value=max(0, int(height * 0.2)), key=f"zone-y1-{review_dir.name}")
            x2 = columns[2].number_input("右", min_value=1, max_value=max(1, int(width)),
                                         value=max(1, int(width * 0.8)), key=f"zone-x2-{review_dir.name}")
            y2 = columns[3].number_input("下", min_value=1, max_value=max(1, int(height)),
                                         value=max(1, int(height * 0.8)), key=f"zone-y2-{review_dir.name}")
            stay = st.number_input("持续停留阈值（秒）", min_value=0.0, max_value=30.0, value=2.0, step=0.5,
                                   key=f"zone-stay-{review_dir.name}")
            submitted = st.form_submit_button("生成候选区域事件", type="primary")
        if submitted:
            if x2 <= x1 or y2 <= y1:
                st.error("候选区域的右/下坐标必须大于左/上坐标。")
            else:
                try:
                    saved = save_zone_events(review_dir, [[x1, y1], [x2, y1], [x2, y2], [x1, y2]],
                                             stay_seconds=stay)
                    st.success(f"已生成 {len(saved['events'])} 条候选事件，均待人工确认。")
                    st.rerun()
                except TrackingError as exc:
                    st.error(str(exc))
    events = tracking_status(review_dir)
    latest = load_tracking(review_dir) or {}
    if latest.get("events"):
        st.markdown("**候选事件**")
        st.dataframe(_event_rows(latest["events"]), use_container_width=True, hide_index=True)
        st.caption("候选事件只描述本次影像中的像素区域关系，不等于违规、身份或真实距离判断；请结合关键帧人工确认。")
        st.caption("生成候选事件后，再点击下方“生成巡查总结”，AI 会优先参考这些事件关键帧；总结问题仍需人工确认。")
    else:
        st.caption("尚未生成区域事件；轨迹证据已保留。")
    downloads = st.columns(2)
    tracks_path = review_dir / "tracks.json"
    events_path = review_dir / "events.json"
    if tracks_path.is_file():
        downloads[0].download_button("下载轨迹 JSON", tracks_path.read_bytes(),
                                     file_name="visual-tracks.json", mime="application/json",
                                     on_click="ignore", use_container_width=True)
    if events_path.is_file():
        downloads[1].download_button("下载事件 JSON", events_path.read_bytes(),
                                     file_name="visual-events.json", mime="application/json",
                                     on_click="ignore", use_container_width=True)
