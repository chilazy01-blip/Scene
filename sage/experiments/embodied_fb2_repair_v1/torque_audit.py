"""Independent native controller equations; no call to controller.run_controller."""
import numpy as np
import mujoco


class TorqueAudit:
    def __init__(self, model, qpos_by_pin, inspection):
        self.model = model
        self.qmap = np.asarray(qpos_by_pin)
        self.act = np.asarray([int(np.flatnonzero(model.actuator_trnid[:,0] ==
            int(np.flatnonzero(model.jnt_qposadr==q)[0]))[0]) for q in self.qmap])
        groups = inspection['groups']
        self.parts = {}
        for part, ids in [('legs',groups['lower_body'][:12]),('torso',groups['lower_body'][12:]),
                          ('left',groups['left_arm']),('right',groups['right_arm'])]:
            p = inspection['controllers'][part]['attributes']
            ids = np.asarray(ids)
            self.parts[part] = (ids,self.qmap[ids]-1,self.act[ids],np.array(p['kp']),np.array(p['kd']))
        self.hands = np.asarray(groups['left_hand']+groups['right_hand'])
        self.matrix = np.zeros((model.nv,model.nv))

    def expected(self, data, command):
        m = self.model
        mujoco.mj_fullM(m,self.matrix,data.qM)
        q,v = data.qpos[self.qmap],data.qvel[self.qmap-1]
        answer = np.zeros(m.nu)
        for part,(ids,dofs,aids,kp,kd) in self.parts.items():
            pd = kp*(np.asarray(command)[ids]-q[ids])-kd*v[ids]
            torque = pd if part=='legs' else self.matrix[np.ix_(dofs,dofs)]@pd+data.qfrc_bias[dofs]
            answer[aids] = np.clip(torque,m.actuator_ctrlrange[aids,0],m.actuator_ctrlrange[aids,1])
        answer[self.act[self.hands]] = np.asarray(command)[self.hands]
        return answer

    def check(self, data, command, tolerance=1e-8):
        expected = self.expected(data,command)
        error = float(np.max(np.abs(expected-data.ctrl)))
        if error > tolerance:
            raise RuntimeError('native_actuator_equation_mismatch:'+str(error))
        return error

    def equivalent_target_delta(self, data, part, delta_torque):
        """Local unconstrained inverse. Saturated actuator inversion is not unique."""
        _,dofs,_,kp,_ = self.parts[part]
        mujoco.mj_fullM(self.model,self.matrix,data.qM)
        delta = np.asarray(delta_torque,dtype=float)
        return delta/kp if part=='legs' else np.linalg.solve(self.matrix[np.ix_(dofs,dofs)],delta)/kp
