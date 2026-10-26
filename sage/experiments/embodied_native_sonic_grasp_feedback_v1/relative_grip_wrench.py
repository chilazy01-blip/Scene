"""Request contact wrench to retain the actual cup pose relative to the wrist."""
import numpy as np
from scipy.spatial.transform import Rotation

def wrench(weight,mass,hand_p,hand_R,anchor,relative_R,cup_p,cup_R,hand_velocity,cup_velocity):
    r=hand_R@anchor;position=hand_p+r;velocity=hand_velocity[3:]+np.cross(hand_velocity[:3],r);k=weight/.025;d=2*np.sqrt(k*mass);F=np.array([0.,0.,weight])+k*(position-cup_p)-d*(cup_velocity[3:]-velocity);F[:2]=np.clip(F[:2],-.5*weight,.5*weight);F[2]=np.clip(F[2],0,2*weight);error=Rotation.from_matrix(hand_R@relative_R@cup_R.T).as_rotvec();T=np.clip(.05*error-.01*(cup_velocity[:3]-hand_velocity[:3]),-.02,.02);return np.r_[F,T]

def limit_update(old,proposal,ends):
    delta=np.clip(proposal-old,-.006,.006);opening=delta*ends<0;delta=np.where(opening,np.clip(delta,-.001,.001),delta);return np.clip(old+delta,np.minimum(0,ends),np.maximum(0,ends))
