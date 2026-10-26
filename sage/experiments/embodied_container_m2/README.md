# Generated container development task

This module extends the frozen M2 v2 execution/recording contract to a generated storage basket. The public scene CLI assembles the actual asset before adaptation. Source visuals and all six generated object poses are preserved. The basket collider is a disjoint cuboid cover of 5 mm undilated source surface voxels; the cavity is not filled and no support plane is added. Fine woven holes can close at this resolution, so source ray coverage and collision-proxy coverage are reported separately.

Success requires lift, continuous bilateral grasp, release, actual bottom support, and one second with the complete oriented target bounding box inside the certified cavity and below the measured wall rim. Handles do not increase the accepted rim height. Side walls and rim cannot qualify as support. The online audit, planner and recorded contact checks share the specific bottom-geometry allowlist; original furniture and mount checks remain inherited from M2 v2.

Robot mounting and IK feasibility are development adaptation, with every candidate and failed task preserved. The first trajectory exposed an IK admission/tracking mismatch; the revised admission requires the existing concatenated position (m) / rotation-vector (rad) residual norm to be below 0.004, which also bounds position error below 4 mm, before the existing 8 mm execution tracking check. Changes to robot mounting are recorded separately from generated scene edits.

The authoritative protocol, source snapshots, budget, amendments and evidence live at `scene_runs/codex_trellis_v2/embodied_container_m2_20260919_v1`. All simulation, generation, geometry checks and rendering must use its guarded CPU/GPU launchers: at most 8 CPUs, 12/16 GiB memory and 900 s per service, with the existing shared GPU lease/watchdog when rendering. Do not rerun frozen old queues to inspect these results.

This is a privileged planning expert in a development scene. Basket rigidity, object mass/inertia and friction remain assumptions. No official training dataset conversion, synchronized training RGB, ACT training, independent holdout or real-world performance is claimed.
