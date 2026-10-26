import json
from pathlib import Path

import pytest

from sage.experiments.embodied_data_stability_v1.audit_candidates import (
    AuditConfigurationError,
    expand_path,
    json_pointer,
    run_audit,
)


CONFIG_DIR = Path(__file__).resolve().parents[1] / "configs"


def test_json_pointer_decodes_tokens_and_lists():
    value = {"a/b": {"~key": [10, 20]}}
    assert json_pointer(value, "/a~1b/~0key/1") == 20


def test_expand_path_rejects_unknown_and_relative_paths():
    with pytest.raises(AuditConfigurationError):
        expand_path("${UNKNOWN}/x", {})
    with pytest.raises(AuditConfigurationError):
        expand_path("relative/path", {})


def test_real_frozen_configs_generate_truthful_incomplete_gate(tmp_path):
    reports = run_audit(
        CONFIG_DIR,
        tmp_path / "run",
        observed_at="2026-10-14T16:00:00+08:00",
    )
    gate = reports["S0_GATE.json"]
    assert gate["audit_implemented"] is True
    assert gate["s0_exit_passed"] is False
    assert gate["physics_attempts"] == 0
    assert gate["network_accessed_during_audit"] is False
    assert gate["native_reproduction_ready_candidates"] == ["source_a_g1_manipulation"]
    assert set(gate["native_reproduction_blocked_candidates"]) == {
        "groot_wbc_sonic",
        "unitree_rl_lab",
    }

    inventory = reports["CANDIDATE_INVENTORY.json"]
    source_a = next(row for row in inventory["candidates"] if row["id"] == "source_a_g1_manipulation")
    assert source_a["status"] == "internal_only"
    assert source_a["s1_native_reproduction_ready"] is True
    historical = next(row for row in source_a["artifacts"] if row["id"] == "historical_native_success")
    assert historical["status"] == "present"
    assert all(item["passed"] for item in historical["json_assertions"])

    license_report = reports["LICENSE_AUDIT.json"]
    source_a_license = next(row for row in license_report["candidates"] if row["candidate_id"] == "source_a_g1_manipulation")
    assert source_a_license["redistribution_ready"] is False
    assert all(scope["evidence_status"] == "absent" for scope in source_a_license["scopes"])

    for name, report in reports.items():
        written = json.loads((tmp_path / "run" / name).read_text(encoding="utf-8"))
        assert (
            written["content_sha256_excluding_this_field"]
            == report["content_sha256_excluding_this_field"]
        )
    for frozen in gate["frozen_inputs"].values():
        assert Path(frozen["path"]).is_file()

