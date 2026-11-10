"""SiteWatch — Streamlit entry point."""
from __future__ import annotations

import csv
import base64
import logging
import hashlib
import json
import os
import time
from pathlib import Path

import cv2
import numpy as np
import streamlit as st

from cv_pipeline.detection import Detector
from cv_pipeline.enhancement import enhance
from cv_pipeline.fusion import LOG_PATH, fuse
from cv_pipeline.motion import MotionDetector
from review_evidence import NOTICE, REVIEW_LABELS, evidence_zip, new_review_dir, review_file
from region_review import backend_status, head_indices, latest_region_review, review_head_region
from safety_summary_ui import render_safety_summary
from safety_summary import summary_export_lock
from tracking import TrackingError, augment_tracking
from tracking_ui import render_tracking_ui
from utils.drawing import draw_overlay

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")

st.set_page_config(page_title="水电一局 · 施工视觉AI", page_icon="🏗️", layout="wide")
RUNTIME = Path(os.environ["SITEWATCH_RUNTIME_DIR"])
RUNTIME.mkdir(parents=True, exist_ok=True)
PROJECT_ROOT = Path(os.environ.get("SITEWATCH_PROJECT_ROOT", Path(__file__).resolve().parents[2]))
BRAND_DIR = PROJECT_ROOT / "sitewatch/branding"
brand_logo = "data:image/png;base64," + base64.b64encode((BRAND_DIR / "logo.png").read_bytes()).decode("ascii")
st.markdown("<style>" + (BRAND_DIR / "theme.css").read_text() + "</style>", unsafe_allow_html=True)
st.markdown(f'''<div class="sd1-masthead">
  <div class="sd1-identity">
    <img class="sd1-logo" src="{brand_logo}" alt="中国电建 · 中国水利水电第一工程局有限公司">
    <div class="sd1-title"><h1>施工视觉AI</h1><p>水电一局 · 工程现场影像复核</p></div>
  </div><span class="sd1-demo">演示环境</span>
</div>
<div class="sd1-hero"><div class="sd1-eyebrow">安全生产 / 视觉智能</div>
  <h2>施工现场安全监测</h2><p>识别人员与防护装备，生成对象轨迹和候选区域事件，留存现场安全检查依据。</p>
</div>
<div class="sd1-steps">
  <div class="sd1-step"><b>01</b><div><strong>导入现场影像</strong><span>选择高清样例或上传照片、视频</span></div></div>
  <div class="sd1-step"><b>02</b><div><strong>AI 识别与定位</strong><span>查看人员、安全帽与防护装备</span></div></div>
  <div class="sd1-step"><b>03</b><div><strong>轨迹事件与人工留证</strong><span>核对候选事件，导出影像与记录</span></div></div>
</div>''', unsafe_allow_html=True)
MODEL_LABELS = {"sitewatch": "施工场景识别",
                "constructelligence-v03": "近景防护识别",
                "client-person-demo": "甲方人员适配（仅人员）"}


def demo_media_entries() -> list[dict]:
    """Read local attribution separately from the detector's image input."""
    manifest = json.loads((PROJECT_ROOT / 'sitewatch/demo-media.json').read_text())
    if manifest.get('schema') != 'demo-media-v1':
        raise ValueError('Unsupported demo media manifest')
    entries = manifest['entries']
    if len({item['id'] for item in entries}) != len(entries):
        raise ValueError('Duplicate demo media identifiers')
    return entries


def checked_demo_media(entry: dict) -> tuple[Path, bytes]:
    path = (PROJECT_ROOT / entry['relative_path']).resolve()
    if not path.is_relative_to(PROJECT_ROOT.resolve()) or not path.is_file():
        raise ValueError('演示素材文件不可用')
    data = path.read_bytes()
    if len(data) != entry['bytes'] or hashlib.sha256(data).hexdigest() != entry['sha256']:
        raise ValueError('演示素材与登记原件不一致')
    return path, data


