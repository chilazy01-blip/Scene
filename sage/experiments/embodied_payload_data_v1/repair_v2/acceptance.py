"""Versioned conjunction of independent evidence, with no success-label shortcuts."""
from . import METHOD_VERSION, QUALITY_VERSION


REQUIRED = frozenset({
    "native_physics", "native_terminal", "continuous_replay", "native_actuation",
    "phase_contacts", "contact_dynamics", "full_independent_support",
    "foot_transients", "continuous_transport", "grasp_state",
    "finite_floor", "source_integrity", "no_mid_episode_state_writes",
})


def accept_episode(episode_id, checks, binding, *, source_role):
    if set(checks) != REQUIRED:
        raise ValueError("missing_or_unknown_acceptance_checks:"+str(sorted(set(checks)^REQUIRED)))
    if not episode_id or source_role not in {"development","regression","holdout"}:
        raise ValueError("invalid_episode_identity")
    required_bindings={"trace_sha256","model_sha256","controller_sha256","quality_contract_sha256","calibration_sha256"}
    if not required_bindings <= set(binding) or any(not isinstance(binding[k],str) or len(binding[k])!=64 for k in required_bindings):
        raise ValueError("incomplete_evidence_binding")
    # A JSON object or a nonempty string 'failed' must never be truthy success.
    passed=all(value is True for value in checks.values())
    return dict(schema="fullbody-episode-acceptance/v2",episode_id=episode_id,source_role=source_role,
                method_version=METHOD_VERSION,quality_version=QUALITY_VERSION,checks=checks,binding=binding,
                episode_passed=passed,batch_passed=False,data_passed=False,learning_verified=False)


def accept_batch(frozen_case_ids, episodes, *, closed):
    if len(frozen_case_ids)<4 or len(set(frozen_case_ids))!=len(frozen_case_ids):
        raise ValueError("invalid_fresh_holdout_specification")
    ids=[e["episode_id"] for e in episodes]
    if len(set(ids))!=len(ids) or any(i not in frozen_case_ids for i in ids):
        raise ValueError("duplicate_or_unknown_batch_case")
    passed=(not closed and set(ids)==set(frozen_case_ids) and all(
        e.get("episode_passed") is True and e.get("quality_version")==QUALITY_VERSION
        and e.get("source_role")=="holdout" for e in episodes))
    return dict(schema="fullbody-batch-acceptance/v2",batch_passed=passed,
                executed=len(episodes),required=len(frozen_case_ids),closed=closed,
                data_capture_admitted=passed,learning_verified=False)
