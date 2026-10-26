"""The only v2 execution/capture/export dispatch path.

Loading models, rendering and writing datasets belong inside the claimed
operation. Callers cannot pass a previously-loaded model through this entry.
"""
import importlib
from .admission import claim


def run_operation(admission_path, operation, case_id, backend_module, **kwargs):
    with claim(admission_path,operation,case_id) as case:
        # Import after admission: rejected work must not load a model or integrate.
        backend=importlib.import_module(backend_module)
        handler=getattr(backend,{"execute":"execute_case","capture":"capture_case","export":"export_case"}[operation])
        return handler(case=case,**kwargs)
