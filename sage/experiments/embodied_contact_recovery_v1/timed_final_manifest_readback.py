"""Schedule the final saved-artifact readback inside the original sealing window."""
import time
from .work import E,c
from .dispatch import MOD,job
from . import controller_recovery_v4 as controller


def main():
    clock=c.read(E/'RUN_CLOCK.json');start=clock['deadline_epoch']-420
    while time.time()<start:
        state=c.read(E/'STATE.json')
        if state['status']!='active' or state['user_stop'] is not None:
            print({'cancelled_for_control_state':True});return
        time.sleep(min(30,max(.01,start-time.time())))
    state=c.read(E/'STATE.json')
    assert state['status']=='active' and state['active'] is None and state['user_stop'] is None
    key='final_manifest_readback_01'
    assert key not in state['jobs']
    case=E/'cases'/(key+'.json')
    c.write(case,{'manifest':str(E/'EVIDENCE_FILE_MANIFEST.json'),'output':'SEALED_MANIFEST_READBACK.json'})
    definition=job('sealed_manifest_readback',[case],[case,MOD/'work.py',E/'EVIDENCE_FILE_MANIFEST.json'],
        timeout=240,kind='seal',scope='existing_evidence_analysis',pool='export_seal')
    controller.extend_jobs(E,{key:definition},'Final independent full-byte readback of prepared immutable artifact catalog before original deadline')
    result=controller.run_one(E)
    state=c.read(E/'STATE.json')
    assert state['jobs'][key]['status']=='succeeded' and c.read(E/'SEALED_MANIFEST_READBACK.json')['passed']
    print({'readback_passed':True,'decision':result['action'],'whole_run_closure_not_claimed':True})


if __name__=='__main__':main()
