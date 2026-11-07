"""Small, version-bound I/O adapter for the official Qwen3-VL Gradio demo.

The model, tokenizer, sampling rule and chat UI remain upstream implementations.
PyAV selection follows transformers 4.57.6 BaseVideoProcessor.fetch_videos.
"""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import subprocess
from types import MethodType
from threading import Lock

ROOT = Path(__file__).resolve().parents[1]
MEDIA_CACHE = ROOT / '.runtime' / 'vision-media'
NUM_FRAMES = 16
VIDEO_EDGE = 448
IMAGE_EDGE = 1024
MAX_NEW_TOKENS = 384
INFERENCE_LOCK = Lock()
GENERATION_OPTIONS = {'do_sample': True, 'temperature': 0.7, 'top_p': 0.8,
                      'top_k': 20, 'repetition_penalty': 1.1}
SYSTEM_PROMPT = (ROOT/'vision/config/review-prompt-neutral.txt').read_text()


def configure_environment():
    os.environ.setdefault('HF_HUB_OFFLINE', '1')
    os.environ.setdefault('TRANSFORMERS_OFFLINE', '1')
    os.environ.setdefault('GRADIO_ANALYTICS_ENABLED', 'False')
    os.environ.setdefault('HF_HUB_DISABLE_TELEMETRY', '1')
    os.environ.setdefault('GRADIO_TEMP_DIR', str(ROOT / '.runtime' / 'vision-gradio'))
    os.environ['NO_PROXY'] = 'localhost,127.0.0.1,::1'
    os.environ['no_proxy'] = os.environ['NO_PROXY']


def normalize_video(path: str) -> tuple[str, dict]:
    """Use bundled FFmpeg to normalize container metadata; preserve source file."""
    import av
    import imageio_ffmpeg
    source = Path(path).resolve(strict=True)
    if source.stat().st_size > 200 * 1024 * 1024:
        raise ValueError('本机小样限制：视频文件需小于200MB。')
    with av.open(str(source)) as container:
        if not container.streams.video:
            raise ValueError('文件中没有可解码的视频。')
        stream = container.streams.video[0]
        fps = float(stream.average_rate or 0)
        duration = float(container.duration or 0) / 1_000_000
        declared_frames = int(stream.frames or 0)
        if not fps or not 0 < duration <= 60:
            raise ValueError('请上传有有效帧率、时长不超过60秒的视频片段。')
    with source.open('rb') as handle:
        digest = hashlib.file_digest(handle, 'sha256').hexdigest()
    info = {'source_name': source.name, 'source_sha256': digest,
            'source_duration_s': duration, 'source_fps': fps,
            'container_normalized': declared_frames == 0}
    if declared_frames:
        return str(source), info
    MEDIA_CACHE.mkdir(parents=True, exist_ok=True)
    target = MEDIA_CACHE / f'{digest}.mp4'
    if not target.exists():
        temp = MEDIA_CACHE / f'{digest}.part.mp4'
        command = [imageio_ffmpeg.get_ffmpeg_exe(), '-nostdin', '-hide_banner',
                   '-loglevel', 'error', '-y', '-i', str(source), '-an',
                   '-vf', 'scale=960:540:force_original_aspect_ratio=decrease:force_divisible_by=2',
                   '-c:v', 'libx264', '-preset', 'veryfast', '-crf', '20',
                   '-pix_fmt', 'yuv420p', '-movflags', '+faststart', str(temp)]
        subprocess.run(command, check=True, timeout=120, capture_output=True)
        temp.replace(target)
    with av.open(str(target)) as container:
        stream = container.streams.video[0]
        if stream.frames <= 0:
            raise ValueError('规范化后仍无法读取视频帧数。')
        info['normalized_frames'] = stream.frames
        info['normalized_fps'] = float(stream.average_rate)
        info['normalized_duration_s'] = float(container.duration) / 1_000_000
        if abs(info['normalized_duration_s'] - duration) > max(0.15, 2 / fps):
            raise ValueError('视频转换前后时长不一致，停止分析以免时间证据错位。')
    return str(target), info


def configure_processor(processor):
    import transformers
    from transformers.video_utils import load_video
    if transformers.__version__ != '4.57.6':
        raise RuntimeError('视频适配已固定transformers==4.57.6，请先重新验证再升级。')

    def fetch_pyav(self, video_url_or_urls, sample_indices_fn=None):
        if sample_indices_fn is None:
            raise ValueError('必须明确视频抽帧规则。')
        if isinstance(video_url_or_urls, list):
            return list(zip(*[self.fetch_videos(x, sample_indices_fn=sample_indices_fn)
                              for x in video_url_or_urls]))
        normalized, info = normalize_video(video_url_or_urls)
        frames, metadata = load_video(normalized, backend='pyav', sample_indices_fn=sample_indices_fn)
        info.update({'sampled_indices': metadata.frames_indices.tolist(),
                     'sampled_timestamps_s': [round(float(i) / metadata.fps, 3)
                                              for i in metadata.frames_indices],
                     'fps': metadata.fps, 'total_frames': metadata.total_num_frames,
                     'video_backend': metadata.video_backend,
                     'sampled_array_bytes': int(frames.nbytes)})
        processor._sd1_video_metadata.append(info)
        return frames, metadata

    processor._sd1_video_metadata = []
    processor.video_processor.fps = None
    processor.video_processor.fetch_videos = MethodType(fetch_pyav, processor.video_processor)
    processor.video_processor.size = {'shortest_edge': 4096, 'longest_edge': NUM_FRAMES * VIDEO_EDGE * VIDEO_EDGE}
    processor.image_processor.size = {'shortest_edge': 4096, 'longest_edge': IMAGE_EDGE * IMAGE_EDGE}
    return processor


def prepare_inputs(processor, messages):
    media = [part for message in messages for part in message.get('content', [])
             if part.get('type') in ('image', 'video')]
    if len(media) != 1:
        raise ValueError('每段会话请只上传一张图片或一个视频；切换素材前请清空历史。')
    if sum(len(part.get('text', '')) for message in messages
           for part in message.get('content', [])) > 6000:
        raise ValueError('会话已较长，请清空历史后重新上传素材。')
    processor._sd1_video_metadata = []
    if not any(message['role'] == 'system' for message in messages):
        messages = [{'role': 'system', 'content': [{'type': 'text', 'text': SYSTEM_PROMPT}]}] + messages
    inputs = processor.apply_chat_template(messages, tokenize=True, add_generation_prompt=True,
                                          return_dict=True, return_tensors='pt',
                                          num_frames=NUM_FRAMES, fps=None, do_sample_frames=True)
    if inputs['input_ids'].shape[-1] > 4096:
        raise ValueError('本机上下文预算已满，请清空历史后重新上传一个短视频。')
    return inputs


def evidence_note(processor):
    records = processor._sd1_video_metadata
    if not records:
        return '\n\n---\n本次为图片或文本分析；结论待人工复核。'
    times = ', '.join(f'{t:.2f}s' for t in records[-1]['sampled_timestamps_s'])
    return f'\n\n---\n**本轮实际抽样时间**（按帧序号与平均帧率估算）：{times}。仅审查这些采样画面，间隔内的短暂动作可能漏检；可变帧率素材的时间可能有偏差，结论待人工复核。'
