"""Explicit name/index binding; independent of SDK list ordering and joint axes."""


def indexed_joint_names(joint_to_index, body_names, left_hand_names, right_hand_names,
                        *, body_prefix="robot0_", gripper_prefix="gripper0_"):
    groups = [set(body_names), set(left_hand_names), set(right_hand_names)]
    if sum(map(len, groups)) != len(joint_to_index) or set.union(*groups) != set(joint_to_index):
        raise ValueError("joint_groups_must_partition_model")
    if len(body_names) != len(groups[0]) or len(left_hand_names) != len(groups[1]) or len(right_hand_names) != len(groups[2]):
        raise ValueError("duplicate_group_name")
    indices = list(joint_to_index.values())
    if any(type(i) is not int for i in indices) or sorted(indices) != list(range(len(indices))):
        raise ValueError("model_indices_must_be_bijective")
    result = [None] * len(indices)
    for name, index in joint_to_index.items():
        if name in groups[0]:
            label = body_prefix + name
        elif name in groups[1]:
            label = gripper_prefix + "left_" + name
        else:
            label = gripper_prefix + "right_" + name
        result[index] = label
    if len(set(result)) != len(result):
        raise ValueError("prefixed_names_must_be_unique")
    return result


def permutation_by_names(source_names, destination_names):
    """Destination values are source_values[result]; never infer axis/sign changes."""
    if len(set(source_names)) != len(source_names) or len(set(destination_names)) != len(destination_names):
        raise ValueError("names_must_be_unique")
    if set(source_names) != set(destination_names):
        raise ValueError("source_and_destination_names_must_match")
    lookup = {name: i for i, name in enumerate(source_names)}
    return [lookup[name] for name in destination_names]
