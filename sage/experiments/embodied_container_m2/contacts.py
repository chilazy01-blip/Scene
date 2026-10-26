"""Container bottom is a distinct permitted support; walls/rim remain obstacles."""
from sage.experiments.embodied_planner_m2_v2.contacts import ContactPolicy as BasePolicy


class ContactPolicy(BasePolicy):
    def __init__(self, model, owners, task):
        super().__init__(model, owners, task)
        self.bottom = {model.geom(name).id for name in task['cavity']['bottom_geoms']}
        self.support |= self.bottom
