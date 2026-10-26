"""One contact allowlist for planning, execution and recorded-data validation."""
class ContactPolicy:
    def __init__(self, model, owners, task):
        self.model, self.owners, self.task = model, owners, task
        self.robot = {i for i, owner in owners.items() if owner == 'base'}
        self.target = {i for i, owner in owners.items() if owner == task['target_body']}
        self.support = {i for i, owner in owners.items() if owner == task['support_body']}
        self.fingers = {model.geom(name).id for name in
                        ('finger1_collision', 'finger2_collision',
                         'finger1_pad_collision', 'finger2_pad_collision')}
        self.mount_pair = frozenset((model.geom('link0_collision').id,
                                    model.geom('robot_mount').id))

    def allowed(self, a, b, *, allow_fingers=True, allow_support=True):
        pair = frozenset((int(a), int(b)))
        if pair == self.mount_pair:
            return True
        if a in self.robot or b in self.robot:
            return allow_fingers and ((a in self.fingers and b in self.target)
                                      or (b in self.fingers and a in self.target))
        if a in self.target or b in self.target:
            return allow_support and ((a in self.target and b in self.support)
                                      or (b in self.target and a in self.support))
        return True

    def violations(self, data, threshold, *, allow_fingers=True, allow_support=True):
        return [dict(geoms=[self.model.geom(int(c.geom1)).name,
                           self.model.geom(int(c.geom2)).name], penetration_m=-float(c.dist))
                for c in data.contact if c.dist < -threshold and not self.allowed(
                    int(c.geom1), int(c.geom2), allow_fingers=allow_fingers,
                    allow_support=allow_support)]
