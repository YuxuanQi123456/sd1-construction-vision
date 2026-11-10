"""Thin Streamlit view for local object crops, evidence navigation and human review."""
import base64
import hashlib
import json
from pathlib import Path

import streamlit as st
import streamlit.components.v1 as components

from object_review import (PARTS, PPE_STATES, TARGET_STATES, crop_target,
                           load_object_reviews, save_object_decision)
from review_evidence import REVIEW_LABELS

_scene = components.declare_component('visual_object_picker', path=str(Path(__file__).resolve().parents[1] / 'reviewer-component'))
CN = {'person': '人员', 'Person': '人员', 'Hardhat': '安全帽', 'hardhat': '安全帽',
      'Safety Vest': '反光衣', 'safety vest': '反光衣'}
EVENT_TITLES = {'zone_enter': '进入区域', 'zone_stay': '持续停留', 'zone_leave': '离开区域'}


def _jump(frame_key, position):
    st.session_state[frame_key] = int(position)


def evidence_index(review_dir, result):
    """Index only frame references that resolve to this review's saved frames."""
    root = Path(review_dir)
    frames = result['frames']
    entries = []
    detection_sha = hashlib.sha256((root / 'detections.json').read_bytes()).hexdigest()
    for filename, field, prefix in [('events.json', 'events', '区域事件')]:
        path = root / filename
        if not path.is_file():
            continue
        payload = json.loads(path.read_text(encoding='utf-8'))
        if payload.get('source_detections_sha256') != detection_sha:
            continue
        for item in payload.get(field, []):
            for ref in item.get('evidence', []):
                pos = ref.get('frame_position')
                if type(pos) is int and 0 <= pos < len(frames) and ref.get('frame_index') == frames[pos]['frame_index'] and ref.get('input_file') == frames[pos]['input_file']:
                    entries.append({'label': f"{prefix} · {item.get('track_id', '')} · {EVENT_TITLES.get(item.get('type'), '候选事件')} · {frames[pos]['timestamp_seconds']:.2f}s", 'frame_position': pos})
    # Summary outputs contain server-resolved evidence references already.
    from safety_summary import load_summary
    summary = load_summary(root)
    success = root / 'safety-summary/latest-success.json'
    if summary and (not success.is_file() or json.loads(success.read_text()).get('detections_sha256') != detection_sha):
        summary = None
    for finding in (summary or {}).get('findings', []):
        for ref in finding.get('evidence', []):
            pos = ref.get('frame_position')
            if type(pos) is int and 0 <= pos < len(frames) and ref.get('frame_index') == frames[pos]['frame_index'] and ref.get('input_file') == frames[pos]['input_file']:
                entries.append({'label': f"巡查疑点 · {finding.get('title', '')} · {frames[pos]['timestamp_seconds']:.2f}s", 'frame_position': pos})
    return entries


def render_evidence_navigation(review_dir, result, frame_key):
    name = Path(review_dir).name
    current = min(len(result['frames']) - 1, max(0, int(st.session_state.get(frame_key, 0))))
    previous, following, text = st.columns([1, 1, 3])
    previous.button('上一采样画面', key='sample-prev-' + name, disabled=current == 0,
                    on_click=_jump, args=(frame_key, current - 1))
    following.button('下一采样画面', key='sample-next-' + name, disabled=current == len(result['frames']) - 1,
                     on_click=_jump, args=(frame_key, current + 1))
    text.caption('点击疑点或区域事件，可跳转到其依据画面；时间基于本次视频采样。')
    try:
        entries = evidence_index(review_dir, result)
    except (OSError, ValueError, TypeError, KeyError):
        st.warning('部分疑点索引暂不可用，采样画面仍可逐张查看。')
        entries = []
    if entries:
        choice = st.selectbox('疑点与事件关键帧', range(len(entries)), format_func=lambda i: entries[i]['label'], key='evidence-choice-' + name)
        st.button('定位这条证据', key='evidence-go-' + name, on_click=_jump, args=(frame_key, entries[choice]['frame_position']))
    else:
        st.caption('暂无疑点或区域事件；下方可直接选采样时间并复核人员。')


