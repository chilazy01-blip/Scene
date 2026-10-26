"""Check every moving digit; another digit or the palm cannot stop its sweep."""
import numpy as np


def digit_closure_corridor(query,start,targets,finger_ids,source_supports=(),margin=.003,*,moving_only=True):
    target_map=dict(zip(map(int,finger_ids),targets));stops={};samples=0
    # Unchanged geometry is checked once. At subsequent samples only this
    # digit's geometry moves; contact/penetration still inspect all pairs.
    original_movers=query.movers
    query.set(start);initial=query.clearance('pick',margin,source_supports)
    if initial['forbidden'] or initial['minimum_clearance']<margin:
        return dict(passed=False,reason='initial_prohibited_geometry',report=initial)
    for side in ('left','right'):
        groups={}
        for index in query.c['inspection']['groups'][side+'_hand']:
            joint=int(np.flatnonzero(query.m.jnt_qposadr==query.qmap[index])[0])
            name=query.m.joint(joint).name
            digits=[digit for digit in ('thumb','index','middle') if digit in name]
            if len(digits)!=1:raise ValueError('unbound_digit:'+name)
            groups.setdefault(digits[0],[]).append(index)
        for digit,ids in groups.items():
            ids=np.asarray(ids);end=start.copy()
            for index in ids:end[query.qmap[index]]=target_map[int(index)]
            count=max(1,int(np.ceil(max(abs(end[query.qmap[ids]]-start[query.qmap[ids]]))/.02)))
            if count>200:return dict(passed=False,reason='digit_sampling_bound')
            for i,u in enumerate(np.linspace(0,1,count+1)):
                query.set(start*(1-u)+end*u)
                if moving_only:
                    query.movers=np.asarray([g for g in original_movers if side+'_hand_'+digit+'_' in query.names[g]],dtype=int)
                    if len(query.movers)==0:
                        query.movers=original_movers;raise ValueError('missing_digit_collision_binding')
                try:report=query.clearance('pick',margin,source_supports)
                finally:query.movers=original_movers
                samples+=1
                other_penetration=0.;contact_stop=None
                for ct in query.d.contact:
                    roles=[query.roles[ct.geom1],query.roles[ct.geom2]]
                    if set(roles)=={'hand','object'}:
                        hand=(ct.geom1,ct.geom2)[roles.index('hand')]
                        if side+'_hand_'+digit+'_' in query.names[hand] and ct.dist<=0:
                            contact_stop=dict(sample=i,fraction=float(u),geoms=[query.names[ct.geom1],query.names[ct.geom2]],distance=float(ct.dist))
                    else:other_penetration=max(other_penetration,max(0.,-float(ct.dist)))
                if report['forbidden'] or report['minimum_clearance']<margin or other_penetration>.01:
                    return dict(passed=False,reason='prohibited_digit_geometry',side=side,digit=digit,sample=i,report=report,prior_contact_stops=stops)
                if contact_stop is not None:
                    stops[side+'_'+digit]=contact_stop;break
    return dict(passed=True,samples=samples,contact_stops=stops,scope='per_digit_free_motion_until_own_first_object_contact; integrated_validation_still_required')
