"""The native-renderer affinity regression is tested in an isolated process."""
import json
import subprocess
import sys
import unittest


class AffinityInheritanceTests(unittest.TestCase):
    def test_native_style_reset_denied_for_parent_thread_and_child(self):
        code = r'''
import json,os,subprocess,sys,threading
from sage.experiments.codex_trellis_scene_v2.p021_full_workflow import lock_inherited_affinity
original=sorted(os.sched_getaffinity(0)); chosen=original[:2]
os.sched_setaffinity(0,chosen)
lock=lock_inherited_affinity()
out={}
def probe():
    try:
        os.sched_setaffinity(0,original)
    except PermissionError:
        out['thread_denied']=True
    out['thread_mask']=sorted(os.sched_getaffinity(0))
thread=threading.Thread(target=probe);thread.start();thread.join()
child="import os,json; denied=False\ntry: os.sched_setaffinity(0,set(range(192)))\nexcept PermissionError: denied=True\nprint(json.dumps({'denied':denied,'mask':sorted(os.sched_getaffinity(0))}))"
out['child']=json.loads(subprocess.check_output([sys.executable,'-c',child]))
out['chosen']=chosen;out['lock']=lock
print(json.dumps(out))
'''
        result = json.loads(subprocess.check_output([sys.executable,'-c',code]))
        self.assertTrue(result['thread_denied'])
        self.assertTrue(result['child']['denied'])
        self.assertEqual(result['thread_mask'],result['chosen'])
        self.assertEqual(result['child']['mask'],result['chosen'])
        self.assertFalse(result['lock']['cpu_bandwidth_quota_claimed'])


if __name__=='__main__':
    unittest.main()