def media_mime(path: Path) -> str:
    return {'.png': 'image/png', '.jpg': 'image/jpeg', '.jpeg': 'image/jpeg',
            '.mp4': 'video/mp4', '.webm': 'video/webm', '.mov': 'video/quicktime',
            '.avi': 'video/x-msvideo'}.get(path.suffix.lower(), 'application/octet-stream')


# ----- cached singletons ----------------------------------------------------
@st.cache_resource(show_spinner="正在加载视觉识别模型…", max_entries=2)
def get_detector(conf_threshold: float, model_id: str, profile: str) -> Detector:
    return Detector(conf_threshold=conf_threshold, model_id=model_id, profile=profile)


# ----- pipeline -------------------------------------------------------------
def process_frame(
    frame: np.ndarray,
    detector: Detector,
    motion: MotionDetector,
    *,
    do_enhance: bool,
    do_motion: bool,
    do_dedup: bool = True,
) -> tuple[np.ndarray, list, list, list]:
    img = enhance(frame) if do_enhance else frame
    dets = detector.detect(img)
    if do_motion:
        hazards = [d.bbox for d in dets if d.category == "hazard"]
        regions = motion.update(img, hazards)
        persons = [d.bbox for d in dets if d.category == "worker"]
        proximity = motion.check_proximity(persons, regions)
    else:
        regions, proximity = [], []
    anns = fuse(dets, regions, proximity, dedup=do_dedup)
    overlay = draw_overlay(img, dets, regions, anns, proximity)
    return overlay, dets, anns, proximity


def _resize_long_edge(frame: np.ndarray, max_long: int = 1280) -> np.ndarray:
    h, w = frame.shape[:2]
    long = max(h, w)
    if long <= max_long:
        return frame
    scale = max_long / long
    return cv2.resize(frame, (int(w * scale), int(h * scale)))


# ----- sidebar --------------------------------------------------------------
st.sidebar.markdown(f'''<div class="sd1-sidebar"><img src="{brand_logo}" alt="水电一局标识">
<strong>施工视觉AI</strong><span>影像识别 · 区域复核 · 证据留存</span></div>''', unsafe_allow_html=True)
st.sidebar.markdown("### 素材与识别配置")
source_choice = st.sidebar.radio('素材来源', ['清晰演示素材', '自己上传'], key='review-source')
demo_entry = None
demo_error = None
if source_choice == '清晰演示素材':
    try:
        entries = demo_media_entries()
        titles = {item['id']: item['title'] for item in entries}
        demo_id = st.sidebar.selectbox('选择演示素材', list(titles), format_func=titles.get, key='review-demo-id')
        demo_entry = next(item for item in entries if item['id'] == demo_id)
    except (OSError, ValueError, KeyError, TypeError, StopIteration):
        demo_error = '演示素材暂不可用，可以切换到“自己上传”。'
        st.sidebar.warning(demo_error)
model_choice = st.sidebar.selectbox(
    "检测模型", ['auto', *MODEL_LABELS],
    format_func=lambda value: '自动（按素材推荐）' if value == 'auto' else MODEL_LABELS[value],
    key='review-model')
automatic_model = demo_entry.get('recommended_model_id', 'sitewatch') if demo_entry else 'sitewatch'
if automatic_model not in MODEL_LABELS:
    automatic_model = 'sitewatch'
model_id = automatic_model if model_choice == 'auto' else model_choice
profile_choice = st.sidebar.selectbox("演示预设", ['auto', 'standard', 'distant'],
    format_func=lambda value: {'auto': '自动（按素材与场景）',
                              'standard': '照片/近景（标准）', 'distant': '远景视频（补充人员与小目标）'}[value])
pending_upload = st.session_state.get('review-media') if source_choice == '自己上传' else None
is_uploaded_video = pending_upload is not None and Path(pending_upload.name).suffix.lower() not in {'.jpg', '.jpeg', '.png'}
automatic_profile = (demo_entry.get('recommended_profile', 'standard') if demo_entry else
                     'distant' if is_uploaded_video else 'standard')
