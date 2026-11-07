# Copyright (c) Alibaba Cloud.
#
# This source code is licensed under the license found in the
# LICENSE file in the root directory of this source tree.
# Modified for the approved SD1 video review demo: bounded NF4/HF inference,
# documented PyAV video I/O and Chinese task guidance. See patches/ and README.
import os
import copy
import re
from argparse import ArgumentParser
from threading import Thread, Event
from queue import Empty
import json

from local_support import (ROOT, MAX_NEW_TOKENS, configure_environment,
                           configure_processor, prepare_inputs, evidence_note, INFERENCE_LOCK, GENERATION_OPTIONS)
configure_environment()
import gradio as gr
import torch
from transformers import (AutoProcessor, AutoModelForImageTextToText, TextIteratorStreamer,
                          BitsAndBytesConfig, StoppingCriteria, StoppingCriteriaList)

try:
    from vllm import SamplingParams, LLM
    from qwen_vl_utils import process_vision_info
    VLLM_AVAILABLE = True
except ImportError:
    VLLM_AVAILABLE = False
    print("Warning: vLLM not available. Install vllm and qwen-vl-utils to use vLLM backend.")


def _get_args():
    parser = ArgumentParser()

    parser.add_argument('-c',
                        '--checkpoint-path',
                        type=str,
                        default='Qwen/Qwen3-VL-235B-A22B-Instruct',
                        help='Checkpoint name or path, default to %(default)r')
    parser.add_argument('--cpu-only', action='store_true', help='Run demo with CPU only')
    parser.add_argument('--load-in-4bit', action='store_true', help='NF4 for the local 4GB GPU')
    parser.add_argument('--keep-vision-fp16', action='store_true', help='Quantize language layers while preserving the visual encoder')

    parser.add_argument('--flash-attn2',
                        action='store_true',
                        default=False,
                        help='Enable flash_attention_2 when loading the model.')
    parser.add_argument('--share',
                        action='store_true',
                        default=False,
                        help='Create a publicly shareable link for the interface.')
    parser.add_argument('--inbrowser',
                        action='store_true',
                        default=False,
                        help='Automatically launch the interface in a new tab on the default browser.')
    parser.add_argument('--server-port', type=int, default=7860, help='Demo server port.')
    parser.add_argument('--server-name', type=str, default='127.0.0.1', help='Demo server name.')
    parser.add_argument('--backend',
                        type=str,
                        choices=['hf', 'vllm'],
                        default='vllm',
                        help='Backend to use: hf (HuggingFace) or vllm (vLLM)')
    parser.add_argument('--gpu-memory-utilization',
                        type=float,
                        default=0.70,
                        help='GPU memory utilization for vLLM (default: 0.70)')
    parser.add_argument('--tensor-parallel-size',
                        type=int,
                        default=None,
                        help='Tensor parallel size for vLLM (default: auto)')

    args = parser.parse_args()
    return args


def _load_model_processor(args):
    if args.backend == 'vllm':
        if not VLLM_AVAILABLE:
            raise ImportError("vLLM is not available. Please install vllm and qwen-vl-utils.")

        os.environ['VLLM_WORKER_MULTIPROC_METHOD'] = 'spawn'
        tensor_parallel_size = args.tensor_parallel_size
        if tensor_parallel_size is None:
            tensor_parallel_size = torch.cuda.device_count()

        # Initialize vLLM sync engine
        model = LLM(
            model=args.checkpoint_path,
            trust_remote_code=True,
            gpu_memory_utilization=args.gpu_memory_utilization,
            enforce_eager=False,
            tensor_parallel_size=tensor_parallel_size,
            seed=0
        )

        # Load processor for vLLM
        processor = AutoProcessor.from_pretrained(args.checkpoint_path)
        return model, processor, 'vllm'
    else:
        if args.cpu_only:
            device_map = 'cpu'
        else:
            device_map = 'auto'

        # Check if flash-attn2 flag is enabled and load model accordingly
        if args.load_in_4bit:
            if args.cpu_only or not torch.cuda.is_available():
                raise RuntimeError('本机NF4演示需要可用的CUDA显卡，请检查运行权限和驱动。')
            model = AutoModelForImageTextToText.from_pretrained(
                args.checkpoint_path, local_files_only=True,
                quantization_config=BitsAndBytesConfig(
                    load_in_4bit=True, bnb_4bit_quant_type='nf4',
                    bnb_4bit_use_double_quant=True, bnb_4bit_compute_dtype=torch.float16,
                    llm_int8_skip_modules=(['embed_tokens','embedding','lm_head','multi_modal_projector',
                                           'merger','modality_projection','router','visual','vision_tower']
                                          if getattr(args,'keep_vision_fp16',False) else None)),
                dtype=torch.float16, attn_implementation='sdpa', device_map={'': 0},
                low_cpu_mem_usage=True)
        elif args.flash_attn2:
            model = AutoModelForImageTextToText.from_pretrained(args.checkpoint_path,
                                                                    torch_dtype='auto',
                                                                    attn_implementation='flash_attention_2',
                                                                    device_map=device_map)
        else:
            model = AutoModelForImageTextToText.from_pretrained(args.checkpoint_path, device_map=device_map)

        processor = configure_processor(AutoProcessor.from_pretrained(args.checkpoint_path, local_files_only=True))
        return model, processor, 'hf'


