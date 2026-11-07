"""Compare adapted video tensors with native Qwen processing, on CPU only."""
import os
os.environ.update(CUDA_VISIBLE_DEVICES='',HF_HUB_OFFLINE='1',TRANSFORMERS_OFFLINE='1')
import functools
import json
from pathlib import Path
import re
import sys
sys.dont_write_bytecode=True
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import torch
from transformers import AutoProcessor
from transformers.video_utils import load_video
import local_support as ls

root=ls.ROOT
checkpoint=root/'downloads/qwen3-vl-2b'
video=root/'.runtime/vision-media/77412d6c74bcb0f2679b5d6d22a3e617ba8397f5bff9ef4274ba684d92b3504b.mp4'
messages=[{'role':'user','content':[{'type':'video','video':str(video)},
    {'type':'text','text':'请先描述实际可见的人员、机械和作业。再指出有画面依据的疑似风险及大致时间；没有依据或看不清的情况请明确说明。'}]}]
current=ls.configure_processor(AutoProcessor.from_pretrained(checkpoint,local_files_only=True))
actual=ls.prepare_inputs(current,messages)
reference=AutoProcessor.from_pretrained(checkpoint,local_files_only=True)
reference.video_processor.fps=None
reference.video_processor.size=current.video_processor.size.copy()
reference.image_processor.size=current.image_processor.size.copy()
frames,metadata=load_video(str(video),backend='pyav',sample_indices_fn=functools.partial(
    reference.video_processor.sample_frames,num_frames=ls.NUM_FRAMES,fps=None))
full=[{'role':'system','content':[{'type':'text','text':ls.SYSTEM_PROMPT}]}]+messages
text=reference.apply_chat_template(full,tokenize=False,add_generation_prompt=True)
expected=reference(text=text,videos=[frames],video_metadata=[metadata],do_sample_frames=False,return_tensors='pt')
checks={k:{'shape':list(actual[k].shape),'dtype':str(actual[k].dtype),
           'exactly_equal':torch.equal(actual[k],expected[k])} for k in actual}
report={'scope':'CPU tensors only; no model weights or GPU; no hazard-accuracy claim',
        'command':'vision/.venv/bin/python -B vision/scripts/check_processor_equivalence.py',
        'actual_keys':sorted(actual),'reference_keys':sorted(expected),'checks':checks,
        'sampled_indices':metadata.frames_indices.tolist(),
        'timestamps_encoded':re.findall(r'<[0-9.]+ seconds>',reference.tokenizer.decode(actual['input_ids'][0])),
        'video_grid_thw':actual['video_grid_thw'].tolist(),
        'all_passed':sorted(actual)==sorted(expected) and all(v['exactly_equal'] for v in checks.values())}
(root/'evidence/V03/input-equivalence.json').write_text(json.dumps(report,indent=2)+'\n')
print(json.dumps(report,indent=2))
assert report['all_passed']
