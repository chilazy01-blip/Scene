"""Metric top-down inset from exact generated collider poses and real path."""

import numpy as np
import cv2


def draw(frame, scene, case, rows, index):
    origin = np.array([668, 90])
    size = np.array([280, 260])
    pad = 18
    cv2.rectangle(frame, tuple(origin), tuple(origin + size), (31, 37, 47), -1)
    cv2.putText(
        frame,
        "Generated layout / top-down",
        tuple(origin + [10, 18]),
        cv2.FONT_HERSHEY_SIMPLEX,
        0.42,
        (235, 235, 235),
        1,
        cv2.LINE_AA,
    )
    width, length = scene["room"]["width"], scene["room"]["length"]
    scale = min((size[0] - 2 * pad) / width, (size[1] - 45) / length)
    base = origin + np.array([pad, size[1] - 12])

    def point(xy):
        return tuple(
            np.rint(base + np.array([xy[0] * scale, -xy[1] * scale])).astype(int)
        )

    cv2.rectangle(frame, point([0, 0]), point([width, length]), (185, 190, 200), 1)
    for obj in scene["obstacles"]:
        yaw = obj["yaw_rad"]
        c, s = np.cos(yaw), np.sin(yaw)
        rotation = np.array([[c, -s], [s, c]])
        half = np.array(obj["dimensions"][:2]) / 2
        local = np.array([[-1, -1], [1, -1], [1, 1], [-1, 1]]) * half
        vertices = local @ rotation.T + obj["center"][:2]
        polygon = np.array([point(v) for v in vertices], dtype=np.int32)
        cv2.fillConvexPoly(frame, polygon, (82, 105, 127))
        cv2.polylines(frame, [polygon], True, (140, 165, 185), 1, cv2.LINE_AA)
    path = np.array(
        [point(r["actual_root_xyz_before_m"][:2]) for r in rows[: index + 1]],
        dtype=np.int32,
    )
    if len(path) > 1:
        cv2.polylines(frame, [path], False, (70, 205, 250), 2, cv2.LINE_AA)
    cv2.circle(frame, point(case["start_xy_m"]), 4, (235, 170, 70), 1, cv2.LINE_AA)
    cv2.circle(
        frame,
        point(case["goal_xy_m"]),
        max(3, round(0.15 * scale)),
        (60, 230, 85),
        1,
        cv2.LINE_AA,
    )
    cv2.circle(
        frame,
        point(rows[index]["actual_root_xyz_before_m"][:2]),
        4,
        (50, 100, 255),
        -1,
        cv2.LINE_AA,
    )
    return frame
