"""Retarget only missing digits from measured settled arm/object geometry."""
import numpy as np
from .tripod_recontact import plan_recontact
from .planned_tripod_r2 import GROUPS


def retarget(runner, desired):
    result=plan_recontact(runner.model,runner.data,runner.cyl_bid)
    updated=np.asarray(desired).copy()
    if result['valid']:
        for digit in result['missing_digits']:
            ids=GROUPS[digit]
            updated[ids]=np.asarray(result['finger_target_rad'])[ids]
    return updated,result