def render_object_review(review_dir, result, frame_position, *, show_all=False):
    root = Path(review_dir)
    frame = result['frames'][frame_position]
    prefix = f'object-{root.name}-{frame_position}'
    input_path = root / frame['input_file']
    digest = hashlib.sha256(input_path.read_bytes()).hexdigest()
    token = prefix + '-' + digest[:12]
    choices = [i for i, d in enumerate(frame['detections']) if show_all or d['class_name'] in REVIEW_LABELS]
    default = next((i for i in choices if frame['detections'][i].get('canonical_class') == 'person' or frame['detections'][i]['class_name'] in {'person', 'Person'}), choices[0] if choices else -1)
    select_key = prefix + '-selected'
    st.session_state.setdefault(select_key, default)
    action = st.session_state.get(prefix + '-picker')
    if isinstance(action, dict) and action.get('token') == token and action.get('nonce') != st.session_state.get(prefix + '-nonce'):
        if action.get('kind') == 'detection' and action.get('index') in choices:
            st.session_state[select_key] = action['index']
        elif action.get('kind') == 'manual' and isinstance(action.get('bbox'), list) and len(action['bbox']) == 4:
            st.session_state[select_key] = -1
            st.session_state[prefix + '-manual'] = action['bbox']
        st.session_state[prefix + '-nonce'] = action.get('nonce')
    st.markdown('<span id="current-frame-review"></span>', unsafe_allow_html=True)
    st.markdown('#### 原图局部复核')
    left, right = st.columns([2, 1], gap='medium')
    with left:
        scene_boxes = [{'index': i, 'bbox': d.get('bbox_xyxy', d['bbox']), 'label': CN.get(d['class_name'], d['class_name'])}
                       for i, d in enumerate(frame['detections']) if i in choices]
        mime = 'image/png' if input_path.suffix == '.png' else 'image/jpeg'
        _scene(image=f'data:{mime};base64,' + base64.b64encode(input_path.read_bytes()).decode(),
                        boxes=scene_boxes, selected=st.session_state[select_key], token=token,
                        key=prefix + '-picker', default=None)
        with st.expander('检测对象列表（也可直接点左侧框）'):
            st.selectbox('选择复核对象', [-1, *choices], key=select_key,
                         format_func=lambda i: '手动框选区域' if i == -1 else f"框 {i + 1} · {CN.get(frame['detections'][i]['class_name'], frame['detections'][i]['class_name'])}")
        st.caption(f"依据：{frame['timestamp_seconds']:.2f}s · 源帧 {frame['frame_index']}；右侧裁图来自未画框原始影像。")
    selected = st.session_state[select_key]
    with right:
        part = st.selectbox('查看局部', list(PARTS), format_func=PARTS.get, key=prefix + '-part')
        try:
            raw, evidence = crop_target(root, frame_position, selected if selected >= 0 else None,
                                         st.session_state.get(prefix + '-manual'), part)
        except (OSError, ValueError, KeyError, TypeError) as exc:
            st.info(str(exc))
            return
        width, height = evidence['crop_dimensions_wh']
        zoom = st.slider('局部放大倍数', 1, 12, 4, key=prefix + '-zoom')
        # CSS enlarges original pixels for inspection without manufacturing detail.
        display_width = max(180, min(2400, width * zoom))
        encoded = base64.b64encode(raw).decode()
        components.html(f'<div style="height:285px;overflow:auto;background:#101b2c;border-radius:8px"><img alt="未画框原图局部" src="data:image/png;base64,{encoded}" style="width:{display_width}px;max-width:none;image-rendering:pixelated"></div>', height=295)
        st.caption(f'原始裁图 {width}×{height} 像素；放大不增加原片细节。')
        if part != 'whole':
            st.caption('头部/上身按人员框位置截取，仅供定位；不表示已识别出帽子或反光衣。')
        st.download_button('下载未画框局部原图', raw, file_name=f"visual-crop-{frame['frame_index']}-{evidence['target_id']}.png", mime='image/png', key=prefix + '-crop-download', on_click='ignore')
        decision = load_object_reviews(root)['decisions'].get(evidence['target_id'], {})
        form_key = prefix + '-' + evidence['target_id']
        with st.form(form_key):
            st.caption('以下为人工意见，独立于模型原结果。')
            state = st.selectbox('目标复核', list(TARGET_STATES), index=list(TARGET_STATES).index(decision.get('target_state', 'pending')), format_func=TARGET_STATES.get)
            helmet = st.selectbox('人工查看安全帽', list(PPE_STATES), index=list(PPE_STATES).index(decision.get('helmet_state', 'pending')), format_func=PPE_STATES.get)
            vest = st.selectbox('人工查看反光衣', list(PPE_STATES), index=list(PPE_STATES).index(decision.get('vest_state', 'pending')), format_func=PPE_STATES.get)
            note = st.text_area('复核备注', value=decision.get('note', ''), max_chars=1000)
            submitted = st.form_submit_button('保存此对象人工复核')
        if submitted:
            try:
                save_object_decision(root, evidence, target_state=state, helmet_state=helmet, vest_state=vest, note=note)
            except Exception:
                st.error('人工意见未保存，请重新选择对象后再保存。')
            else:
                st.success('此对象人工复核已保存，原模型结果保持。')
