from pathlib import Path

ROOT = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_expert_branch1_20261026_v1')
PREVIOUS = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_codex_reference_20261025_v1')
ORIGINAL = Path('/data/wsj/main/scene_runs/codex_trellis_v2/embodied_native_sonic_body_grasp_20261025_v1')
PACKAGE = Path(__file__).parent
PYTHON = '/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/cpu_env/bin/python'
ENV37 = '/data/wsj/main/scene_runs/codex_trellis_v2/embodied_stretch_ai_admission_20260926_v1/full_body_milestone/feasibility_guard_v4/prepared/payload_data_20261009/native_parallel_12h_20261011/shared/env37'

# Keep metadata-only tooling usable without importing native physics packages.
import hashlib
import json
import os

HASH_FIELD = 'content_sha256_excluding_this_field'

def canonical(value):
    return hashlib.sha256(json.dumps(value,ensure_ascii=False,sort_keys=True,separators=(',',':'),allow_nan=False).encode()).hexdigest()

def read_bound_json(path):
    document=json.loads(Path(path).read_text())
    if canonical({k:v for k,v in document.items() if k!=HASH_FIELD})!=document.get(HASH_FIELD):
        raise ValueError('content hash mismatch: '+str(path))
    return document

def _file_binding(path):
    path=Path(path).resolve();h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return dict(path=str(path),size_bytes=path.stat().st_size,sha256=h.hexdigest())

def plain(value):
    if isinstance(value,dict):return {k:plain(v) for k,v in value.items()}
    if isinstance(value,(list,tuple)):return [plain(v) for v in value]
    if hasattr(value,'item'):return value.item()
    return value

def safe_save(path,value):
    path=Path(path);body={k:v for k,v in plain(value).items() if k!=HASH_FIELD}
    body[HASH_FIELD]=canonical(body)
    temporary=path.with_name(path.name+'.'+str(os.getpid())+'.tmp')
    temporary.write_text(json.dumps(body,ensure_ascii=False,sort_keys=True,indent=2,allow_nan=False)+'\n')
    temporary.replace(path)

def check(binding):
    if _file_binding(Path(binding['path']))!=binding:
        raise ValueError('changed frozen dependency: '+binding['path'])
