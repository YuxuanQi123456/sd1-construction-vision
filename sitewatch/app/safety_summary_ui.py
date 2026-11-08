"""Business-facing safety summary and explicit human review controls."""
from __future__ import annotations

import hashlib
import logging
import math
from pathlib import Path

import streamlit as st

from safety_summary import (
    generate_summary,
    latest_summary_attempt,
    load_summary,
    set_finding_decision,
    summary_backend_status,
    summary_report,
)

LOGGER = logging.getLogger(__name__)
REVIEW_STATUSES = {
    "pending": "待人工确认",
    "confirmed": "已确认问题",
    "dismissed": "已排除",
}


def _key(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:24]


def _frame_label(frame: dict) -> str:
    timestamp = float(frame["timestamp_seconds"])
    if not math.isfinite(timestamp) or timestamp < 0:
        raise ValueError("Invalid evidence timestamp")
    return f"{timestamp:.2f} 秒（帧 {int(frame['frame_index'])}）"


def _evidence_frames(finding: dict, result: dict) -> list[dict]:
    """Use saved detection frames for time and paths, never model text."""
    frames = result["frames"]
    selected = []
    seen = set()
    for evidence in finding.get("evidence", []):
        position = evidence.get("frame_position")
        if (type(position) is not int or not 0 <= position < len(frames)
                or position in seen):
            continue
        frame = frames[position]
        if (evidence.get("input_file") != frame.get("input_file")
                or evidence.get("frame_index") != frame.get("frame_index")
                or evidence.get("timestamp_seconds") != frame.get("timestamp_seconds")):
            continue
        _frame_label(frame)
        selected.append(frame)
        seen.add(position)
    return selected


def _render_finding(review_dir: Path, result: dict, summary: dict,
                    finding: dict, number: int, prefix: str) -> None:
    status = finding.get("review_status", "pending")
    if status not in REVIEW_STATUSES:
        status = "pending"
    finding_key = f"{prefix}-{_key(str(finding['id']))}"
    with st.container(border=True):
        kind = "疑似问题" if status == "pending" else "问题"
        st.markdown(f"##### {kind} {number} · {REVIEW_STATUSES[status]}")
        st.text(finding["title"], width="stretch")
        st.caption("观察依据与不确定性")
        st.text(finding["detail"], width="stretch")
        st.caption("建议人工核查")
        st.text(finding["suggestion"], width="stretch")

        frames = _evidence_frames(finding, result)
        if frames:
            st.caption("依据采样时间：" + "；".join(_frame_label(frame) for frame in frames))
            if st.checkbox("查看依据原图", key=f"{finding_key}-evidence"):
                for frame in frames:
                    path = (review_dir / frame["input_file"]).resolve()
                    if path.is_relative_to(review_dir) and path.is_file():
                        st.image(str(path), caption="未画框依据画面 · " + _frame_label(frame),
                                 width="stretch")
                    else:
                        st.warning("依据原图暂不可用，请检查完整证据中的原始画面。")
        else:
            st.warning("依据画面暂不可用，请查看完整证据中的原始记录。")

        if finding.get("reviewed_at"):
            st.caption("最近人工保存时间：" + str(finding["reviewed_at"]))
        with st.form(f"{finding_key}-form"):
            decision = st.selectbox(
                "人工确认状态", list(REVIEW_STATUSES),
                index=list(REVIEW_STATUSES).index(status),
                format_func=REVIEW_STATUSES.get, key=f"{finding_key}-status",
            )
            note = st.text_area("人工备注（可选，最多 1000 字）",
                                value=finding.get("review_note", ""), max_chars=1000,
                                key=f"{finding_key}-note")
            submitted = st.form_submit_button("保存人工确认", width="stretch")
        if submitted:
            try:
                set_finding_decision(review_dir, summary["summary_id"], finding["id"], decision, note)
            except Exception:
                LOGGER.exception("Could not save safety finding decision")
                st.error("人工确认未保存。总结版本可能已更新，请刷新后核对并重试。")
            else:
                st.session_state[f"{prefix}-saved"] = True
                st.rerun()


