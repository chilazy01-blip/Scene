"""Conservative full-vector endpoint protection for every qualified palm.

Eight signed halfspaces bound the L1 norm in an orthonormal error-aligned
frame. Thus the linearized Euclidean error is at most the native limit minus
its interior reserve. Nonlinear whole-path acceptance remains mandatory.
"""
from itertools import product
import numpy as np
from scipy import sparse
from .component_compiler_r1 import Compiler as Base, solve_qp


class Compiler(Base):
    def problem(self, x, linear, trust):
        cost, matrix, low, high = super().problem(x, linear, trust)
        n, size = self.map.size, matrix.shape[1]
        signs = np.asarray(list(product((-1., 1.), repeat=3)))
        rows, upper, groups = [], [], []
        for sample, (phase, jacobian, error, _, _) in enumerate(linear['endpoints']):
            if self.current['meta']['phases'][phase]['endpoint_palm_error'] > .006:
                continue
            for arm in range(2):
                err = error[3 * arm:3 * arm + 3]
                length = float(np.linalg.norm(err))
                if length <= 1e-12:
                    frame = np.eye(3)
                else:
                    radial = err / length
                    axis = np.eye(3)[int(np.argmin(np.abs(radial)))]
                    lateral = np.cross(radial, axis)
                    lateral /= np.linalg.norm(lateral)
                    frame = np.vstack([radial, lateral, np.cross(radial, lateral)])
                reserve = min(.0005, max(.006 - length, 0.) * .5)
                radius = .006 - reserve
                normals = signs @ frame
                core = sparse.csr_matrix(normals) @ jacobian[3 * arm:3 * arm + 3] / .006
                rows.append(sparse.hstack([core, sparse.csr_matrix((8, size - n))], format='csr'))
                upper.extend((radius - normals @ err) / .006)
                groups.append(dict(sample=sample, phase=phase, arm=arm,
                                   frame=frame.tolist(), radius_m=radius))
        self.objective_record.update(full_vector_palm_protection=True,
                                     palm_inner_polytope_rows=len(upper),
                                     palm_inner_polytope_groups=groups,
                                     linear_euclidean_bound_guaranteed=True)
        if not rows:
            return cost, matrix, low, high
        extra = sparse.vstack(rows, format='csr')
        return (cost, sparse.vstack([matrix[:-size], extra, matrix[-size:]], format='csr'),
                np.r_[low[:-size], np.full(len(upper), -np.inf), low[-size:]],
                np.r_[high[:-size], upper, high[-size:]])
