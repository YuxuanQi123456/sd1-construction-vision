"""Actual upstream model inference; no synthetic/fixed answers."""
import argparse
import json
from pathlib import Path
import resource
import shutil
import subprocess
import hashlib
import sys
import time
from datetime import datetime, timezone
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_support import ROOT, configure_environment, prepare_inputs, MAX_NEW_TOKENS, GENERATION_OPTIONS
import local_support
configure_environment()
import torch
from runtime_json import write_json_atomic

parser = argparse.ArgumentParser()
parser.add_argument('--preflight', action='store_true')
parser.add_argument('--sample', default='florenc')
parser.add_argument('--all', action='store_true')
parser.add_argument('--save-quantized', action='store_true')
parser.add_argument('--output', default='evidence/V01/model-probe.json')
parser.add_argument('--frames', type=int, default=8)
parser.add_argument('--video-edge', type=int, default=384)
parser.add_argument('--prompt-file')
parser.add_argument('--checkpoint', type=Path)
parser.add_argument('--quantized-output', type=Path)
parser.add_argument('--keep-vision-fp16', action='store_true')
parser.add_argument('--clip-start', type=float, default=0)
parser.add_argument('--clip-duration', type=float)
args = parser.parse_args()
local_support.NUM_FRAMES = args.frames
local_support.VIDEO_EDGE = args.video_edge
if args.prompt_file:
    local_support.SYSTEM_PROMPT = (ROOT/args.prompt_file).read_text()
result = {'torch':torch.__version__, 'cuda_available':torch.cuda.is_available()}
result['configuration'] = {'frames':args.frames, 'video_edge':args.video_edge,
                           'system_prompt':local_support.SYSTEM_PROMPT,
                           'clip_start':args.clip_start,'clip_duration':args.clip_duration}
if not result['cuda_available']:
    raise RuntimeError('CUDA unavailable: run with GPU access outside the restricted sandbox')
result.update({'gpu':torch.cuda.get_device_name(0), 'cuda_capability':torch.cuda.get_device_capability(0),
               'cuda_free_total':list(torch.cuda.mem_get_info())})
torch.set_num_threads(8)
if args.preflight:
    import bitsandbytes as bnb
    layer = bnb.nn.Linear4bit(32,32,compute_dtype=torch.float16,quant_type='nf4').to('cuda')
    y = layer(torch.zeros(1,32,device='cuda',dtype=torch.float16))
    assert torch.isfinite(y).all()
    result['nf4_cuda_kernel'] = 'passed'
    print(json.dumps(result,indent=2))
    (ROOT / 'evidence/V01/gpu-preflight.json').write_text(json.dumps(result,indent=2)+'\n')
    raise SystemExit(0)

output_path = ROOT/args.output
output_path.parent.mkdir(parents=True,exist_ok=True)
result.update({'status':'loading_model','command':sys.argv,
               'started_at':datetime.now(timezone.utc).isoformat()})
def persist_result():
    write_json_atomic(output_path,result)
def record_failure(kind, error, traceback):
    result.update(status='failed',error=f'{kind.__name__}: {error}')
    persist_result()
    sys.__excepthook__(kind,error,traceback)
sys.excepthook=record_failure
persist_result()
from web_demo_mm import _load_model_processor
start = time.monotonic()
checkpoint = ROOT/'downloads/qwen3-vl-2b-nf4'
if args.save_quantized or not checkpoint.exists(): checkpoint = ROOT/'downloads/qwen3-vl-2b'
if args.checkpoint: checkpoint = args.checkpoint.resolve()
result['checkpoint'] = str(checkpoint)
model, processor, backend = _load_model_processor(SimpleNamespace(
    backend='hf', checkpoint_path=str(checkpoint),
    load_in_4bit=True, cpu_only=False, flash_attn2=False,keep_vision_fp16=args.keep_vision_fp16))