profile = automatic_profile if profile_choice == 'auto' else profile_choice
st.sidebar.caption(f'本次检测模型：{MODEL_LABELS[model_id]}。' +
                   ('已按所选素材推荐解析。' if model_choice == 'auto' and demo_entry else
                    '已自动采用施工场景识别方案。' if model_choice == 'auto' else '已手动指定。'))
preserve_resolution = st.sidebar.checkbox('保留原片画质（较慢）', value=True, key='preserve-resolution')
with st.sidebar.expander("高级识别设置", expanded=False):
    enhancement_requested = st.toggle("图像增强", value=False, disabled=preserve_resolution)
    recommended_confidence = float(demo_entry.get('recommended_confidence_threshold', 0.4)) if demo_entry else 0.4
    recommended_confidence = min(0.8, max(0.2, recommended_confidence))
    conf_threshold = st.slider("检测置信度阈值", 0.2, 0.8, recommended_confidence, 0.05,
                               key=f"conf-threshold-{demo_entry['id'] if demo_entry else 'upload'}")
    st.caption('分数表示模型对当前检测框的判断强度，不代表准确率；调高阈值会减少显示框，也可能漏掉目标。')
    st.caption('固定样例采用实测配置；清晰素材按推荐场景运行，上传视频默认远景。')
    if demo_entry and demo_entry.get('client_media'):
        st.caption(f"甲方视频演示配置：远景输入 {demo_entry.get('recommended_confidence_threshold', 0.4):.2f} 阈值；按固定素材适配，不代表通用现场精度。")
    if profile == 'distant':
        st.caption('远景配置：防护装备1280输入，通用人员640输入；速度较慢。')
    if model_id != "sitewatch":
        st.caption('对照模型可能改善部分检出，仍有误报；当前是演示配置。')
do_enhance = enhancement_requested and not preserve_resolution
if preserve_resolution:
    st.sidebar.caption('原尺寸无损保存，可下载原图与检测框图。')
do_motion = False
proximity_px = 80

def render_violation_log() -> None:
    """Render the recent-violations table in the sidebar.

    Called at the *end* of the script so it reflects anything logged during this
    run (e.g. a freshly uploaded image), rather than the pre-processing state.
    """
    with st.sidebar.expander("上游规则记录（当前未启用）", expanded=False):
        rows: list[list[str]] = []
        header: list[str] | None = None
        if LOG_PATH.exists():
            with LOG_PATH.open("r", encoding="utf-8") as f:
                reader = csv.reader(f)
                header = next(reader, None)
                for row in reader:
                    rows.append(row)
        rows = rows[-20:][::-1]
        if rows:
            st.dataframe(
                {h: [r[i] for r in rows] for i, h in enumerate(header or [])},
                use_container_width=True,
                height=300,
            )
        else:
            st.caption("离线复核不运行距离、运动或形状安全规则。")


# ----- shared resources ----------------------------------------------------
try:
    detector = get_detector(conf_threshold, model_id, profile)
except Exception:
    logging.exception("Visual detection model failed to load")
    st.error("视觉识别暂不可用，请联系演示管理员检查运行资源。")
    st.stop()

with st.sidebar.expander("模型来源与许可", expanded=False):
    st.markdown("[SiteWatch / Hani Moustafa](https://github.com/AitchEm-bot/sitewatch) · 源代码 MIT · YOLO 与权重 AGPL-3.0")
    st.markdown(f"当前检测模型：[ {MODEL_LABELS[model_id]} ]({detector.provenance['repository']}) · {detector.provenance['weight_license']}")
    st.caption(f"固定版本 {detector.provenance['commit']}；{len(detector.names)} 类；CPU 推理")
    st.caption('这里的类别数是目标标签数；本演示重点展示人员、安全帽、反光背心及未佩戴候选。')
    st.code(detector.model_sha256, language=None)
    st.json(detector.names)
    if detector.person_spec:
        st.caption('补充人员：Ultralytics官方YOLOv8n，640输入，只输出person；独立来源，不输出安全帽类别。')
        st.json(detector.provenance['person_companion'])

