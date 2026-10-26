"""Shared pre-load admission for a causally justified successor."""
from contextlib import contextmanager
import fcntl
import hashlib
import json
import time
from pathlib import Path

from . import METHOD_VERSION, QUALITY_VERSION


class AdmissionError(RuntimeError):
    pass


def sha(path):
    h = hashlib.sha256()
    with Path(path).open("rb") as f:
        for block in iter(lambda: f.read(1024*1024), b""):
            h.update(block)
    return h.hexdigest()


def check(admission, operation, case_id, now=None):
    """Pure check is also used by capture/export; no model import needed."""
    def require(ok, reason):
        if not ok:
            raise AdmissionError(reason)
    require(operation in {"execute", "regress", "develop", "capture", "export"}, "unknown_operation")
    require(admission.get("schema") == "fullbody-admission/v2", "unknown_admission_schema")
    require(admission.get("method_version") == METHOD_VERSION, "method_version_mismatch")
    require(admission.get("quality_version") == QUALITY_VERSION, "quality_version_mismatch")
    require(admission.get("batch_state") == "open", "batch_closed")
    require(admission.get("authorized") is True, "resource_authorization_missing")
    now = time.time() if now is None else now
    require(isinstance(admission.get("deadline_epoch"), (int,float)) and now < admission["deadline_epoch"], "deadline")
    require(admission.get("resource_reserve_verified") is True, "complete_resource_reserve_required")
    cases = admission.get("cases", {})
    require(case_id in cases, "unknown_case")
    case = cases[case_id]
    require(case.get("role") in {"development", "regression", "holdout"}, "unknown_case_role")
    require(not (case["role"] == "holdout" and case.get("seen", True)), "seen_case_is_not_holdout")
    require(admission.get("preflight_passed") is True, "preflight_required")
    if operation in {"regress","develop"}:
        require(case.get("role") == ("regression" if operation=="regress" else "development"), "regression_role_required" if operation=="regress" else "development_role_required")
        require(admission.get("diagnostic_protocol_frozen") is True, "diagnostic_protocol_required")
        require(case.get("production_eligible") is False, "diagnostic_cannot_produce_data")
    else:
        require(admission.get("quality_calibration_passed") is True, "quality_calibration_required")
    if operation in {"capture", "export"}:
        require(admission.get("batch_passed") is True, "batch_not_passed")
        require(case.get("physical_passed") is True and case.get("independent_passed") is True, "episode_not_accepted")
        require(case.get("quality_version") == QUALITY_VERSION, "legacy_quality_not_admitted")
    return case


@contextmanager
def claim(admission_path, operation, case_id):
    """Lock before check+claim and retain claim on failure (no silent retry)."""
    path = Path(admission_path)
    with path.with_suffix(".lock").open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        admission = json.loads(path.read_text())
        case = check(admission, operation, case_id)
        method_state = path.parent/'METHOD_STATE.json'
        if method_state.exists():
            state=json.loads(method_state.read_text())
            if state.get('method_version') != METHOD_VERSION or state.get('closed') is True or state.get('scientific_failures',0) >= 3 or (operation=='develop' and state.get('development_attempts',0)>=3):
                raise AdmissionError('method_scientific_exit')
        transition_path=path.parent/'METHOD_TRANSITION.json'
        if not transition_path.exists():raise AdmissionError('causal_transition_required')
        transition=json.loads(transition_path.read_text())
        prior=Path(transition['prior_method_state'])
        if sha(prior)!=transition['prior_method_state_sha256'] or not json.loads(prior.read_text()).get('closed'):
            raise AdmissionError('prior_closure_changed')
        if transition.get('new_causal_evidence_verified') is not True or transition.get('counters_reset') is not False:
            raise AdmissionError('causal_transition_required')
        bindings = admission.get("files", {})
        if not bindings or any(sha(p) != h for p,h in bindings.items()):
            raise AdmissionError("frozen_input_changed_or_missing")
        if not case_id.replace("_", "").isalnum():
            raise AdmissionError("invalid_case_id")
        claims = path.parent / "claims"
        claims.mkdir(exist_ok=True)
        try:
            with (claims / f"{case_id}.{operation}.json").open("x") as f:
                json.dump(dict(operation=operation, case_id=case_id, admission_sha256=sha(path), epoch=time.time()), f)
        except FileExistsError as e:
            raise AdmissionError("case_already_consumed") from e
        # Keep lock for the operation, preventing concurrent admission mutations.
        yield case
