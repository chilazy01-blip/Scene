import numpy as np
import pytest
from .mesh_hand_reference import from_shape,targets,ROLES
from .normal_admittance import update
from sage.experiments.embodied_carry_v1.grasp import RIGHT_CLOSED,group

def test_nonuniform_shape_is_reproduced_without_exceeding_native_reference_limits():
    names=list(RIGHT_CLOSED);shape=np.array([RIGHT_CLOSED[n]*(.2+.02*i) for i,n in enumerate(names)]);template,touch=from_shape(names,shape);assert np.max(np.abs(targets(names,template,touch)-shape))<1e-14
    assert all(abs(v)<=abs(RIGHT_CLOSED[n]) for n,v in template.items());end=targets(names,template,{g:.5 for g in ROLES});assert all(abs(v)<=abs(RIGHT_CLOSED[n])*.5+1e-14 for n,v in zip(names,end))

def test_force_reference_updates_preserve_all_joint_slew_limits_for_nonuniform_shapes():
    names=list(RIGHT_CLOSED);template,_=from_shape(names,[RIGHT_CLOSED[n]*(.2+.02*i) for i,n in enumerate(names)]);closures={g:0. for g in ROLES};filtered={g:0. for g in ROLES};old=targets(names,template,closures)
    for i in range(400):
        for g in ROLES:closures[g],filtered[g]=update(closures[g],filtered[g],float(i%7),2.,max(abs(v) for n,v in template.items() if group(n)==g))
        new=targets(names,template,closures);assert np.max(np.abs(new-old))<=.00600000001;old=new

def test_shape_cannot_reverse_a_joint_or_exceed_original_halfclosed_envelope():
    names=list(RIGHT_CLOSED);q=[RIGHT_CLOSED[n]*.3 for n in names];q[0]=-q[0]
    with pytest.raises(ValueError):from_shape(names,q)
    with pytest.raises(ValueError):from_shape(names,[RIGHT_CLOSED[n]*.6 for n in names])
