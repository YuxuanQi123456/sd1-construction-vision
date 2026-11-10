"""Explicit local replay generation; no remote model calls."""
from pathlib import Path
import logging
import streamlit as st

from video_replay import build_video_replay, existing_replay


def render_video_replay(review_dir, result, detector):
    if result.get('media_type') != 'video':
        return
    root = Path(review_dir)
    with st.expander('连续叠框视频回放', expanded=False):
        st.caption('逐帧使用本次本地模型生成可播放MP4。首次生成需要等待；播放、放大和人工保存均不调用外部模型。')
        replay = None
        try:
            replay = existing_replay(root)
            if st.button('生成连续叠框回放' if replay is None else '检查已有连续回放', key='video-replay-' + root.name):
                bar = st.progress(0., text='开始本地逐帧推理…')
                def update(done, total):
                    bar.progress(done / total, text=f'逐帧推理 {done}/{total} 帧')
                try:
                    replay = build_video_replay(root, detector, progress=update)
                finally:
                    bar.empty()
        except Exception:
            logging.getLogger(__name__).exception('Continuous replay generation failed')
            st.error('连续回放尚未生成成功，已有采样检测仍可查看。请重试，或重新识别后建立新任务。')
        if replay:
            st.video(str(root / replay['video_file']))
            st.caption(f"已分析回放：{replay['decoded_frame_count']} 帧 · {replay['fps']:.2f} FPS · {replay['duration_seconds']:.2f} 秒。不同于实时摄像头。")
            st.download_button('下载连续叠框视频', (root / replay['video_file']).read_bytes(), file_name='visual-analyzed-replay.mp4', mime='video/mp4', key='replay-download-' + root.name, on_click='ignore')
