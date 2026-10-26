"""Deterministic bounded RRT-Connect for reference poses, never physical state writes."""
import numpy as np
from sage.experiments.embodied_transport_native_v1.contacts import contact_pair


class PlanningBudget(RuntimeError):
    pass


class ArmPlanner:
    def __init__(self, mujoco, model, qids, maximum_checks=4000, seed=20261022):
        self.mj,self.model=mujoco,model
        self.data=mujoco.MjData(model)
        self.qids=np.asarray(qids)
        jids=[int(model.dof_jntid[int(model.joint(i).dofadr[0])]) for i in range(model.njnt) if int(model.joint(i).qposadr[0]) in set(qids)]
        self.lower,self.upper=model.jnt_range[jids].T.copy()
        self.maximum_checks=maximum_checks
        self.seed=seed

    def solve(self, qpos, goal):
        self.checks=0;self.cache={};self.rejections=[]
        original=np.asarray(qpos).copy();start=original[self.qids].copy();goal=np.asarray(goal).copy()
        rng=np.random.default_rng(self.seed)
        def valid(q):
            key=tuple(np.round(q,12))
            if key in self.cache:return self.cache[key]
            if self.checks>=self.maximum_checks:raise PlanningBudget('bounded reference collision budget')
            self.checks+=1
            if np.any(q<self.lower) or np.any(q>self.upper):self.cache[key]=False;return False
            self.data.qpos[:]=original;self.data.qpos[self.qids]=q
            self.mj.mj_kinematics(self.model,self.data);self.mj.mj_comPos(self.model,self.data)
            self.mj.mj_flex(self.model,self.data);self.mj.mj_collision(self.model,self.data)
            bad=[]
            for c in self.data.contact:
                pair=contact_pair(self.model,c);names=[p['name'] for p in pair];bodies=[p['body'] for p in pair]
                robot_scene=any(n.startswith('scene_collision_') for n in names) and any(n.startswith('robot_') for n in names)
                nonfoot_floor='native_floor' in names and not any(b in ('left_ankle_roll_link','right_ankle_roll_link') for b in bodies)
                bad_object='payload_surface' in names and not any(b=='generated_desk' or b.startswith('right_hand_') or b=='right_wrist_yaw_link' for b in bodies)
                if c.dist<-.006 or (robot_scene and c.dist<-.0005) or nonfoot_floor or bad_object:
                    bad.append(dict(pair=pair,distance_m=float(c.dist)))
            ok=not bad;self.cache[key]=ok
            if bad and len(self.rejections)<24:self.rejections.append(dict(angles_rad=q.tolist(),contacts=bad[:5]))
            return ok
        def edge(a,b,resolution=.025):
            count=max(1,int(np.ceil(np.max(np.abs(b-a))/resolution)))
            return all(valid(a+(b-a)*(i/count)) for i in range(1,count+1))
        def extend(tree,target):
            nodes,parents=tree
            i=int(np.argmin([np.linalg.norm(n-target) for n in nodes]));d=target-nodes[i]
            candidate=nodes[i]+d*min(1.,.35/max(np.max(np.abs(d)),1e-12))
            if not edge(nodes[i],candidate):return None,False
            nodes.append(candidate);parents.append(i)
            return len(nodes)-1,bool(np.max(np.abs(candidate-target))<1e-10)
        def backtrack(tree,index):
            path=[]
            while index>=0:path.append(tree[0][index]);index=tree[1][index]
            return path[::-1]
        path=None;failure=None;iterations=0
        try:
            if not valid(start):failure='actual_start_geometry_blocked'
            elif not valid(goal):failure='goal_geometry_blocked'
            elif edge(start,goal):path=[start,goal]
            else:
                trees=[([start],[-1]),([goal],[-1])]
                for iterations in range(800):
                    if self.checks>=self.maximum_checks-600:break
                    a=iterations%2;b=1-a
                    if rng.random()<.2:sample=trees[b][0][-1]
                    elif rng.random()<.8:sample=np.clip((start+goal)/2+rng.normal(size=7)*np.array([1.,.8,1.,.9,1.,.8,1.]),self.lower,self.upper)
                    else:sample=rng.uniform(self.lower,self.upper)
                    ia,_=extend(trees[a],sample)
                    if ia is None:continue
                    target=trees[a][0][ia]
                    for _ in range(30):
                        ib,reached=extend(trees[b],target)
                        if ib is None:break
                        if reached:
                            left=backtrack(trees[a],ia);right=backtrack(trees[b],ib)
                            path=left+right[-2::-1]
                            if a==1:path=path[::-1]
                            break
                    if path is not None:break
                if path is None:failure='bounded_collision_route_not_found'
            if path is not None:
                # Greedy deterministic shortcuts are each collision checked.
                shortened=[path[0]];i=0
                while i<len(path)-1:
                    choices=range(len(path)-1,i,-1);j=i+1
                    for candidate in choices:
                        if self.checks>=self.maximum_checks-400:break
                        if edge(path[i],path[candidate]):j=candidate;break
                    shortened.append(path[j]);i=j
                path=shortened
                if not all(edge(a,b,.025) for a,b in zip(path[:-1],path[1:])):failure='dense_route_validation_failed';path=None
        except PlanningBudget as exc:
            failure=str(exc);path=None
        return dict(passed=path is not None,failure=failure,knots_rad=None if path is None else [q.tolist() for q in path],
                    collision_checks=self.checks,search_iterations=iterations,seed=self.seed,maximum_checks=self.maximum_checks,
                    rejection_examples=self.rejections,new_physics_steps=0,reference_only=True)
