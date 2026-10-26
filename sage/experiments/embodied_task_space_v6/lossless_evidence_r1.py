"""Lossless complete-candidate array storage with explicit byte hashes.

All arrays belong to one evaluation. Aliases/XOR residuals refer only to arrays
inside that same artifact; no phase selection or cross-iteration splicing.
"""
from pathlib import Path
import hashlib,json,zipfile
import numpy as np
from scipy import sparse


def write_arrays(path,arrays):
    path=Path(path)
    if path.exists():raise FileExistsError(path)
    candidates={'reference':'raw_reference','velocity':'raw_velocity','acceleration':'raw_acceleration'}
    metadata={'schema':'whole_candidate_lossless_arrays_v1','arrays':{}}
    canonical={k:np.ascontiguousarray(v) for k,v in arrays.items()}
    for a in canonical.values():
        if a.dtype.hasobject:raise ValueError('object_array_forbidden')
    order=sorted(canonical,key=lambda k:(k in candidates,k))
    temp=path.with_suffix('.pending')
    try:
        with zipfile.ZipFile(temp,'x',compression=zipfile.ZIP_DEFLATED,compresslevel=6) as output:
            for key in order:
                value=canonical[key];raw=value.tobytes();record=dict(dtype=value.dtype.str,shape=list(value.shape),sha256=hashlib.sha256(raw).hexdigest(),bytes=len(raw))
                base=candidates.get(key)
                if base in canonical and canonical[base].dtype==value.dtype and canonical[base].shape==value.shape:
                    record['xor_base']=base;payload=np.bitwise_xor(np.frombuffer(raw,dtype=np.uint8),canonical[base].view(np.uint8).ravel())
                else:payload=np.frombuffer(raw,dtype=np.uint8)
                itemsize=value.dtype.itemsize;shuffled=payload.reshape(-1,itemsize).T.copy().tobytes()
                entry=key+'.bytes';record['entry']=entry;metadata['arrays'][key]=record;output.writestr(entry,shuffled)
            output.writestr('MANIFEST.json',json.dumps(metadata,sort_keys=True,separators=(',',':')))
        temp.replace(path)
    except BaseException:
        # Keep a failed partial artifact as evidence, never overwrite a success.
        raise
    return metadata


def read_arrays(path):
    values={}
    with zipfile.ZipFile(path,'r') as source:
        manifest=json.loads(source.read('MANIFEST.json'))
        if manifest.get('schema')!='whole_candidate_lossless_arrays_v1':raise ValueError('unknown_array_schema')
        records=manifest['arrays'];pending=dict(records)
        while pending:
            progressed=False
            for key,record in list(pending.items()):
                base=record.get('xor_base')
                if base is not None and base not in values:continue
                dtype=np.dtype(record['dtype']);shape=tuple(record['shape']);size=int(np.prod(shape,dtype=np.int64))*dtype.itemsize
                if dtype.hasobject or size!=record['bytes']:raise ValueError('invalid_array_size_or_type')
                shuffled=source.read(record['entry'])
                if len(shuffled)!=size:raise ValueError('array_payload_size')
                raw=np.frombuffer(shuffled,dtype=np.uint8).reshape(dtype.itemsize,-1).T.copy().ravel()
                if base is not None:
                    parent=values[base]
                    if parent.dtype!=dtype or parent.shape!=shape:raise ValueError('xor_source_shape')
                    raw=np.bitwise_xor(raw,parent.view(np.uint8).ravel())
                if hashlib.sha256(raw.tobytes()).hexdigest()!=record['sha256']:raise ValueError('array_integrity_failure:'+key)
                values[key]=raw.view(dtype).reshape(shape).copy();del pending[key];progressed=True
            if not progressed:raise ValueError('cyclic_or_missing_array_dependency')
    return values


def sparse_digest(A):
    A=A.tocsr(copy=True);A.sum_duplicates();A.sort_indices();A.eliminate_zeros()
    h=hashlib.sha256();h.update(np.asarray(A.shape,dtype='<i8').tobytes())
    for v in [A.indptr.astype('<i8'),A.indices.astype('<i8'),A.data.astype('<f8')]:h.update(v.tobytes())
    return h.hexdigest()


def write_prefixed_matrix(folder,A,hard_path,hard):
    folder=Path(folder);A=A.tocsr();n=hard.shape[0]
    expected=sparse.hstack([hard,sparse.csr_matrix((n,A.shape[1]-hard.shape[1]))],format='csr')
    if sparse_digest(A[:n])!=sparse_digest(expected):raise ValueError('matrix_prefix_not_exact')
    sparse.save_npz(folder/'A_TAIL.npz',A[n:])
    record=dict(schema='original_sparse_matrix_exact_prefix_v1',shape=list(A.shape),prefix_rows=n,prefix_path=str(Path(hard_path).resolve()),prefix_file_sha256=hashlib.sha256(Path(hard_path).read_bytes()).hexdigest(),matrix_semantic_sha256=sparse_digest(A))
    (folder/'A_MANIFEST.json').write_text(json.dumps(record,indent=2)+'\n')
    return record


def read_prefixed_matrix(folder):
    folder=Path(folder);record=json.loads((folder/'A_MANIFEST.json').read_text())
    if record.get('schema')!='original_sparse_matrix_exact_prefix_v1':raise ValueError('matrix_schema')
    p=Path(record['prefix_path'])
    if hashlib.sha256(p.read_bytes()).hexdigest()!=record['prefix_file_sha256']:raise ValueError('matrix_prefix_integrity')
    hard=sparse.load_npz(p).tocsr();tail=sparse.load_npz(folder/'A_TAIL.npz').tocsr()
    if hard.shape[0]!=record['prefix_rows'] or tail.shape[1]!=record['shape'][1]:raise ValueError('matrix_shape_mismatch')
    A=sparse.vstack([sparse.hstack([hard,sparse.csr_matrix((hard.shape[0],tail.shape[1]-hard.shape[1]))],format='csr'),tail],format='csr')
    if list(A.shape)!=record['shape'] or sparse_digest(A)!=record['matrix_semantic_sha256']:raise ValueError('original_matrix_integrity')
    return A
