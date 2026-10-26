"""Choose the outward bent-elbow reference branch, not new physical limits."""

from .kinematics import IK as BaseIK, ARM_NAMES


class IK(BaseIK):
    def __init__(self,*args):
        super().__init__(*args)
        self.lower[3]=max(self.lower[3],.05)
        self.upper[1]=min(self.upper[1],-.03)
