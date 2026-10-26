"""Prospective finger closing envelope against prohibited geometry.

Intended hand/object intersection is a contact stop, not a predicted achieved
pose. Its depth is omitted only in this virtual envelope; integrated native
penetration gates remain unchanged. This cannot certify contact force quality.
"""
import numpy as np
from ..repair_v2.quality import phase_contacts


def closure_corridor(query, start, targets, finger_ids, source_supports=(), margin=.003):
    target_map=dict(zip(map(int,finger_ids),targets))
    stops={};samples=0
    for side in ('left','right'):
        ids=np.asarray(query.c['inspection']['groups'][side+'_hand'])
        end=start.copy()
        for index in ids:end[query.qmap[index]]=target_map[int(index)]
        count=max(1,int(np.ceil(max(abs(end[query.qmap[ids]]-start[query.qmap[ids]]))/.04)))
        if count>100:return dict(passed=False,reason='closure_envelope_sampling_bound')
        for i,u in enumerate(np.linspace(0,1,count+1)):
            query.set(start*(1-u)+end*u)
            report=query.clearance('pick',margin,source_supports);samples+=1
            other_penetration=0.;contact_stop=None
            for ct in query.d.contact:
                roles=[query.roles[ct.geom1],query.roles[ct.geom2]]
                if set(roles)=={'hand','object'}:
                    hand=(ct.geom1,ct.geom2)[roles.index('hand')]
                    if side in query.names[hand] and ct.dist<=0:
                        contact_stop=dict(sample=i,fraction=float(u),geoms=[query.names[ct.geom1],query.names[ct.geom2]],distance=float(ct.dist))
                else:other_penetration=max(other_penetration,max(0.,-float(ct.dist)))
            if report['forbidden'] or report['minimum_clearance']<margin or other_penetration>.01:
                return dict(passed=False,reason='prohibited_closure_geometry',side=side,sample=i,report=report,prior_contact_stops=stops)
            if contact_stop is not None:
                stops[side]=contact_stop
                break
    return dict(passed=True,samples=samples,contact_stops=stops,
                scope='per_hand_free_motion_until_first_object_contact_only; further_closure_requires_fresh_integrated_evidence')
