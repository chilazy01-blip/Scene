"""Conditional RGB-D capture from accepted saved states, with durable quotas."""
from pathlib import Path
import ctypes
import json
import os
import time
import traceback

import h5py
import numpy as np

from .alignment import accepted_chunks, sha


CAMERAS = ("robot0_oak_egoview", "robot0_right_eef_view")


def capture_chunk(root, trial, output, start, stop):
    root, trial, output = map(Path, (root, trial, output))
    inputs = np.load(root/"prepared/expert_adaptation_20261007/runtime_prepare_r4/CONTROL_INPUTS.npz")
    fields, states, source_binding = accepted_chunks(trial, inputs["qpos_by_pin"])
    assert 0 <= start < stop <= len(states) and stop-start <= 128
    assert not output.exists()
    output.mkdir(parents=True)
    os.environ.update(MUJOCO_GL="egl", PYOPENGL_PLATFORM="egl",
        __EGL_VENDOR_LIBRARY_FILENAMES="/usr/share/glvnd/egl_vendor.d/50_mesa.json",
        LIBGL_ALWAYS_SOFTWARE="1", GALLIUM_DRIVER="llvmpipe", EGL_PLATFORM="surfaceless")
    import mujoco
    from OpenGL import GL, EGL
    from sage.experiments.embodied_rgbd_v1.geometry import intrinsics_from_frustum
    from sage.experiments.embodied_expert_task_v3.static_quota_extension import open_current
    from sage.experiments.embodied_task_space_v6.durable_batch_r1 import Batch

    def forbid(*args, **kwargs):
        raise RuntimeError("saved_state_capture_forbids_physics")
    mujoco.mj_step = mujoco.mj_step1 = mujoco.mj_step2 = forbid
    model = mujoco.MjModel.from_binary_path(str(trial/"MODEL.mjb"))
    frozen_arrays = np.load(root/"prepared/expert_adaptation_20261007/NATIVE_MODEL_ARRAYS_R2.npz")
    assert all(np.array_equal(getattr(model,key),value) for key,value in frozen_arrays.items())
    data = mujoco.MjData(model)
    renderer = None
    result = dict(passed=False, physics_steps=0, policy_forwards=0, start=start, stop=stop,
                  source_trial=str(trial), source_binding=source_binding)
    began = time.monotonic()
    rays = []
    with open_current(root, enable_extension=True) as quota:
        batch = Batch(quota, "render_passes", 4*(stop-start), 4*(stop-start), 4)
        try:
            assert mujoco.__version__ == "3.2.6"
            renderer = mujoco.Renderer(model, height=256, width=256)
            renderer._gl_context.make_current()
            get_string = ctypes.CFUNCTYPE(ctypes.c_char_p, ctypes.c_uint)(EGL.eglGetProcAddress(b"glGetString"))
            device = get_string(GL.GL_RENDERER).decode()
            assert "llvmpipe" in device.lower(), device
            options = mujoco.MjvOption()
            options.geomgroup[3] = 0
            options.sitegroup[:] = 0
            options.flags[mujoco.mjtVisFlag.mjVIS_RANGEFINDER] = False
            base = model.body("robot0_pelvis").id
            far = float(model.vis.map.zfar*model.stat.extent)
            metadata = dict(schema="native-g1-rgbd-fullbody-command-chunks/v1",
                scope="simulation_training", rows=len(states), image_frequency_hz=25,
                command_frequency_hz=50, action_chunk_length=2, cameras=list(CAMERAS),
                source_binding=source_binding, source_trial=str(trial),
                capture="exact saved state at native cached q/dq sensor timestamp",
                depth="ideal registered metric optical depth, no completion or physical sensor noise",
                intrinsics="native MuJoCo camera projection, integer pixel indices are pixel centers",
                extrinsics="optical frame to robot pelvis; world/object poses excluded from learner",
                controller_plan_sha256=sha(trial.parent/"PHYSICAL_PLAN_R1.json"))
            with h5py.File(output/"chunk.h5", "x") as target:
                target.attrs["metadata"] = json.dumps(metadata, sort_keys=True)
                target.attrs["start"] = start
                target.attrs["stop"] = stop
                for key, values in fields.items():
                    target.create_dataset("trajectory/"+key, data=values[start:stop], compression="gzip")
                for name in CAMERAS:
                    for key, shape, dtype in (("rgb", (256,256,3), "u1"), ("depth_m", (256,256), "f4"),
                        ("valid", (256,256), "?"), ("K", (3,3), "f8"), ("optical_to_base", (4,4), "f8")):
                        target.create_dataset(f"cameras/{name}/{key}", shape=(stop-start,*shape),
                            dtype=dtype, chunks=(1,*shape), compression="gzip")
                for local, row in enumerate(range(start, stop)):
                    if time.monotonic() >= float(os.environ["TASK_DEADLINE_MONOTONIC"])-12:
                        raise TimeoutError("bounded_capture_deadline")
                    state = states[row]
                    data.time = state[0]
                    data.qpos[:] = state[1:58]
                    data.qvel[:] = state[58:]
                    mujoco.mj_forward(model, data)
                    base_R = data.xmat[base].reshape(3,3)
                    for name in CAMERAS:
                        cid = model.camera(name).id
                        renderer.disable_depth_rendering()
                        renderer.disable_segmentation_rendering()
                        renderer.update_scene(data, camera=name, scene_option=options)
                        rgb = batch.call(lambda: renderer.render().copy())
                        camera = mujoco.mjv_averageCamera(renderer.scene.camera[0], renderer.scene.camera[1])
                        K = intrinsics_from_frustum(256,256,camera.frustum_near,
                            camera.frustum_bottom,camera.frustum_top,camera.frustum_center)
                        renderer.enable_depth_rendering()
                        depth = batch.call(lambda: renderer.render().copy())
                        valid = np.isfinite(depth) & (depth>0) & (depth<far*(1-1e-5))
                        metric = np.where(valid,depth,0).astype(np.float32)
                        pose = np.eye(4)
                        pose[:3,:3] = data.cam_xmat[cid].reshape(3,3)@np.diag([1.,-1.,-1.])
                        pose[:3,3] = data.cam_xpos[cid]
                        relative = np.eye(4)
                        relative[:3,:3] = base_R.T@pose[:3,:3]
                        relative[:3,3] = base_R.T@(pose[:3,3]-data.xpos[base])
                        for key, value in dict(rgb=rgb,depth_m=metric,valid=valid,K=K,optical_to_base=relative).items():
                            target[f"cameras/{name}/{key}"][local] = value
                        if row in (0,len(states)//2,len(states)-1):
                            ys, xs = np.nonzero(valid)
                            assert len(xs)>=4
                            for i in np.linspace(0,len(xs)-1,4,dtype=int):
                                u,v = int(xs[i]),int(ys[i])
                                ray = np.array([(u-K[0,2])/K[0,0],(v-K[1,2])/K[1,1],1.])
                                length = np.linalg.norm(ray)
                                direction = pose[:3,:3]@ray/length
                                near = float(camera.frustum_near)*length
                                geom = np.array([-1],np.int32)
                                distance = mujoco.mj_ray(model,data,pose[:3,3]+near*direction,
                                    direction,options.geomgroup,1,-1,geom)
                                error = abs((distance+near)/length-float(depth[v,u]))
                                assert distance>=0 and error<.002, (name,row,u,v,error)
                                rays.append(dict(camera=name,row=row,pixel=[u,v],error_m=float(error)))
                    (output/"STATE.json").write_text(json.dumps(dict(completed_rows=local+1,
                        planned_rows=stop-start,render_passes=batch.completed)))
            assert all(np.array_equal(getattr(model,key),value) for key,value in frozen_arrays.items())
            result.update(passed=True,rows=stop-start,gl_renderer=device,
                          chunk_sha256=sha(output/"chunk.h5"),rays=rays,
                          model_unchanged=sha(trial/"MODEL.mjb")==source_binding["MODEL.mjb"])
        except BaseException as error:
            result.update(error=repr(error),traceback=traceback.format_exc())
        finally:
            if renderer is not None:
                renderer.close()
            result.update(elapsed_seconds=time.monotonic()-began,
                          render_passes=batch.completed,render_charged=batch.charged)
            (output/"RESULT.json").write_text(json.dumps(result,indent=2))
    return result


def assemble(chunk_dirs, destination):
    from .reader import PublicSequence
    destination = Path(destination)
    assert not destination.exists()
    entries = []
    for folder in map(Path, chunk_dirs):
        receipt = json.loads((folder/"RESULT.json").read_text())
        assert receipt["passed"] and sha(folder/"chunk.h5")==receipt["chunk_sha256"]
        entries.append((receipt["start"],receipt,folder))
    entries.sort(key=lambda row: row[0])
    cursor = 0
    first_metadata = None
    destination.parent.mkdir(parents=True,exist_ok=True)
    with h5py.File(destination,"x") as output:
        for start, receipt, folder in entries:
            assert start==cursor
            with h5py.File(folder/"chunk.h5","r") as source:
                metadata = json.loads(source.attrs["metadata"])
                if first_metadata is None:
                    first_metadata = metadata
                    output.attrs["metadata"] = json.dumps(metadata,sort_keys=True)
                    def allocate(name,item):
                        if isinstance(item,h5py.Dataset):
                            shape = (metadata["rows"],*item.shape[1:])
                            output.create_dataset(name,shape=shape,dtype=item.dtype,
                                                  chunks=(1,*item.shape[1:]),compression="gzip")
                    source.visititems(allocate)
                assert metadata==first_metadata
                def append(name,item):
                    if isinstance(item,h5py.Dataset):
                        output[name][start:receipt["stop"]] = item[:]
                source.visititems(append)
            cursor = receipt["stop"]
        assert cursor==first_metadata["rows"]
    binding = dict(path=str(destination),sha256=sha(destination),rows=cursor,
        capture_complete=True,complete_physical_task=True,independent_full_task_passed=True,
        source_binding=first_metadata["source_binding"],chunks=[str(row[2]) for row in entries])
    public = PublicSequence(binding)
    assert len(public)==cursor
    destination.with_suffix(".binding.json").write_text(json.dumps(binding,indent=2))
    return binding
