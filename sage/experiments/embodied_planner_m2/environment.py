"""M2 audit extension; the frozen M1 environment and assets are untouched."""
import mujoco
import numpy as np

from sage.experiments.embodied_scene_bridge.environment import TaskEnvironment


class ExecutionEnvironment(TaskEnvironment):
    def reset(self, seed, jitter=True):
        obs = super().reset(seed, jitter)
        self.audit_rows = []
        self.contact_rows = []
        self.bilateral_streak = 0.
        self.last_pad_forces = [0., 0.]
        self.last_finger_contact = False
        self.last_support_force = 0.
        self.max_penetration = 0.
        self.forbidden_pairs = {}
        self.metrics['robot_self_collision'] = False
        return obs

    def _audit(self):
        # Keep M1's acceptance computation and additionally retain physical
        # contacts at every integration step, including self-collision evidence.
        super()._audit()
        m,d,t = self.model,self.data,self.task
        pads = [0.,0.];finger = False;support = 0.
        for i,c in enumerate(d.contact):
            ids = [int(c.geom1),int(c.geom2)]
            own = [self.owner[j] for j in ids]
            names = [m.geom(j).name for j in ids]
            force = np.zeros(6);mujoco.mj_contactForce(m,d,i,force)
            self.contact_rows.append([float(d.time),float(d.time-.001),*ids,float(c.dist),*force.tolist()])
            penetration = max(0.,-float(c.dist))
            if t['target_body'] in own:
                for name in names:
                    if name.startswith('finger') and 'collision' in name:
                        finger = True
                        pads[int(name[6])-1] += max(0.,float(force[0]))
                if t['support_body'] in own:
                    normal = c.frame[2]*(1 if own.index(t['target_body'])==1 else -1)
                    if normal > .5:
                        support += max(0.,force[0]*normal)
            if 'base' in own:
                robot_index = own.index('base');other = 1-robot_index
                allowed = (names[other]=='robot_mount' or
                           (own[other]==t['target_body'] and names[robot_index].startswith('finger')))
                if not allowed:
                    self.max_penetration = max(self.max_penetration,penetration)
                    if penetration > t['success']['max_forbidden_penetration_m']:
                        pair = '|'.join(sorted(names))
                        self.forbidden_pairs[pair] = self.forbidden_pairs.get(pair,0)+1
                        self.metrics['forbidden_contact'] = True
                        if own == ['base','base']:
                            self.metrics['robot_self_collision'] = True
        self.last_pad_forces = pads
        self.last_finger_contact = finger
        self.last_support_force = float(support)
        bilateral = min(pads)>t['success']['min_bilateral_force_n']
        self.bilateral_streak = self.bilateral_streak+.001 if bilateral else 0.
        pos=d.qpos[self.target_qi:self.target_qi+3]
        self.audit_rows.append([float(d.time),*pos.tolist(),*pads,support,float(finger),
                               self.metrics['goal_xy_error_m'],self.metrics['stable_s'],self.max_penetration])

    def target_pose(self):
        body=self.model.body(self.task['target_body']).id
        matrix=np.eye(4);matrix[:3,:3]=self.data.xmat[body].reshape(3,3)
        matrix[:3,3]=self.data.xpos[body]
        return matrix

    def grip_pose(self):
        matrix=np.eye(4);matrix[:3,:3]=self.data.site_xmat[self.ctrl.site].reshape(3,3)
        matrix[:3,3]=self.data.site_xpos[self.ctrl.site]
        return matrix