st.sidebar.markdown("### 视频分析范围")
recommended_sample_seconds = float(demo_entry.get('recommended_sample_seconds', 1.0)) if demo_entry else 1.0
recommended_sample_seconds = recommended_sample_seconds if recommended_sample_seconds in {0.5, 1.0, 2.0} else 1.0
sample_seconds = st.sidebar.select_slider("视频采样间隔（秒）", options=[0.5, 1.0, 2.0], value=recommended_sample_seconds)
recommended_max_seconds = int(demo_entry.get('recommended_max_seconds', 8)) if demo_entry else 8
recommended_max_seconds = min(30, max(1, recommended_max_seconds))
max_seconds = st.sidebar.slider("视频复核起始时长（秒）", 1, 30, recommended_max_seconds,
                                key=f"max-seconds-{demo_entry['id'] if demo_entry else 'upload'}")
st.sidebar.caption("仅分析指定范围内的采样画面。")



# ----- tabs ----------------------------------------------------------------
tab_review, tab_live = st.tabs(["影像识别与复核", "摄像头接入说明"])


with tab_live:
    if os.environ.get("SITEWATCH_ENABLE_LIVE") != "1":
        st.info("当前演示支持照片与视频文件复核，尚未接入现场摄像头。请在“影像识别与复核”中选择素材。")
    else:
        st.markdown("### 摄像头实时画面")
        st.caption("连接摄像头前，请在浏览器中允许相机访问。")

        try:
            from streamlit_webrtc import VideoProcessorBase, webrtc_streamer
            import av  # noqa: F401  (ensures the runtime is available)
        except Exception:  # noqa: BLE001
            logging.exception("Camera component unavailable")
            st.error("摄像头组件未安装，当前无法启用实时画面。")
        else:

            class SiteWatchProcessor(VideoProcessorBase):
                def __init__(self) -> None:
                    self.motion = MotionDetector(proximity_threshold=proximity_px)
                    self.last_anns: list = []
                    self._times: list[float] = []
                    self._frame_idx = 0
                    self._skip_alt = False

                def recv(self, frame):
                    import av

                    self._frame_idx += 1
                    # Adaptive frame skipping when FPS is poor.
                    if self._skip_alt and self._frame_idx % 2 == 0:
                        return frame

                    t0 = time.perf_counter()
                    img = frame.to_ndarray(format="bgr24")
                    # Standardise live size for performance.
                    if img.shape[1] > 640:
                        img = cv2.resize(img, (640, 480))

                    overlay, _dets, anns, _prox = process_frame(
                        img,
                        detector,
                        self.motion,
                        do_enhance=do_enhance,
                        do_motion=do_motion,
                    )
                    self.last_anns = anns

                    dt_s = time.perf_counter() - t0
                    self._times.append(dt_s)
                    if len(self._times) > 30:
                        self._times.pop(0)
                    avg = sum(self._times) / len(self._times)
                    fps = 1.0 / avg if avg > 0 else 0.0
                    self._skip_alt = fps < 10.0
                    cv2.putText(
                        overlay,
                        f"FPS {fps:.1f}",
                        (8, 22),
                        cv2.FONT_HERSHEY_SIMPLEX,
                        0.7,
                        (255, 255, 255),
                        2,
                        cv2.LINE_AA,
                    )
                    return av.VideoFrame.from_ndarray(overlay, format="bgr24")

            ctx = webrtc_streamer(
                key="sitewatch-live",
                video_processor_factory=SiteWatchProcessor,
                media_stream_constraints={"video": True, "audio": False},
                async_processing=True,
            )

            if ctx and ctx.video_processor and ctx.state.playing:
                st.markdown("**最近提示**")
                anns = ctx.video_processor.last_anns or []
                if anns:
                    st.write(
                        [{"priority": a.priority, "text": a.text} for a in anns[:5]]
                    )
                else:
                    st.caption("当前没有生成提示。")


