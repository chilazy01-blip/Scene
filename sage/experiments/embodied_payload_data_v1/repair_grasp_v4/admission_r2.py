"""Complete grasp development requires actual numerical force qualification."""
from pathlib import Path
from .admission import claim as prior_claim,AdmissionError
from .resources import read,sha


def require_full_force_admission(admission,case):
    binding=admission.get('force_diagnostic_report',{})
    path=binding.get('path')
    if not path or not Path(path).is_file() or sha(path)!=binding.get('sha256'):
        raise AdmissionError('full_grasp_force_admission_required')
    report=read(path)
    if report.get('passed') is not True or report.get('production_calibrated') is not False:
        raise AdmissionError('full_grasp_force_admission_required')
    model=read(Path(case['package'])/'MODEL_BINDING.json')
    if report.get('model_sha256')!=model['sha256']:
        raise AdmissionError('grasp_force_model_binding_mismatch')
    return report


def claim(path,operation,case_id):
    admission=read(path);case=admission.get('cases',{}).get(case_id,{})
    if operation=='develop' and not case.get('checkpoint',False):require_full_force_admission(admission,case)
    return prior_claim(path,operation,case_id)
