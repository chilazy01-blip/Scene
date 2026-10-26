"""Vertical interval witnesses preserve disconnected source solids and holes."""
import numpy as np
import trimesh
from sage.experiments.embodied_scene_quality_v2.contracts import require


def merge_intervals(intervals,tolerance=1e-7):
    result=[]
    for lo,hi in sorted(intervals):
        if hi-lo<=tolerance:continue
        if result and lo<=result[-1][1]+tolerance:result[-1][1]=max(result[-1][1],hi)
        else:result.append([float(lo),float(hi)])
    return result


def deepest_overlap(first,second):
    best=[0.,0.];length=0.
    for a,b in first:
        for c,d in second:
            lo,hi=max(a,c),min(b,d)
            if hi-lo>length:best=[float(lo),float(hi)];length=hi-lo
    return float(length),best


def closed_components(mesh,digits,maximum):
    copy=mesh.copy();copy.merge_vertices(digits_vertex=digits)
    components=list(copy.split(only_watertight=False,repair=False));require(len(components)<=maximum,'source_component_budget')
    closed=[m for m in components if m.is_watertight and abs(m.volume)>1e-12]
    return closed,dict(components=len(components),closed_components=len(closed),open_or_zero_volume_components=len(components)-len(closed),
        merged_digits=digits,source_triangles=len(mesh.faces),geometry_modified=False,
        complete=bool(len(closed)==len(components) and components))


def solid_intervals(components,xy,zstart,tolerance):
    origins=np.c_[xy,np.full(len(xy),zstart)];directions=np.tile([0.,0.,-1.],(len(xy),1))
    result=[[] for _ in xy];known=np.ones(len(xy),dtype=bool)
    for mesh in components:
        hits,indices,_=mesh.ray.intersects_location(origins,directions,multiple_hits=True)
        rows={}
        for i,z in zip(indices,hits[:,2]):rows.setdefault(int(i),[]).append(float(z))
        for i,values in rows.items():
            values.sort();distinct=[]
            for z in values:
                if not distinct or z-distinct[-1]>tolerance:distinct.append(z)
            if len(distinct)%2:
                known[i]=False;continue
            result[i].extend(zip(distinct[::2],distinct[1::2]))
    return [merge_intervals(r,tolerance) for r in result],known


def box_intervals(centers,half_sizes,rotations,xy,tolerance):
    result=[[] for _ in xy]
    for c,s,rot in zip(centers,half_sizes,rotations):
        require(np.max(abs(rot[2,:2]))<1e-8 and np.max(abs(rot[:2,2]))<1e-8 and abs(rot[2,2]-1)<1e-8,'support_box_not_vertical')
        local=(xy-c[:2])@rot[:2,:2]
        inside=np.all(abs(local)<=s[:2]+1e-12,axis=1)
        for index in np.flatnonzero(inside):result[index].append([c[2]-s[2],c[2]+s[2]])
    return [merge_intervals(r,tolerance) for r in result]


def pack(intervals,maximum):
    counts=np.array([len(r) for r in intervals],dtype=np.int32);width=max(1,int(counts.max(initial=0)))
    require(width<=maximum,'interval_budget')
    result=np.zeros((len(intervals),width,2))
    for i,row in enumerate(intervals):
        if row:result[i,:len(row)]=row
    return result,counts


def unpack(values,counts):
    return [values[i,:int(n)].tolist() for i,n in enumerate(counts)]


def compare(source,proxy,tool,source_known,tool_known,complete,threshold):
    source_depth=[];proxy_depth=[];witness=[]
    for s,p,t in zip(source,proxy,tool):
        depth,interval=deepest_overlap(s,t);source_depth.append(depth);witness.append(interval)
        proxy_depth.append(deepest_overlap(p,t)[0])
    source_depth=np.asarray(source_depth);proxy_depth=np.asarray(proxy_depth);witness=np.asarray(witness)
    trusted=np.asarray(source_known)&np.asarray(tool_known)
    positive=trusted&(source_depth>threshold);proxy_positive=np.asarray(tool_known)&(proxy_depth>threshold)
    source_absent=trusted&(source_depth<=threshold) if complete else np.zeros(len(tool),dtype=bool)
    state=('source_interference_witnessed' if positive.any() else
        'proxy_only_on_sampled_rays' if np.any(proxy_positive&source_absent) else 'unknown_or_no_witness')
    return dict(classification=state,source_witness_count=int(positive.sum()),proxy_overlap_count=int(proxy_positive.sum()),
        proxy_only_sample_count=int((proxy_positive&source_absent).sum()),known_ray_count=int(trusted.sum()),
        source_complete=complete,source_max_vertical_overlap_m=float(source_depth[trusted].max(initial=0)),
        proxy_max_vertical_overlap_m=float(proxy_depth[np.asarray(tool_known)].max(initial=0)),
        no_global_clearance_claim=True),dict(source_overlap=source_depth,proxy_overlap=proxy_depth,
        witness_intervals=witness,witness_mask=positive,source_known=source_known,tool_known=tool_known)