def render_safety_summary(review_dir, result, project_root) -> None:
    """Read on reruns; generate and persist decisions only on explicit clicks."""
    review_dir = Path(review_dir).resolve()
    review_key = "safety-summary-" + _key(str(review_dir))
    st.divider()
    st.markdown("#### AI 安全巡查总结")
    st.caption("从本次检测中选取首、中、末最多 3 个代表采样画面，归纳可见情况与疑似问题，供人工确认。")

    summary = None
    attempt = None
    try:
        summary = load_summary(review_dir)
        attempt = latest_summary_attempt(review_dir)
    except Exception:
        LOGGER.exception("Could not read safety summary records")
        st.warning("巡查总结记录暂时无法读取，已有检测结果仍可查看和导出。")
    try:
        ready = bool(summary_backend_status(project_root).get("ready"))
    except Exception:
        LOGGER.exception("Could not read safety summary availability")
        ready = False
    complete = result.get("status") == "complete" and bool(result.get("frames"))
    if not ready:
        st.info("巡查总结暂不可用，请联系演示管理员检查配置。已有检测结果仍可查看和导出。")
    if not complete:
        st.info("请先完成影像检测，再生成巡查总结。")
    generated = False
    failed = False
    label = "重新生成巡查总结" if summary else "生成巡查总结"
    if summary:
        st.caption("重新生成将建立一版新总结，问题重新进入待人工确认；已有版本与人工记录保留在完整证据中。")
    if st.button(label, type="primary", disabled=not (ready and complete),
                 key=f"{review_key}-generate"):
        try:
            with st.spinner("正在分析代表画面并生成巡查总结…"):
                summary = generate_summary(review_dir, project_root)
            generated = True
        except Exception:
            LOGGER.exception("Safety summary generation failed")
            failed = True
        try:
            attempt = latest_summary_attempt(review_dir)
        except Exception:
            LOGGER.exception("Could not read latest safety summary attempt")

    if failed or (attempt and attempt.get("status") == "failed"):
        st.error("最近一次巡查总结生成失败，失败记录已保留。请检查配置或连接后重试。")
        if summary:
            st.warning("当前保留上次成功生成的总结，请核对下方生成时间。")
    elif attempt and attempt.get("status") == "processing":
        st.warning("最近一次巡查总结尚未完成；当前如有总结，仍为上次成功版本。")
    if not summary:
        st.caption("尚无可用的巡查总结。AI 总结仅覆盖实际送入的采样画面，不能代替现场检查。")
        return
    if generated:
        st.success("巡查总结已生成，疑似问题均待人工确认。")

    prefix = f"{review_key}-{_key(str(summary['summary_id']))}"
    if st.session_state.pop(f"{prefix}-saved", False):
        st.success("人工确认已保存。")
    st.caption("总结生成时间：" + str(summary["generated_at"]))
    scope = summary["scope"]
    positions = scope["summary_frame_positions"]
    scope_frames = [result["frames"][position] for position in positions]
    st.caption(f"本次总结分析 {len(positions)} 个代表画面 / 检测共 {scope['detected_frame_count']} 个画面。")
    st.caption("实际分析采样时间：" + "；".join(_frame_label(frame) for frame in scope_frames))
    st.caption("仅依据上述采样画面，不推断未观察区域与视频全程；检测框与分数供参考。")

    st.markdown("##### 整体总结")
    st.text(summary["overview"], width="stretch")
    st.markdown("##### 可见观察")
    for index, observation in enumerate(summary["observations"], 1):
        st.text(f"{index}. {observation}", width="stretch")
    st.markdown("##### 分析限制")
    for index, limitation in enumerate(summary["limitations"], 1):
        st.text(f"{index}. {limitation}", width="stretch")

    findings = summary["findings"]
    counts = {status: sum(item.get("review_status", "pending") == status for item in findings)
              for status in REVIEW_STATUSES}
    for column, status in zip(st.columns(3), REVIEW_STATUSES):
        column.metric(REVIEW_STATUSES[status], counts[status])
    st.caption("仅点击“保存人工确认”后写入；未保存的选择与备注不计入上方统计。")
    if not findings:
        st.info("本次代表画面未形成疑似问题条目；这不代表现场或视频全程安全，请结合分析限制继续人工检查。")
    for number, finding in enumerate(findings, 1):
        _render_finding(review_dir, result, summary, finding, number, prefix)

    try:
        report = summary_report(review_dir)
    except Exception:
        LOGGER.exception("Could not prepare safety summary text export")
        st.warning("巡查总结文本暂时无法导出，请重试或下载完整证据。")
    else:
        st.download_button("下载巡查总结", report, file_name="safety-summary.txt",
                           mime="text/plain; charset=utf-8", on_click="ignore",
                           key=f"{prefix}-download")
    st.caption("完整证据包包含巡查总结、实际分析依据、生成记录和人工确认记录。")