def _parse_text(text):
    lines = text.split('\n')
    lines = [line for line in lines if line != '']
    count = 0
    for i, line in enumerate(lines):
        if '```' in line:
            count += 1
            items = line.split('`')
            if count % 2 == 1:
                lines[i] = f'<pre><code class="language-{items[-1]}">'
            else:
                lines[i] = '<br></code></pre>'
        else:
            if i > 0:
                if count % 2 == 1:
                    line = line.replace('`', r'\`')
                    line = line.replace('<', '&lt;')
                    line = line.replace('>', '&gt;')
                    line = line.replace(' ', '&nbsp;')
                    line = line.replace('*', '&ast;')
                    line = line.replace('_', '&lowbar;')
                    line = line.replace('-', '&#45;')
                    line = line.replace('.', '&#46;')
                    line = line.replace('!', '&#33;')
                    line = line.replace('(', '&#40;')
                    line = line.replace(')', '&#41;')
                    line = line.replace('$', '&#36;')
                lines[i] = '<br>' + line
    text = ''.join(lines)
    return text


def _remove_image_special(text):
    text = text.replace('<ref>', '').replace('</ref>', '')
    return re.sub(r'<box>.*?(</box>|$)', '', text)


def _is_video_file(filename):
    video_extensions = ['.mp4', '.avi', '.mkv', '.mov', '.wmv', '.flv', '.webm', '.mpeg']
    return any(filename.lower().endswith(ext) for ext in video_extensions)


def _gc():
    import gc
    gc.collect()
    if torch.cuda.is_available():
        torch.cuda.empty_cache()


def _transform_messages(original_messages):
    transformed_messages = []
    for message in original_messages:
        new_content = []
        for item in message['content']:
            if 'image' in item:
                new_item = {'type': 'image', 'image': item['image']}
            elif 'text' in item:
                new_item = {'type': 'text', 'text': item['text']}
            elif 'video' in item:
                new_item = {'type': 'video', 'video': item['video']}
            else:
                continue
            new_content.append(new_item)

        new_message = {'role': message['role'], 'content': new_content}
        transformed_messages.append(new_message)

    return transformed_messages


def _prepare_inputs_for_vllm(messages, processor):
    """Prepare inputs for vLLM inference"""
    text = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    image_inputs, video_inputs, video_kwargs = process_vision_info(
        messages,
        image_patch_size=processor.image_processor.patch_size,
        return_video_kwargs=True,
        return_video_metadata=True
    )

    mm_data = {}
    if image_inputs is not None:
        mm_data['image'] = image_inputs
    if video_inputs is not None:
        mm_data['video'] = video_inputs

    return {
        'prompt': text,
        'multi_modal_data': mm_data,
        'mm_processor_kwargs': video_kwargs
    }


