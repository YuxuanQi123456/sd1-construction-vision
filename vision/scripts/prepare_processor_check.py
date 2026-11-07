"""Verify actual decoder, timestamps and bounded samples without loading weights."""
import json
from pathlib import Path
import resource
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from local_support import ROOT, NUM_FRAMES, configure_environment, configure_processor, prepare_inputs
configure_environment()
from transformers import AutoProcessor
from transformers.video_utils import VIDEO_DECODERS

def forbidden(*args, **kwargs):
    raise AssertionError('The full-video/alternative decoder must not be used in this test')

VIDEO_DECODERS['torchvision'] = forbidden
VIDEO_DECODERS['torchcodec'] = forbidden
p = configure_processor(AutoProcessor.from_pretrained(ROOT / 'downloads/qwen3-vl-2b', local_files_only=True))
results = []
for sample in json.loads((ROOT / 'vision/config/samples.json').read_text()):
    if sample.get('media_type') == 'image':
        continue
    start = time.monotonic()
    inputs = prepare_inputs(p, [{'role':'user','content':[
        {'type':'video','video':str(ROOT / 'downloads/vision-samples' / sample['file'])},
        {'type':'text','text':'请描述实际可见的人员与机械。'}]}])
    result = {'sample':sample['id'],'seconds':round(time.monotonic()-start,3),
              'input_tokens':inputs['input_ids'].shape[-1],
              'video_grid_thw':inputs['video_grid_thw'].tolist(),
              'metadata':p._sd1_video_metadata,
              'peak_rss_kib':resource.getrusage(resource.RUSAGE_SELF).ru_maxrss}
    assert len(result['metadata'][0]['sampled_indices']) == NUM_FRAMES
    assert result['metadata'][0]['video_backend'] == 'pyav'
    results.append(result)
    print(json.dumps(result,ensure_ascii=False),flush=True)
(ROOT / 'evidence/V04/processor-check.json').write_text(json.dumps(results,ensure_ascii=False,indent=2)+'\n')