import bitsandbytes as bnb
result['visual_fourbit_layers']=sum(isinstance(m,bnb.nn.Linear4bit) for m in model.model.visual.modules())
result['language_fourbit_layers']=sum(isinstance(m,bnb.nn.Linear4bit) for m in model.model.language_model.modules())
result['visual_parameter_dtypes']=sorted({str(p.dtype) for p in model.model.visual.parameters()})
if args.keep_vision_fp16: assert result['visual_fourbit_layers']==0
result.update({'load_seconds':round(time.monotonic()-start,3),
               'model_footprint_bytes':model.get_memory_footprint(),
               'model_is_4bit':getattr(model,'is_loaded_in_4bit',False),
               'results':[]})
print('MODEL_READY', json.dumps({k:v for k,v in result.items() if k!='results'}), flush=True)
result['status']='model_ready'
persist_result()
if args.save_quantized:
    target = args.quantized_output or ROOT/'downloads/qwen3-vl-2b-nf4'
    model.save_pretrained(target, safe_serialization=True)
    for source in checkpoint.iterdir():
        if source.is_file() and source.suffix != '.safetensors' and source.name not in ('config.json','generation_config.json','model.safetensors.index.json'):
            shutil.copy2(source,target/source.name)
    print('QUANTIZED_MODEL_SAVED',str(target),flush=True)
samples = [s for s in json.loads((ROOT/'vision/config/samples.json').read_text())
           if s.get('media_type') != 'image']
if not args.all:
    samples = [s for s in samples if s['id']==args.sample]
assert samples
for sample in samples:
    source_video=ROOT/'downloads/vision-samples'/sample['file']
    if args.clip_duration:
        import imageio_ffmpeg
        clip=ROOT/'.runtime/vision-media'/f'window-{sample["id"]}-{args.clip_start}-{args.clip_duration}.mp4'
        if not clip.exists():
            subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(),'-nostdin','-hide_banner','-loglevel','error',
                            '-y','-ss',str(args.clip_start),'-i',str(source_video),'-t',str(args.clip_duration),
                            '-an','-vf','scale=960:540:force_original_aspect_ratio=decrease:force_divisible_by=2',
                            '-c:v','libx264','-preset','veryfast','-crf','20','-pix_fmt','yuv420p',str(clip)],
                           check=True,capture_output=True,timeout=120)
        source_video=clip
    messages = [{'role':'user','content':[
        {'type':'video','video':str(source_video)},
        {'type':'text','text':'请先描述实际可见的人员、机械和作业。再指出有画面依据的疑似风险及大致时间；没有依据或看不清的情况请明确说明。'}]}]
    start=time.monotonic()
    inputs=prepare_inputs(processor,messages)
    metadata=list(processor._sd1_video_metadata)
    inputs={k:v.to(model.device) for k,v in inputs.items()}
    torch.cuda.reset_peak_memory_stats()
    torch.manual_seed(42)
    with torch.inference_mode():
        generated=model.generate(**inputs,max_new_tokens=MAX_NEW_TOKENS,**GENERATION_OPTIONS)
    count=inputs['input_ids'].shape[-1]
    text=processor.batch_decode(generated[:,count:],skip_special_tokens=True)[0]
    row={'sample':sample['id'],'question':messages[0]['content'][-1]['text'],
         'answer':text,'seconds':round(time.monotonic()-start,3),
         'input_tokens':count,'output_tokens':generated.shape[-1]-count,
         'gpu_peak_allocated':torch.cuda.max_memory_allocated(),
         'gpu_peak_reserved':torch.cuda.max_memory_reserved(),
         'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss,
         'sampling':metadata,'generation_options':GENERATION_OPTIONS,'seed':42}
    result['results'].append(row)
    result['status']='generating'
    persist_result()
    print(json.dumps(row,ensure_ascii=False),flush=True)
    del inputs, generated
    torch.cuda.empty_cache()
result.update(status='completed',finished_at=datetime.now(timezone.utc).isoformat())
persist_result()