with tab_review:
    st.markdown("### 影像识别与复核")
    st.caption("先选素材并开始识别，再查看检测框、复核局部区域，最后导出证据。")
    show_all = st.checkbox(f"显示全部{len(detector.names)}类目标标签（含设备与车辆）", value=False,
                           key=f"show-all-{model_id}")
    st.caption('当前识别场景：' + ('远景视频 · 人员与防护装备' if profile == 'distant' else '照片 / 近景 · 人员与防护装备'))
    display_mode = st.radio('画面显示', ['大图看检测结果', '左右对照'], horizontal=True, key='review-display')
    upload = None
    if source_choice == '自己上传':
        upload = st.file_uploader(
            "上传施工照片或视频",
            type=["jpg", "jpeg", "png", "mp4", "avi", "mov", "webm"],
            key='review-media',
        )
    contents = None
    media_name = None
    tmp_path = None
    if demo_entry is not None and demo_error is None:
        try:
            tmp_path, contents = checked_demo_media(demo_entry)
            media_name = tmp_path.name
            st.caption(f"演示素材：{demo_entry['title']}")
            st.caption('甲方提供的本地内部演示素材。' if demo_entry.get('client_media') else '公开演示素材，非水电一局现场。')
            with st.expander('素材来源与使用说明', expanded=False):
                source_label = (f"[来源]({demo_entry['source']})" if demo_entry.get('source', '').startswith('http')
                                else f"来源：{demo_entry.get('source', '未登记')}")
                license_label = (f"[{demo_entry['license']}]({demo_entry['license_url']})"
                                 if demo_entry.get('license_url') else demo_entry.get('license', '许可信息未登记'))
                st.markdown(f"作者：{demo_entry['author']} · {source_label} · {license_label}")
                st.caption(demo_entry.get('description', '公开演示素材，非水电一局现场。'))
        except (OSError, ValueError, KeyError, TypeError):
            st.session_state.pop('review', None)
            st.error('演示素材校验失败，请选择其它素材或切换到自己上传。')
    elif source_choice == '自己上传' and upload is not None:
        contents = upload.getvalue()
        media_name = Path(upload.name).name
    if contents is not None and media_name is not None:
        digest = hashlib.sha256(contents).hexdigest()
        if tmp_path is None:
            upload_dir = RUNTIME / "uploads" / digest
            upload_dir.mkdir(parents=True, exist_ok=True)
            tmp_path = upload_dir / media_name
            tmp_path.write_bytes(contents)
        source_id = demo_entry['id'] if demo_entry is not None else 'upload'
        signature = (digest, source_choice, source_id, model_choice, model_id, profile_choice, profile, preserve_resolution,
                     conf_threshold, do_enhance, sample_seconds, max_seconds)
        saved = st.session_state.get("review")
        if saved and saved[0] != signature:
            st.session_state.pop("review", None)
        st.caption(f"当前影像：{media_name}")
        if st.button("开始识别与复核", type="primary", key=f"run-review-{digest}-{model_id}"):
            destination = new_review_dir(RUNTIME)
            placeholder = st.empty()
            status = st.empty()
            def update(overlay, frame):
                placeholder.image(str(destination / frame["overlay_file" if show_all else "review_overlay_file"]), use_container_width=True)
                status.caption(f"已识别 {frame['timestamp_seconds']:.2f} 秒画面；{len(frame['detections'])} 个检测框")
            try:
                with st.spinner("正在识别人员与防护装备，请稍候…"):
                    result = review_file(tmp_path, detector, destination,
                                         do_enhance=do_enhance, sample_seconds=sample_seconds,
                                         max_seconds=max_seconds, callback=update,
                                         preserve_resolution=preserve_resolution)
                if result["media_type"] == "video":
                    try:
                        result["tracking"] = augment_tracking(destination, result, sample_seconds=sample_seconds)
                    except TrackingError as exc:
                        logging.exception("ByteTrack evidence generation failed")
                        result["tracking_error"] = str(exc)
                st.session_state["review"] = (signature, str(destination), result)
            except Exception:
                logging.exception("Visual footage processing failed")
                st.session_state.pop("review", None)
                st.error("复核失败：影像处理未完成，请重试或联系管理员。已完成的原始证据保存在本机复核目录。")
            placeholder.empty()
            status.empty()
        saved = st.session_state.get("review")
        if saved and saved[0] == signature:
            _, destination, result = saved
            destination = Path(destination)
            st.success(f"识别完成：{len(result['frames'])} 个画面；待人工复核框 {result['manual_review_detection_count']} 次。")
            summary = st.columns(3)
            summary[0].metric("已分析画面", f"{len(result['frames'])} 帧")
            summary[1].metric("待人工复核框", f"{result['manual_review_detection_count']} 次")
            summary[2].metric("处理耗时", f"{result['elapsed_seconds']:.1f} 秒")
            st.caption('统计来自本次实际结果；待复核框按NO-*类别计次，非人员去重统计。')
            if result["media_type"] == "video":
                st.caption("仅复核下列采样时间：" + ", ".join(f"{f['timestamp_seconds']:.2f}s" for f in result["frames"]))
            selected = st.selectbox("查看采样画面", range(len(result["frames"])),
                                    format_func=lambda i: f"{result['frames'][i]['timestamp_seconds']:.2f}s / frame {result['frames'][i]['frame_index']}",
                                    key=f"frame-{destination.name}")
            frame = result["frames"][selected]
            input_path = destination / frame['input_file']
            shown_path = destination / frame["overlay_file" if show_all else "review_overlay_file"]
            source_width, source_height = frame['source_dimensions_wh']
            image_width, image_height = frame['detection_dimensions_wh']
            st.caption(f'原片画面 {source_width}×{source_height}；本次保存画面 {image_width}×{image_height}。页面按屏幕缩放显示。')
            if display_mode == '左右对照':
                left, right = st.columns(2)
                left.image(str(input_path), caption='本次输入画面', use_container_width=True)
                right.image(str(shown_path), caption=f'{MODEL_LABELS[model_id]} · 检测结果', use_container_width=True)
            else:
                st.image(str(shown_path), caption=f'{MODEL_LABELS[model_id]} · 大图检测结果', use_container_width=True)
                with st.expander('查看本次输入原图', expanded=False):
                    st.image(str(input_path), caption='本次输入画面', use_container_width=True)
            downloads = st.columns(3)
            downloads[0].download_button('下载当前输入原图', input_path.read_bytes(), file_name=input_path.name,
                                        mime=media_mime(input_path), on_click='ignore', use_container_width=True)
            downloads[1].download_button('下载当前检测框图', shown_path.read_bytes(), file_name=shown_path.name,
                                        mime=media_mime(shown_path), on_click='ignore', use_container_width=True)
            source_path = destination / result['source_file']
            downloads[2].download_button('下载原始影像', source_path.read_bytes(), file_name=Path(result['source_name']).name,
                                        mime=media_mime(source_path), on_click='ignore', use_container_width=True)
            with st.expander("查看检测明细与原始分数", expanded=False):
                st.dataframe([{"类别": d["class_name"], "检测分数": d["confidence"],
                               "检测框坐标": d["bbox_xyxy"],
                               "识别方案": MODEL_LABELS.get(d["source"], "人员补充识别")}
                              for d in frame["detections"] if show_all or d["class_name"] in REVIEW_LABELS], use_container_width=True)
                st.caption(NOTICE)
            render_tracking_ui(destination, result, selected, frame, PROJECT_ROOT)
            st.markdown("#### 智能视觉复核")
            st.caption("对所选头部进行辅助复核，结合原图查看防护装备佩戴情况。")
            heads = head_indices(frame)
            if not heads:
                st.info("当前帧未检出可复核的头部框，不能据此判断是否戴帽。")
            else:
                detection_index = st.selectbox("选择头部检测框", heads,
                    format_func=lambda i: f"框 {i + 1} · {frame['detections'][i]['class_name']} · {frame['detections'][i]['confidence']:.3f}",
                    key=f"head-{destination.name}-{selected}")
                detection = frame["detections"][detection_index]
                available = backend_status(PROJECT_ROOT)
                if not available["ready"]:
                    st.info("智能复核暂不可用，已有检测结果仍可查看和导出。请联系演示管理员检查配置。")
                else:
                    st.caption("智能复核已配置，点击后分析当前所选头部画面。")
                if st.button("复核所选头部", disabled=not available["ready"],
                             key=f"review-head-{destination.name}-{selected}-{detection_index}"):
                    try:
                        with st.spinner("正在复核所选头部…"):
                            review_head_region(destination, selected, detection_index, PROJECT_ROOT)
                    except Exception:
                        st.error("区域复核失败；原检测结果与失败记录已保留，请检查复核配置或连接后重试。")
                opinion = latest_region_review(destination, selected, detection_index)
                if opinion and opinion["status"] == "complete":
                    st.image(str(destination / opinion["crop_file"]), caption="本次复核的未画框裁剪图", width=320)
                    st.write(f"检测器原结论：{detection['class_name']}；原检测分数 {detection['confidence']:.3f}")
                    st.write("智能复核意见：" + opinion["opinion"]["label"])
                    st.caption("复核方式：头部区域智能识别 · 结果供人工核对。")
                    if opinion["comparison"] == "disagree":
                        st.warning("复核意见与检测结果存在差异，请结合原图确认。")
                    elif opinion["comparison"] == "uncertain":
                        st.info("区域意见尚不能确认，请查看原图和原始回答。")
                    else:
                        st.caption("复核意见与检测结果一致，请结合现场情况核对。")
                    with st.expander("查看复核记录", expanded=False):
                        st.text(opinion["opinion"]["raw_answer"])
                        st.caption(f"复核时间 {opinion['at']}；源帧 {opinion['frame_index']} / {opinion['timestamp_seconds']:.2f}s")
                        st.code(opinion["crop_sha256"], language=None)
                elif opinion and opinion["status"] == "failed":
                    st.error("该区域上次复核未完成，没有生成替代结论；失败证据已保留，可重试。")
            render_safety_summary(destination, result, PROJECT_ROOT)
            st.download_button("下载原始检测 JSON", (destination / "detections.json").read_bytes(),
                               file_name="visual-detections.json", mime="application/json", on_click="ignore")
            try:
                with summary_export_lock(destination):
                    package_bytes = evidence_zip(destination).read_bytes()
            except Exception:
                logging.exception("Could not prepare complete visual evidence")
                st.warning("完整证据包暂不可用，请稍后重试。原始检测和巡查总结仍可单独下载。")
            else:
                st.download_button("下载完整证据（原文件 / 检测框 / JSON）", package_bytes,
                                   file_name="visual-evidence.zip", mime="application/zip", on_click="ignore")
        elif tmp_path.suffix.lower() in {".jpg", ".jpeg", ".png"}:
            preview = cv2.imread(str(tmp_path))
            if preview is None:
                st.error("无法解码上传图片，请更换文件。")
            else:
                st.image(str(tmp_path), caption="原片预览 · 点击“开始识别与复核”查看AI检测结果", use_container_width=True)
        else:
            st.video(str(tmp_path))
    else:
        st.session_state.pop("review", None)
        st.markdown('''<div class="sd1-empty"><strong>从一张现场照片开始</strong>
<p>在上方上传施工照片或视频，即可识别人员与防护装备。<br>也可在左侧选择“清晰演示素材”，直接体验完整复核流程。</p></div>''', unsafe_allow_html=True)

st.markdown('''<div class="sd1-footer">水电一局 · 施工视觉AI演示<br>
AI 检测用于辅助人工复核，识别框不等于违规结论；仅分析已列出的采样画面。<br>
技术信息与开源组件许可见侧栏“模型来源与许可”。</div>''', unsafe_allow_html=True)


# Render the sidebar violation log last, so it includes anything logged during
# this run (e.g. a just-uploaded image) instead of only the pre-processing state.
if os.environ.get("SITEWATCH_ENABLE_LIVE") == "1":
    render_violation_log()
