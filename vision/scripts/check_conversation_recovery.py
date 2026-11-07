"""Exercise real callback AST with a fake model; no server or GPU required."""
import ast
import copy
import hashlib
import json
import os
from pathlib import Path
import re
import types

ROOT = Path(__file__).resolve().parents[2]
paths = [ROOT/'vision/web_demo_mm.py', ROOT/'vision/local_support.py']
web, local = [ast.parse(p.read_text()) for p in paths]

class Strip(ast.NodeTransformer):
    def visit_Nonlocal(self, node):
        return None

ns = {'copy':copy, 'os':os, 're':re,
      'gr':types.SimpleNamespace(Error=ValueError, skip=lambda:None),
      'SYSTEM_PROMPT':'test', 'NUM_FRAMES':8, 'print':lambda *a:None}
for tree, names in [(web, ['_parse_text', '_remove_image_special', '_is_video_file',
                         '_transform_messages', 'add_text', 'add_file', 'predict',
                         'submit_and_predict', 'regenerate']), (local, ['prepare_inputs'])]:
    for name in names:
        node = next(n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef) and n.name == name)
        node = Strip().visit(copy.deepcopy(node))
        exec(compile(ast.fix_missing_locations(ast.Module(body=[node],type_ignores=[])),
                     'actual-source-AST','exec'), ns)

class Processor:
    def apply_chat_template(self, *a, **k):
        return {'input_ids':types.SimpleNamespace(shape=[1,32])}

ns.update(model=None,processor=Processor(),backend='hf')
mode = 'ok'
def call(model, processor, messages, backend):
    ns['prepare_inputs'](processor, ns['_transform_messages'](messages))
    if mode == 'fail_before': raise ValueError('intentional pre-output failure')
    yield '测试模型正常输出' if mode == 'ok' else '未完成的流输出'
    if mode == 'fail_after': raise ValueError('intentional streaming failure')

ns['call_local_model'] = call
results, h, state = [], [], []
try:
    list(ns['submit_and_predict'](h,state,'请分析'))
except ValueError as error:
    results.append(['no_media_precheck', not h and not state, str(error)])
h, state = ns['add_file'](h,state,types.SimpleNamespace(name='/test/valid.mp4'))
rows = list(ns['submit_and_predict'](h,state,'上传后请分析'))
h, state, _ = rows[-1]
results.append(['upload_then_submit',len(state)==2 and state[-1][1]=='测试模型正常输出'])
for failure in ['fail_before','fail_after']:
    before, mode, rows = copy.deepcopy((h,state)), failure, []
    try:
        for row in ns['submit_and_predict'](h,state,'后续问题'): rows.append(row)
    except ValueError: pass
    h,state,question = rows[-1]
    results.append([failure+'_rollback',(h,state)==before and question=='后续问题'])
    mode='ok'
    h,state,_=list(ns['submit_and_predict'](h,state,'失败后重发'))[-1]
    results.append([failure+'_retry',state[-1][1]=='测试模型正常输出' and
                    all(a is not None for q,a in state if isinstance(q,str))])
for failure in ['fail_before','fail_after']:
    before, mode = copy.deepcopy((h,state)), failure
    try: list(ns['regenerate'](h,state))
    except ValueError: pass
    results.append(['regenerate_'+failure+'_rollback',(h,state)==before])
mode='ok'
list(ns['regenerate'](h,state))
results.append(['regenerate_success',state[-1][1]=='测试模型正常输出'])
record={'files':{str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest() for p in paths},
        'tests':results,'all_passed':len(results)==9 and all(r[1] for r in results),
        'scope':'actual callback AST, fake processor/model; no server/GPU',
        'command':'python3 vision/scripts/check_conversation_recovery.py'}
print(json.dumps(record,ensure_ascii=False,indent=2))
(ROOT/'evidence/V01/conversation-recovery.json').write_text(json.dumps(record,ensure_ascii=False,indent=2)+'\n')
assert record['all_passed']