def _launch_demo(args, model, processor, backend):

    def call_local_model(model, processor, messages, backend):
        messages = _transform_messages(messages)

        if backend == 'vllm':
            # vLLM inference
            inputs = _prepare_inputs_for_vllm(messages, processor)
            sampling_params = SamplingParams(max_tokens=1024)

            accumulated_text = ''
            for output in model.generate(inputs, sampling_params=sampling_params):
                for completion in output.outputs:
                    new_text = completion.text
                    if new_text:
                        accumulated_text += new_text
                        yield accumulated_text
        else:
            # HuggingFace inference
            with INFERENCE_LOCK:
                stop = Event()
                thread = None
                class StopRequested(StoppingCriteria):
                    def __call__(self, input_ids, scores, **kwargs):
                        return stop.is_set()
                try:
                    inputs = prepare_inputs(processor, messages)
                    tokenizer = processor.tokenizer
                    streamer = TextIteratorStreamer(tokenizer, timeout=180.0, skip_prompt=True, skip_special_tokens=True)
                    inputs = {k: v.to(model.device) for k, v in inputs.items()}
                    gen_kwargs = {'max_new_tokens': MAX_NEW_TOKENS, 'streamer': streamer,
                                  **GENERATION_OPTIONS, 'stopping_criteria': StoppingCriteriaList([StopRequested()]), **inputs}
                    errors = []
                    def generate_checked():
                        try:
                            with torch.inference_mode():
                                model.generate(**gen_kwargs)
                        except Exception as error:
                            errors.append(error)
                            streamer.on_finalized_text('', stream_end=True)
                    thread = Thread(target=generate_checked, daemon=True)
                    thread.start()
                    generated_text = ''
                    for new_text in streamer:
                        generated_text += new_text
                        yield generated_text
                    thread.join()
                    if errors:
                        raise gr.Error(f'模型运行失败：{type(errors[0]).__name__}。请清空历史、缩短片段后重试。')
                    yield generated_text + evidence_note(processor)
                except Empty:
                    raise gr.Error('模型生成超时，正在停止本次计算；请缩短片段后重试。')
                except ValueError as error:
                    raise gr.Error(str(error))
                finally:
                    stop.set()
                    if thread is not None:
                        thread.join()  # Keep the GPU lock until the old generation really ends.
                    _gc()

    def create_predict_fn():

        def predict(_chatbot, task_history):
            nonlocal model, processor, backend
            chat_query = _chatbot[-1][0]
            query = task_history[-1][0]
            if not isinstance(query, str) or len(query.strip()) == 0:
                _chatbot.pop()
                task_history.pop()
                return _chatbot
            print('User: ' + _parse_text(query))
            history_cp = copy.deepcopy(task_history)
            full_response = ''
            messages = []
            content = []
            for q, a in history_cp:
                if isinstance(q, (tuple, list)):
                    if _is_video_file(q[0]):
                        content.append({'video': f'{os.path.abspath(q[0])}'})
                    else:
                        content.append({'image': f'{os.path.abspath(q[0])}'})
                else:
                    content.append({'text': q})
                    messages.append({'role': 'user', 'content': content})
                    messages.append({'role': 'assistant', 'content': [{'text': a}]})
                    content = []
            messages.pop()

            for response in call_local_model(model, processor, messages, backend):
                _chatbot[-1] = (_parse_text(chat_query), _remove_image_special(_parse_text(response)))

                yield _chatbot
                full_response = response

            task_history[-1] = (query, full_response)
            print('Qwen-VL-Chat: ' + _parse_text(full_response))
            yield _chatbot

        return predict


    def create_regenerate_fn():

        def regenerate(_chatbot, task_history):
            nonlocal model, processor, backend
            if not task_history:
                return _chatbot
            item = task_history[-1]
            if item[1] is None:
                return _chatbot
            previous_history = list(_chatbot)
            previous_task = list(task_history)
            chatbot_item = _chatbot.pop(-1)
            if chatbot_item[0] is None:
                _chatbot[-1] = (_chatbot[-1][0], None)
            else:
                _chatbot.append((chatbot_item[0], None))
            _chatbot_gen = predict(_chatbot, task_history)
            try:
                for _chatbot in _chatbot_gen:
                    yield _chatbot
            except Exception:
                task_history[:] = previous_task
                _chatbot[:] = previous_history
                yield _chatbot
                raise

        return regenerate

    predict = create_predict_fn()
    regenerate = create_regenerate_fn()

    def add_text(history, task_history, text):
        task_text = text
        history = history if history is not None else []
        task_history = task_history if task_history is not None else []
        history = history + [(_parse_text(text), None)]
        task_history = task_history + [(task_text, None)]
        return history, task_history

    def add_file(history, task_history, file):
        history = history if history is not None else []
        task_history = task_history if task_history is not None else []
        history = history + [((file.name,), None)]
        task_history = task_history + [((file.name,), None)]
        return history, task_history

    def reset_user_input():
        return gr.update(value='')

    def submit_and_predict(history, task_history, text):
        if not text or not text.strip():
            raise gr.Error('请先输入要核查的问题。')
        # Validate media/history before committing a new unanswered turn.
        media = [q for q, _ in (task_history or []) if isinstance(q, (tuple, list))]
        if len(media) != 1:
            raise gr.Error('每段会话请先上传一张图片或一个视频；切换素材前请清空历史。')
        previous_history = list(history or [])
        previous_task = list(task_history or [])
        history, task_history = add_text(history, task_history, text)
        yield history, task_history, ''
        try:
            for updated in predict(history, task_history):
                yield updated, task_history, gr.skip()
        except Exception:
            # Undo the failed turn, so upload/correct/retry remains possible.
            task_history[:] = previous_task
            history[:] = previous_history
            yield history, task_history, text
            raise

    def reset_state(_chatbot, task_history):
        task_history.clear()
        _chatbot.clear()
        _gc()
        return []

    sample_manifest = json.loads((ROOT / 'vision/config/samples.json').read_text())
    suggested_question = '请描述画面中实际可见的人员、机械和作业；指出有画面依据的疑似风险及大致时间，无法确认的情况请明确说明。'
    def load_example(sample_id):
        sample = next(s for s in sample_manifest if s['id'] == sample_id)
        path = str(ROOT / 'downloads/vision-samples' / sample['file'])
        source = f"公开实拍样例：[{sample['author']} / Wikimedia Commons]({sample['source']}) · [{sample['license']}]({sample['license_url']})。非本项目现场；没有权威违规标签。"
        question=suggested_question if _is_video_file(path) else '请描述实际可见的人员、工具或机械、正在处理的物体及防护用品。哪些情况有画面依据值得复核？看不清的细节请明确说明。'
        return [((path,), None)], [((path,), None)], question, source

    video_css = '.control-height video {display:block; width:auto!important; max-width:100%; max-height:320px!important; object-fit:contain; margin-inline:auto;} .control-height [data-testid="user"] img {display:block; width:auto!important; max-width:100%; max-height:400px!important; object-fit:contain; margin-inline:auto;}'
    with gr.Blocks(css=video_css, theme=gr.themes.Default(
            font=['Microsoft YaHei', 'Arial', 'sans-serif'],
            font_mono=['Consolas', 'monospace'])) as demo:
        gr.Markdown('# 施工视频 AI 隐患审查')
        gr.Markdown('基于 Qwen3-VL 开源模型，在本机分析施工图片或60秒以内视频：先确认可见作业，再复核疑似风险。')
        gr.Markdown('示例提问：**画面中有哪些人员、机械和作业？有哪些有画面依据的疑似风险？哪些情况无法确认？**')

        with gr.Row():
            sample_picker = gr.Dropdown([(s['title'], s['id']) for s in sample_manifest], value='florenc', label='选择公开实拍样例')
            sample_btn = gr.Button('载入样例（开启新会话）')
        sample_source = gr.Markdown('也可上传自己的图片或短视频。每段会话只分析一个素材，可连续追问。')

        chatbot = gr.Chatbot(label='视频与 AI 复核记录', elem_classes='control-height', height=620)
        query = gr.Textbox(lines=3, label='向 AI 提问', value='请描述画面中实际可见的人员、机械和作业；指出有画面依据的疑似风险及大致时间，无法确认的情况请明确说明。')
        task_history = gr.State([])

        with gr.Row():
            addfile_btn = gr.UploadButton('📁 Upload (上传文件)', file_types=['image', 'video'])
            submit_btn = gr.Button('🚀 Submit (发送)')
            regen_btn = gr.Button('🤔️ Regenerate (重试)')
            empty_bin = gr.Button('🧹 Clear History (清除历史)')

        submit_btn.click(submit_and_predict, [chatbot, task_history, query],
                         [chatbot, task_history, query], show_progress=True,
                         concurrency_id='vision-model', concurrency_limit=1)
        empty_bin.click(reset_state, [chatbot, task_history], [chatbot], show_progress=True,
                        concurrency_id='vision-model', concurrency_limit=1)
        regen_btn.click(regenerate, [chatbot, task_history], [chatbot], show_progress=True,
                        concurrency_id='vision-model', concurrency_limit=1)
        addfile_btn.upload(add_file, [chatbot, task_history, addfile_btn], [chatbot, task_history], show_progress=True,
                           concurrency_id='vision-model', concurrency_limit=1)
        sample_btn.click(load_example, [sample_picker], [chatbot, task_history, query, sample_source],
                         concurrency_id='vision-model', concurrency_limit=1)

        gr.Markdown('开源来源：[阿里云 Qwen3-VL](https://github.com/QwenLM/Qwen3-VL)（Apache-2.0）。模型按抽样画面回答，疑似风险需结合原片人工复核。')

    demo.queue(default_concurrency_limit=1).launch(
        share=args.share,
        inbrowser=args.inbrowser,
        server_port=args.server_port,
        server_name=args.server_name,
        allowed_paths=[str(ROOT / 'downloads/vision-samples')],
        max_file_size='200mb',
    )


def main():
    args = _get_args()
    model, processor, backend = _load_model_processor(args)
    _launch_demo(args, model, processor, backend)


if __name__ == '__main__':
    main()
