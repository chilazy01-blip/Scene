from sage.experiments.embodied_data_stability_v1.contact_diagnostics import (
    CategorizedContactAudit,
    classify_contact_pair,
)


def test_contact_taxonomy_separates_the_three_s3_failure_mechanisms():
    assert (
        classify_contact_pair(
            "red_block", "right_hand_thumb_2_link", "red_cylinder", "thumb_mesh"
        )
        == "hand_object"
    )
    assert (
        classify_contact_pair("red_block", "table_white", "red_cylinder", "table_white_top")
        == "object_target_table"
    )
    assert classify_contact_pair("right_ankle_roll_link", "world", "foot", "floor") == "foot_ground"


def test_contact_audit_keeps_independent_penetration_and_force_peaks():
    audit = CategorizedContactAudit()
    audit.observe(
        step=4,
        sim_time_s=0.02,
        body_a="red_block",
        body_b="right_hand_middle_0_link",
        geom_a="red_cylinder",
        geom_b="middle",
        distance_m=-0.012,
        force_n=2.0,
    )
    audit.observe(
        step=5,
        sim_time_s=0.025,
        body_a="red_block",
        body_b="right_hand_middle_0_link",
        geom_a="red_cylinder",
        geom_b="middle",
        distance_m=-0.004,
        force_n=8.0,
    )
    report = audit.report()["hand_object"]
    assert report["contact_samples"] == 2
    assert report["physics_steps_with_contact"] == 2
    assert report["max_penetration_m"] == 0.012
    assert report["max_contact_force_n"] == 8.0
    assert report["penetration_peak"]["physics_step"] == 4
    assert report["force_peak"]["physics_step"] == 5
