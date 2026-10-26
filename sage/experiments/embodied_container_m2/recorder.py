import h5py
import numpy as np
from sage.experiments.embodied_planner_m2_v2.recorder import Recorder as BaseRecorder, finite_json


class Recorder(BaseRecorder):
    def dump(self, path, seed, result, binding):
        summary = super().dump(path, seed, result, binding)
        with h5py.File(path, 'a') as h:
            h.attrs.update(task='place_in_container', container_audit_schema='container-1khz/v1')
            data = h.create_dataset('privileged/container_1khz', data=np.asarray(self.env.container_rows).reshape(-1, 6), compression='gzip')
            data.attrs['columns'] = 'time_s,inside,side_margin_m,rim_margin_m,bottom_margin_m,bottom_support_n'
        return summary
