"""Prepared linear endpoint protection within contact-failing phases.

This class only augments the convex subproblem. The matching component acceptance
helper still needs a separately admitted search adapter and independent audit.
"""
import numpy as np
from scipy import sparse
from sage.experiments.embodied_task_space_v10.interior_compiler_r1 import Compiler as Base, solve_qp


class Compiler(Base):
    def problem(self, x, linear, trust):
        cost, matrix, low, high = super().problem(x, linear, trust)
        size = matrix.shape[1]
        n = self.map.size
        rows, lower, upper, protected = [], [], [], []
        for phase, jacobian, error, hand_jacobian, hand_error in linear['endpoints']:
            status = self.current['meta']['phases'][phase]
            if status['passed']:
                continue
            if status['endpoint_hand_error'] <= .012:
                block = sparse.hstack([hand_jacobian / .012,
                                       sparse.csr_matrix((len(hand_error), size - n))], format='csr')
                rows.append(block)
                lower.extend((- .012 - hand_error) / .012)
                upper.extend((.012 - hand_error) / .012)
                protected.append((phase, 'hand'))
            if status['endpoint_palm_error'] <= .006:
                for arm in range(2):
                    err = error[3 * arm:3 * arm + 3]
                    length = float(np.linalg.norm(err))
                    if length <= 1e-12:
                        continue
                    support = sparse.csr_matrix((err / length)[None, :]) @ jacobian[3 * arm:3 * arm + 3]
                    row = sparse.hstack([support / .006, sparse.csr_matrix((1, size - n))], format='csr')
                    reserve = min(.0005, max(.006 - length, 0.) * .5)
                    rows.append(row)
                    lower.append(-np.inf)
                    upper.append((.006 - reserve - length) / .006)
                    protected.append((phase, 'palm'))
        self.objective_record.update(component_endpoint_protection=True,
                                     component_protection_added_rows=len(lower),
                                     component_protection_groups=sorted(set(protected)),
                                     nonlinear_component_acceptance_required=True)
        if not rows:
            return cost, matrix, low, high
        extra = sparse.vstack(rows, format='csr')
        return (cost, sparse.vstack([matrix[:-size], extra, matrix[-size:]], format='csr'),
                np.r_[low[:-size], lower, low[-size:]],
                np.r_[high[:-size], upper, high[-size:]])
